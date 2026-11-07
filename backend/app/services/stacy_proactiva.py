# === ARCHIVO: ClanManager\backend\app\services\stacy_proactiva.py ===
"""Motor de anuncios proactivos automáticos de S.T.A.C.Y. hacia el grupo de WhatsApp."""

import json
import logging
import re
import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.sesion import FabricaSesion
from app.models.asalto import AsaltoCapital, AsaltoDistrito, AsaltoRegistro
from app.models.guerra import Guerra
from app.models.stacy import StacyAristaGrafo, StacyMensajeWhatsapp
from app.services import asaltos as servicio_asaltos
from app.services import guerras as servicio_guerras
from app.services.clash_client import ClashApiError, ClashClient
from app.services.stacy_ai import (
    _CIRCUIT_BREAKER_429,
    _MOTIVO_BLOQUEO,
    _calcular_costo_usd,
    _construir_cola_activa,
    _limpiar_formato_whatsapp,
    _llamar_redactor_etapa2,
    _registrar_exito_modelo,
    _registrar_fallo_modelo,
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
    if not grupos:
        return None
    return grupos[1] if len(grupos) > 1 else grupos[0]


async def disparar_alerta_guerra(
    cliente: ClashClient,
    tipo_evento: str,
    forzar_envio: bool = False,
    guerra_id: int | None = None,
) -> dict:
    """
    Sondea la guerra clásica o CWL en vivo, selecciona la guerra/ronda exacta y publica
    el reporte proactivo de S.T.A.C.Y. en el grupo oficial de WhatsApp.
    """
    chat_id = _obtener_chat_id_principal()
    if not chat_id:
        return {"enviado": False, "motivo": "ALLOWED_GROUP_ID no está configurado en Variables."}

    async with FabricaSesion() as sesion:
        try:
            g_clasica = await servicio_guerras.guardar_guerra_actual(sesion, cliente)
            if g_clasica is None:
                await servicio_guerras.guardar_liga_actual(sesion, cliente)
        except ClashApiError as exc:
            logger.warning("No se pudo refrescar guerra/CWL antes de alerta %s: %s", tipo_evento, exc)

        guerra: Guerra | None = None
        if guerra_id is not None:
            res_id = await sesion.execute(
                select(Guerra)
                .where(Guerra.id == guerra_id)
                .options(selectinload(Guerra.miembros), selectinload(Guerra.ataques))
            )
            guerra = res_id.scalar_one_or_none()

        if guerra is None:
            res = await sesion.execute(
                select(Guerra)
                .order_by(Guerra.preparacion_inicio.desc())
                .limit(5)
                .options(selectinload(Guerra.miembros), selectinload(Guerra.ataques))
            )
            candidatas = list(res.scalars().all())
            if not candidatas:
                return {"enviado": False, "motivo": "No hay guerra registrada en PostgreSQL."}
            en_batalla = [g for g in candidatas if g.estado == "inWar"]
            guerra = en_batalla[0] if en_batalla else candidatas[0]

        id_alerta = f"PROACTIVO_WAR_{guerra.id}_{tipo_evento}"
        if not forzar_envio:
            ya_enviado = await sesion.get(StacyMensajeWhatsapp, id_alerta)
            if ya_enviado is not None:
                return {"enviado": False, "motivo": f"Alerta {id_alerta} ya fue enviada previamente."}

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
    etiqueta_cwl = f"la Ronda {guerra.liga_ronda} de CWL" if es_cwl else "la guerra"

    if tipo_evento == "INICIO":
        if es_cwl:
            return (
                f"¡Acaba de iniciar el Día de Batalla de {etiqueta_cwl} contra '{guerra.rival_nombre}' "
                f"({guerra.tamano_equipo}v{guerra.tamano_equipo})! "
                "Anuncia que tenemos 24 horas y recuerda que en CWL el único ataque (1/1) es OBLIGATORIAMENTE "
                "a su espejo (# contra #) durante las 24 horas, salvo cambio autorizado."
            )
        return (
            f"¡Acaba de iniciar el Día de Batalla contra '{guerra.rival_nombre}' ({guerra.tamano_equipo}v{guerra.tamano_equipo})! "
            "Anuncia que se abren las PRIMERAS 5 HORAS de ataque exclusivo a espejo (# contra #) con el 1.er tiro."
        )
    if tipo_evento == "CORTE_5H":
        return (
            f"¡Se cumplieron las primeras 5 horas de batalla contra '{guerra.rival_nombre}'! "
            "Anuncia oficialmente que TERMINÓ EL BLOQUEO DE ESPEJOS y SE ABRE EL MAPA LIBRE."
        )
    if tipo_evento == "ULTIMAS_3H":
        tiros_txt = "0/1" if es_cwl else "0/2 o 1/2"
        return (
            f"¡ALERTA ROJA: Quedan menos de 3 HORAS para que termine {etiqueta_cwl} contra '{guerra.rival_nombre}'! "
            f"Muestra el marcador y pasa lista nominal de los miembros que siguen sin atacar ({tiros_txt}) "
            "para que entren a cumplir su ataque de inmediato."
        )
    return (
        f"¡{etiqueta_cwl.upper()} CONTRA '{guerra.rival_nombre}' HA FINALIZADO! "
        "Presenta el informe ejecutivo de cierre: veredicto final del marcador, elogio a quienes lograron pleno (3⭐), "
        "reporte de infractores de espejo y lista de quienes dejaron su tiro sin usar."
    )


async def _redactar_con_cola_etapa2(
    prompt_e2: str,
    incluir_firma: bool = True,
) -> tuple[str, dict]:
    t0 = time.monotonic()
    cola_e2 = _construir_cola_activa(2)
    historial_saltos: list[str] = []

    async with httpx.AsyncClient(timeout=25.0) as http:
        for prov2 in cola_e2:
            ahora_ts = time.time()
            nombre_corto = prov2["modelo"].split("/")[-1]
            if _CIRCUIT_BREAKER_429.get(prov2["modelo"], 0) > ahora_ts:
                motivo = _MOTIVO_BLOQUEO.get(prov2["modelo"], "429")
                historial_saltos.append(f"E2:{nombre_corto}[{motivo}]")
                continue

            res2 = await _llamar_redactor_etapa2(http, prov2, prompt_e2)
            if res2["exito"] and res2.get("texto"):
                modelo_e2 = nombre_corto[:50]
                u2 = res2.get("usage") or {}
                tokens = sum(
                    int(u2.get(k) or 0)
                    for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
                )
                costo = _calcular_costo_usd(prov2["modelo"], u2)
                _registrar_exito_modelo(prov2["modelo"], tokens)

                latencia = round(time.monotonic() - t0, 1)
                texto_limpio = _limpiar_formato_whatsapp(res2["texto"])
                nota_salto = f"\n↪ _Saltó: {', '.join(historial_saltos)}_" if historial_saltos else ""
                txt_costo = f" (${costo:.4f})" if costo > 0 else " ($0 Gratis)"
                firma_str = (
                    f"\n━━━━━━━━━━━━\n🤖 _S.T.A.C.Y. [Auto-Scheduler ➔ {modelo_e2}] • "
                    f"⏱️ {latencia}s • 🪙 {tokens:,} tok{txt_costo}_{nota_salto}"
                )

                if incluir_firma and settings.mostrar_firma_modelo:
                    texto_limpio += firma_str

                return texto_limpio, {
                    "modelo": modelo_e2,
                    "tokens": tokens,
                    "costo": costo,
                    "latencia": latencia,
                    "firma": firma_str if settings.mostrar_firma_modelo else "",
                }

            err2 = str(res2.get("error") or "")
            etiqueta_err = _registrar_fallo_modelo(
                prov2["modelo"],
                err2,
                res2.get("retry_after"),
            )
            historial_saltos.append(f"E2:{nombre_corto}[{etiqueta_err}]")

    return (
        "🚨 *AVISO AUTOMÁTICO DE GUERRA — S.T.A.C.Y.*\n\nRevisa el mapa de guerra activa del clan.",
        {"modelo": "fallback", "tokens": 0, "costo": 0.0, "latencia": 0.0, "firma": ""},
    )


def _ensamblar_alerta_capital_hibrida(
    ficha: dict,
    asunto_ia: str,
    cierre_ia: str,
    firma_str: str,
) -> str:
    """
    Ensambla de forma determinista el expediente forense de Capital garantizando que la
    cronología de ataques nunca se trunque y mantenga el diseño de Tarjetas Móviles.
    """
    bloques_cargos: list[str] = []
    for cargo in ficha.get("cargos_infraccion") or []:
        bloques_cargos.append(
            f"• *{cargo['regla_vulnerada']}*\n  └ {cargo['explicacion']}"
        )

    seccion_cargos = "\n".join(bloques_cargos)
    seccion_cronologia = "\n".join(ficha.get("cronologia_detallada") or [])

    partes = [
        "🚨 *AUDITORÍA DE CAPITAL: FALTA DETECTADA*",
        f"*Asunto:* {asunto_ia}",
        f"▸ *REGLA VULNERADA*\n{seccion_cargos}",
        f"▸ *CRONOLOGÍA DE ATAQUES*\n{seccion_cronologia}",
    ]
    if cierre_ia:
        partes.append(f"💬 _{cierre_ia.strip('_')}_")

    cuerpo = "\n\n".join(partes)
    return f"{cuerpo}{firma_str}"


async def auditar_y_alertar_infracciones_capital(
    cliente: ClashClient,
    forzar_envio: bool = False,
) -> dict:
    """
    Revisa la auditoría forense del asalto actual y, si detecta una infracción consumada
    que aún no haya sido denunciada en el grupo, ensambla el reporte híbrido (Asunto +
    Comentario por IA + Cronología determinista en Python) y lo envía por WhatsApp.
    """
    chat_id = _obtener_chat_id_principal()
    if not chat_id:
        return {"alertas_enviadas": 0, "motivo": "ALLOWED_GROUP_ID no configurado"}

    alertas_enviadas = []

    async with FabricaSesion() as sesion:
        res = await sesion.execute(
            select(AsaltoCapital)
            .order_by(AsaltoCapital.inicio.desc())
            .limit(1)
            .options(
                selectinload(AsaltoCapital.miembros),
                selectinload(AsaltoCapital.registros)
                .selectinload(AsaltoRegistro.distritos)
                .selectinload(AsaltoDistrito.ataques),
            )
        )
        asalto = res.scalar_one_or_none()
        if asalto is None:
            return {"alertas_enviadas": 0, "motivo": "Sin asalto registrado"}

        auditoria = servicio_asaltos.construir_auditoria_capital(asalto)
        infractores = auditoria.get("infractores_confirmados") or []

        for ficha in infractores:
            tag_limpio = ficha["tag"].replace("#", "")
            cant_cargos = len(ficha["cargos_infraccion"])
            id_alerta = f"PROACTIVO_CAP_{asalto.id}_{tag_limpio}_C{cant_cargos}"

            if not forzar_envio:
                ya_enviado = await sesion.get(StacyMensajeWhatsapp, id_alerta)
                if ya_enviado is not None:
                    continue

            resumen_cargos = "; ".join(
                f"{c['regla_vulnerada']} ({c['explicacion']})"
                for c in (ficha.get("cargos_infraccion") or [])
            )

            # Prompt ultraligero (~180 tokens): la IA solo redacta el Asunto y el Cierre irónico
            prompt_e2 = (
                "[MODO AUDITORÍA FORENSE DE CAPITAL — S.T.A.C.Y.]\n"
                f"Jugador infractor: {ficha['nick']} | Tiros: `{ficha['tiros_txt']}` | Oro: `{ficha['oro_total']:,}`\n"
                f"Faltas detectadas: {resumen_cargos}\n\n"
                "TAREA: Redacta únicamente 2 líneas en español con tu tono agudo del Alto Mando:\n"
                "ASUNTO: <1 oración directa con el nombre del jugador, sus tiros entre acentos graves y la falta cometida>\n"
                "CIERRE: <1 observación final breve e irónica de máximo 25 palabras recordando rematar los distritos>"
            )

            texto_ia, meta = await _redactar_con_cola_etapa2(prompt_e2, incluir_firma=False)

            asunto_match = re.search(r"ASUNTO:\s*(.+)", texto_ia, flags=re.IGNORECASE)
            cierre_match = re.search(r"CIERRE:\s*(.+)", texto_ia, flags=re.IGNORECASE)

            asunto_final = (
                asunto_match.group(1).strip()
                if asunto_match
                else f"*{ficha['nick']}* (`{ficha['tiros_txt']}`) incumplió el reglamento de remates en la Capital del Clan."
            )
            cierre_final = (
                cierre_match.group(1).strip()
                if cierre_match
                else "En este clan quien abre un distrito y tiene tiros libres lo termina; nada de dejarle el trabajo sucio a los compañeros."
            )

            texto_final = _ensamblar_alerta_capital_hibrida(
                ficha=ficha,
                asunto_ia=asunto_final,
                cierre_ia=cierre_final,
                firma_str=meta.get("firma", ""),
            )

            registro = await sesion.get(StacyMensajeWhatsapp, id_alerta)
            if registro is None:
                registro = StacyMensajeWhatsapp(
                    id_message_wa=id_alerta,
                    chat_id=chat_id,
                    telefono_remitente="AUDITOR_CAPITAL",
                    nombre_whatsapp="Auditoría Automática Capital",
                    jugador_tag_vinculado=ficha["tag"],
                    nivel_acceso_aplicado="CLAN_GLOBAL",
                    mensaje_usuario=f"[AUDITORÍA CAPITAL: {ficha['nick']}]",
                )
                sesion.add(registro)

            registro.respuesta_stacy = texto_final
            registro.modelo_etapa_1 = "forensic_engine"
            registro.modelo_etapa_2 = meta["modelo"]
            registro.herramientas_usadas = ["auditoria_capital_2_etapas"]
            registro.tokens_totales = meta["tokens"]
            registro.costo_total_usd = meta["costo"]
            registro.latencia_segundos = meta["latencia"]
            await sesion.commit()

            exito_wa = await _enviar_whatsapp_grupo(chat_id, texto_final)
            alertas_enviadas.append({
                "jugador": ficha["nick"],
                "id_alerta": id_alerta,
                "enviado": exito_wa,
            })

    return {"alertas_enviadas": len(alertas_enviadas), "detalles": alertas_enviadas}