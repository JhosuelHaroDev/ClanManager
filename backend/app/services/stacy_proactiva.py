"""Motor de anuncios proactivos automáticos de S.T.A.C.Y. hacia el grupo de WhatsApp."""

import json
import logging
import time

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.sesion import FabricaSesion
from app.models.guerra import Guerra
from app.models.stacy import StacyAristaGrafo, StacyMensajeWhatsapp
from app.services import guerras as servicio_guerras
from app.services.clash_client import ClashApiError, ClashClient
from app.services.stacy_ai import (
    _CIRCUIT_BREAKER_429,
    _calcular_costo_usd,
    _construir_cola_activa,
    _limpiar_formato_whatsapp,
    _llamar_redactor_etapa2,
)
from app.services.stacy_tools import _reconstruir_estado_guerra

logger = logging.getLogger("clanmanager.stacy_proactiva")


async def _enviar_whatsapp_grupo(chat_id: str, texto: str) -> bool:
    if not settings.green_api_token or not chat_id:
        logger.warning("Falta GREEN_API_TOKEN o ALLOWED_GROUP_ID para envío proactivo.")
        return False

    url_typing = f"{settings.green_api_url}/waInstance{settings.green_id_instance}/sendTyping/{settings.green_api_token}"
    url_msg = f"{settings.green_api_url}/waInstance{settings.green_id_instance}/sendMessage/{settings.green_api_token}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            try:
                await http.post(url_typing, json={"chatId": chat_id, "typingTime": 3000})
            except httpx.HTTPError:
                pass
            res = await http.post(url_msg, json={"chatId": chat_id, "message": texto})
            return res.status_code == 200
    except httpx.HTTPError as exc:
        logger.error("Error enviando alerta proactiva a Green-API: %s", exc)
        return False


def _obtener_chat_id_principal() -> str | None:
    if not settings.allowed_group_id:
        return None
    grupos = [g.strip() for g in settings.allowed_group_id.split(",") if g.strip()]
    return grupos[0] if grupos else None


async def disparar_alerta_guerra(
    cliente: ClashClient,
    tipo_evento: str,
    forzar_envio: bool = False,
) -> dict:
    """
    Sondea la guerra en vivo, verifica que el aviso no se haya enviado antes
    y publica el reporte proactivo de S.T.A.C.Y. en el grupo de WhatsApp.
    tipos soportados: 'INICIO' | 'CORTE_5H' | 'ULTIMAS_3H' | 'FINAL'
    """
    chat_id = _obtener_chat_id_principal()
    if not chat_id:
        return {"enviado": False, "motivo": "ALLOWED_GROUP_ID no está configurado en Variables."}

    async with FabricaSesion() as sesion:
        try:
            await servicio_guerras.guardar_guerra_actual(sesion, cliente)
        except ClashApiError as exc:
            logger.warning("No se pudo refrescar guerra antes de alerta %s: %s", tipo_evento, exc)

        res = await sesion.execute(
            select(Guerra)
            .order_by(Guerra.preparacion_inicio.desc())
            .limit(1)
            .options(selectinload(Guerra.miembros), selectinload(Guerra.ataques))
        )
        guerra = res.scalar_one_or_none()
        if guerra is None:
            return {"enviado": False, "motivo": "No hay guerra registrada en PostgreSQL."}

        id_alerta = f"PROACTIVO_WAR_{guerra.id}_{tipo_evento}"
        if not forzar_envio:
            ya_enviado = await sesion.get(StacyMensajeWhatsapp, id_alerta)
            if ya_enviado is not None:
                return {"enviado": False, "motivo": f"Alerta {id_alerta} ya fue enviada previamente."}

        # Cargar acuerdos de espejo activos en el Grafo de Memoria
        res_grafo = await sesion.execute(
            select(StacyAristaGrafo)
            .where(
                StacyAristaGrafo.es_activa.is_(True),
                StacyAristaGrafo.tipo_relacion == "CAMBIO_ESPEJO_CON",
            )
            .options(
                selectinload(StacyAristaGrafo.nodo_origen),
                selectinload(StacyAristaGrafo.nodo_destino),
            )
        )
        cambios_set: set[tuple[str, str]] = set()
        for ar in res_grafo.scalars().all():
            n1 = ar.nodo_origen.nombre_entidad.lower()
            n2 = ar.nodo_destino.nombre_entidad.lower()
            cambios_set.add((n1, n2))
            cambios_set.add((n2, n1))

        paquete = _reconstruir_estado_guerra(guerra, cambios_set)
        datos_resumen = _extraer_resumen_para_alerta(paquete, guerra)
        instruccion_evento = _construir_instruccion_evento(tipo_evento, guerra)

        prompt_e2 = (
            "[MODO PROACTIVO AUTOMÁTICO DE S.T.A.C.Y. PARA TODO EL GRUPO DE WHATSAPP]\n"
            "[Destinatario: Todo el clan 'Melanie Stacy' y el Alto Mando]\n\n"
            f"EVENTO DISPARADO: {instruccion_evento}\n\n"
            f"DATOS EN TIEMPO REAL DE POSTGRESQL:\n{json.dumps(datos_resumen, ensure_ascii=False)}\n\n"
            "INSTRUCCIÓN DE REDACCIÓN: Redacta el anuncio oficial para el grupo de WhatsApp en español, "
            "con tu personalidad nivel 2.5 (ingeniosa, ejecutiva y picante), usando el estándar visual móvil "
            "(título en mayúsculas con emoji, subtítulos con '▸ *', viñetas '• ', subdetalles '  └ ' y cifras entre `acentos graves`)."
        )

        texto_final, meta = await _redactar_con_cola_etapa2(prompt_e2)

        # Registrar en stacy_mensajes_whatsapp para idempotencia y memoria de corto plazo
        registro = await sesion.get(StacyMensajeWhatsapp, id_alerta)
        if registro is None:
            registro = StacyMensajeWhatsapp(
                id_message_wa=id_alerta,
                chat_id=chat_id,
                telefono_remitente="SISTEMA_SCHEDULER",
                nombre_whatsapp="Anuncio Proactivo S.T.A.C.Y.",
                nivel_acceso_aplicado="CLAN_GLOBAL",
                mensaje_usuario=f"[ANUNCIO AUTOMÁTICO: {tipo_evento}]",
            )
            sesion.add(registro)

        registro.respuesta_stacy = texto_final
        registro.modelo_etapa_1 = "scheduler"
        registro.modelo_etapa_2 = meta["modelo"]
        registro.herramientas_usadas = [f"alerta_{tipo_evento.lower()}"]
        registro.tokens_totales = meta["tokens"]
        registro.costo_total_usd = meta["costo"]
        registro.latencia_segundos = meta["latencia"]
        await sesion.commit()

    exito_wa = await _enviar_whatsapp_grupo(chat_id, texto_final)
    logger.info("Alerta proactiva %s enviada a WhatsApp (%s): %s", id_alerta, chat_id, exito_wa)
    return {
        "enviado": exito_wa,
        "id_alerta": id_alerta,
        "chat_id": chat_id,
        "mensaje": texto_final,
    }


def _extraer_resumen_para_alerta(paquete: dict, guerra: Guerra) -> dict:
    infractores = []
    cracks = []
    sin_atacar_0 = []
    falta_1 = []
    bases_abiertas = []

    for x in paquete["filas"]:
        if "infraccion" in x["obs"].lower():
            infractores.append(f"#{x['pos']} {x['nick']}: {x['obs']} (T1:{x['t1']} | T2:{x['t2']})")
        if "Doble Pleno" in x["obs"] or ("3*" in x["t1"] and x["perm"] == 1):
            cracks.append(f"#{x['pos']} {x['nick']} (T1:{x['t1']}{(' + T2:' + x['t2']) if x['t2'] not in ('-', 'N/A(CWL)') else ''})")
        elif "3*" in x["t1"] and x["usados"] == 1:
            cracks.append(f"#{x['pos']} {x['nick']} (Pleno en T1:{x['t1']}, falta 2do tiro)")

        if x["usados"] == 0:
            sin_atacar_0.append(f"#{x['pos']} {x['nick']}[TH{x['th']}]")
        elif x["usados"] < x["perm"]:
            falta_1.append(f"#{x['pos']} {x['nick']}[TH{x['th']}] (T1:{x['t1']})")

        if "100%" not in x["estado_rival"]:
            bases_abiertas.append(f"#{x['pos']}[TH{x['rival_th']}]: {x['estado_rival']}")

    return {
        "marcador": paquete["marcador"],
        "rival": guerra.rival_nombre,
        "infractores_regla_5h": infractores or ["Ninguno"],
        "destacados_plenos": cracks[:12],
        "sin_atacar_0_tiros_total": len(sin_atacar_0),
        "sin_atacar_0_tiros_lista": sin_atacar_0,
        "falta_segundo_tiro_total": len(falta_1),
        "falta_segundo_tiro_lista": falta_1,
        "bases_rivales_abiertas_total": len(bases_abiertas),
        "bases_rivales_abiertas_muestra": bases_abiertas[:12],
    }


def _construir_instruccion_evento(tipo_evento: str, guerra: Guerra) -> str:
    es_cwl = bool(guerra.war_tag)
    if tipo_evento == "INICIO":
        if es_cwl:
            return (
                f"¡Acaba de iniciar el Día de Batalla de CWL contra '{guerra.rival_nombre}'! "
                "Anuncia que tenemos 24 horas y recuerda que en CWL el único tiro (1/1) es OBLIGATORIAMENTE a su espejo (# contra #)."
            )
        return (
            f"¡Acaba de iniciar el Día de Batalla contra '{guerra.rival_nombre}' ({guerra.tamano_equipo}v{guerra.tamano_equipo})! "
            "Anuncia que se abren las PRIMERAS 5 HORAS de ataque exclusivo a espejo (# contra #) con el 1.er tiro. "
            "Advierte con humor que nadie robe espejos ajenos ni gaste su 2.º tiro antes de las 5 horas."
        )
    if tipo_evento == "CORTE_5H":
        return (
            f"¡Se cumplieron las primeras 5 horas de batalla contra '{guerra.rival_nombre}'! "
            "Anuncia oficialmente que TERMINÓ EL BLOQUEO DE ESPEJOS y SE ABRE EL MAPA LIBRE para limpieza de 3⭐ y segundos tiros. "
            "Muestra el marcador actual, felicita a los que ya aseguraron su espejo con 3⭐, exhibe con sarcasmo si hubo algún infractor "
            "que se adelantó antes de las 5h, y menciona cuántas bases rivales quedan abiertas."
        )
    if tipo_evento == "ULTIMAS_3H":
        return (
            f"¡ALERTA ROJA: Quedan menos de 3 HORAS para que termine la guerra contra '{guerra.rival_nombre}'! "
            "Muestra el marcador, pasa lista nominal de los miembros que siguen en 0/2 (pregúntales con ironía si firmaron un tratado de paz) "
            "y de los que están en 1/2 para que entren a rematar las bases abiertas ya mismo."
        )
    return (
        f"¡LA GUERRA CONTRA '{guerra.rival_nombre}' HA FINALIZADO! "
        "Presenta el informe ejecutivo de cierre: veredicto final del marcador, elogio a los Cracks que hicieron Doble Pleno (6⭐), "
        "reporte de infractores de la regla de las 5h y lista de quienes dejaron tiros colgados sin usar (0/2 o 1/2) para auditoría del Alto Mando."
    )


async def _redactar_con_cola_etapa2(prompt_e2: str) -> tuple[str, dict]:
    t0 = time.monotonic()
    cola_e2 = _construir_cola_activa(2)
    ahora_ts = time.time()
    historial_saltos = []

    async with httpx.AsyncClient(timeout=25.0) as http:
        for prov2 in cola_e2:
            if _CIRCUIT_BREAKER_429.get(prov2["modelo"], 0) > ahora_ts:
                historial_saltos.append(f"E2:{prov2['modelo'].split('/')[-1]}[429]")
                continue

            res2 = await _llamar_redactor_etapa2(http, prov2, prompt_e2)
            if res2["exito"] and res2.get("texto"):
                modelo_e2 = prov2["modelo"].split("/")[-1]
                u2 = res2.get("usage") or {}
                tokens = sum(
                    int(u2.get(k) or 0)
                    for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
                )
                costo = _calcular_costo_usd(prov2["modelo"], u2)
                latencia = round(time.monotonic() - t0, 1)
                texto_limpio = _limpiar_formato_whatsapp(res2["texto"])

                if settings.mostrar_firma_modelo:
                    txt_costo = f" (${costo:.4f})" if costo > 0 else " ($0 Gratis)"
                    nota_salto = f"\n↪ _Saltó: {', '.join(historial_saltos)}_" if historial_saltos else ""
                    texto_limpio += (
                        f"\n━━━━━━━━━━━━\n🤖 _S.T.A.C.Y. [Auto-Scheduler ➔ {modelo_e2}] • "
                        f"⏱️ {latencia}s • 🪙 {tokens:,} tok{txt_costo}_{nota_salto}"
                    )
                return texto_limpio, {
                    "modelo": modelo_e2,
                    "tokens": tokens,
                    "costo": costo,
                    "latencia": latencia,
                }

            err2 = str(res2.get("error") or "")
            if "429" in err2:
                _CIRCUIT_BREAKER_429[prov2["modelo"]] = ahora_ts + 60.0
            historial_saltos.append(f"E2:{prov2['modelo'].split('/')[-1]}")

    return (
        "🚨 *AVISO AUTOMÁTICO DE GUERRA — S.T.A.C.Y.*\n\nRevisa el mapa de guerra activa del clan.",
        {"modelo": "fallback", "tokens": 0, "costo": 0.0, "latencia": 0.0},
    )