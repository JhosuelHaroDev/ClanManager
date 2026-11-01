"""Servicio de Asaltos a la Capital con Sondeo en 2 Etapas y Motor Forense Calibrado."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.asalto import (
    AsaltoAtaque,
    AsaltoCapital,
    AsaltoDistrito,
    AsaltoMiembro,
    AsaltoRegistro,
)
from app.schemas.asalto import AsaltoOut, RegistroCapitalOut
from app.services.clash_client import ClashClient

logger = logging.getLogger("clanmanager.asaltos")

# Caché en RAM para la Etapa 1 del sondeo: {inicio_iso: (ataques_totales, estado)}
_CACHE_ETAPA1_CAPITAL: dict[str, tuple[int, str]] = {}
_ULTIMO_CAMBIO_DETECTADO_UTC: datetime | None = None


def hay_posible_timeout_pendiente(ahora_utc: datetime) -> bool:
    """Indica si transcurrieron >= 15 min desde el último golpe para revisar abandonos."""
    if _ULTIMO_CAMBIO_DETECTADO_UTC is None:
        return False
    minutos = (ahora_utc - _ULTIMO_CAMBIO_DETECTADO_UTC).total_seconds() / 60.0
    return 15.0 <= minutos <= 30.0


async def sondear_asalto_dos_etapas(
    sesion: AsyncSession,
    cliente: ClashClient,
    forzar_etapa_2: bool = False,
) -> tuple[AsaltoCapital | None, bool]:
    """
    ETAPA 1 (Centinela en RAM): Verifica si `totalAttacks` aumentó respecto al sondeo previo.
    ETAPA 2 (Sondeo Profundo): Solo toca PostgreSQL cuando hay ataques nuevos.
    """
    global _ULTIMO_CAMBIO_DETECTADO_UTC

    items = await cliente.obtener_asaltos_capital(limite=1)
    if not items:
        return None, False

    raw_actual = items[0]
    inicio_str = str(raw_actual.get("startTime") or "")
    total_ataques_api = int(raw_actual.get("totalAttacks") or 0)
    estado_api = str(raw_actual.get("state") or "")

    previo = _CACHE_ETAPA1_CAPITAL.get(inicio_str)
    if (
        not forzar_etapa_2
        and previo is not None
        and previo[0] == total_ataques_api
        and previo[1] == estado_api
    ):
        return None, False

    asalto = await _guardar_desde_raw_preservando_timestamps(sesion, raw_actual)
    if asalto is not None:
        _CACHE_ETAPA1_CAPITAL[inicio_str] = (total_ataques_api, estado_api)
        _ULTIMO_CAMBIO_DETECTADO_UTC = datetime.now(timezone.utc)
        return asalto, True

    return None, False


async def guardar_asalto_actual(
    sesion: AsyncSession, cliente: ClashClient
) -> AsaltoCapital | None:
    """Guarda o actualiza el asalto actual preservando las marcas de tiempo de los golpes."""
    items = await cliente.obtener_asaltos_capital(limite=1)
    if not items:
        return None
    asalto = await _guardar_desde_raw_preservando_timestamps(sesion, items[0])
    if asalto is not None:
        inicio_str = str(items[0].get("startTime") or "")
        _CACHE_ETAPA1_CAPITAL[inicio_str] = (asalto.ataques_totales, asalto.estado)
    return asalto


async def _guardar_desde_raw_preservando_timestamps(
    sesion: AsyncSession, raw_item: dict
) -> AsaltoCapital | None:
    asalto_actual = AsaltoOut.desde_api(raw_item)
    if asalto_actual.inicio is None:
        return None

    ahora_utc = datetime.now(timezone.utc)

    resultado = await sesion.execute(
        select(AsaltoCapital)
        .where(AsaltoCapital.inicio == asalto_actual.inicio)
        .options(
            selectinload(AsaltoCapital.miembros),
            selectinload(AsaltoCapital.registros)
            .selectinload(AsaltoRegistro.distritos)
            .selectinload(AsaltoDistrito.ataques),
        )
    )
    asalto = resultado.scalar_one_or_none()

    memoria_timestamps: dict[tuple, tuple[datetime, int]] = {}
    max_orden_previo = 0

    if asalto is None:
        asalto = AsaltoCapital(
            inicio=asalto_actual.inicio,
            miembros=[],
            registros=[],
        )
        sesion.add(asalto)
    else:
        for reg_old in asalto.registros:
            for dist_old in reg_old.distritos:
                for atk_old in dist_old.ataques:
                    ts = atk_old.detectado_en or ahora_utc
                    ord_ap = atk_old.orden_aparicion or 0
                    if ord_ap > max_orden_previo:
                        max_orden_previo = ord_ap
                    clave = (
                        reg_old.sentido,
                        reg_old.clan_tag,
                        reg_old.clan_nombre,
                        dist_old.distrito_id_juego,
                        atk_old.atacante_tag,
                        atk_old.destruccion,
                    )
                    memoria_timestamps[clave] = (ts, ord_ap)

        asalto.miembros.clear()
        asalto.registros.clear()
        await sesion.flush()

    asalto.estado = asalto_actual.estado
    asalto.fin = asalto_actual.fin
    asalto.oro_capital_total = asalto_actual.oro_capital_total
    asalto.asaltos_completados = asalto_actual.asaltos_completados
    asalto.ataques_totales = asalto_actual.ataques_totales
    asalto.distritos_rivales_destruidos = asalto_actual.distritos_rivales_destruidos
    asalto.recompensa_ofensiva = asalto_actual.recompensa_ofensiva
    asalto.recompensa_defensiva = asalto_actual.recompensa_defensiva

    for miembro in asalto_actual.miembros:
        asalto.miembros.append(
            AsaltoMiembro(
                tag=miembro.tag,
                nombre=miembro.nombre,
                ataques_usados=miembro.ataques_usados,
                limite_ataques=miembro.limite_ataques,
                ataques_bono=miembro.ataques_bono,
                oro_capital_saqueado=miembro.oro_capital_saqueado,
            )
        )

    siguiente_orden = max_orden_previo + 1

    # Supercell entrega ataques_realizados en orden cronológico natural (Incursión #1 -> Incursión actual).
    # Se guarda directamente sin invertir para que registro.id respete la secuencia histórica real.
    for sentido, lista in (
        ("ofensivo", asalto_actual.ataques_realizados),
        ("defensivo", asalto_actual.ataques_recibidos),
    ):
        for registro_datos in lista:
            fila_reg, siguiente_orden = _construir_registro(
                registro_datos,
                sentido,
                memoria_timestamps=memoria_timestamps,
                ahora_utc=ahora_utc,
                siguiente_orden=siguiente_orden,
            )
            asalto.registros.append(fila_reg)

    await sesion.commit()
    return asalto


def _construir_registro(
    registro: RegistroCapitalOut,
    sentido: str,
    *,
    memoria_timestamps: dict | None = None,
    ahora_utc: datetime | None = None,
    siguiente_orden: int = 1,
) -> tuple[AsaltoRegistro, int]:
    """Arma un AsaltoRegistro preservando la marca de tiempo y orden_aparicion de cada golpe."""
    if ahora_utc is None:
        ahora_utc = datetime.now(timezone.utc)
    modo_compat = memoria_timestamps is None
    if memoria_timestamps is None:
        memoria_timestamps = {}

    fila = AsaltoRegistro(
        sentido=sentido,
        clan_tag=registro.clan_tag,
        clan_nombre=registro.clan_nombre,
        clan_nivel=registro.clan_nivel,
        ataques_usados=registro.ataques_usados,
        distritos_totales=registro.distritos_totales,
        distritos_destruidos=registro.distritos_destruidos,
        distritos=[],
    )
    for distrito in registro.distritos:
        fila_distrito = AsaltoDistrito(
            distrito_id_juego=distrito.id,
            nombre=distrito.nombre,
            nivel=distrito.nivel,
            destruccion=distrito.destruccion,
            estrellas=distrito.estrellas,
            ataques_usados=distrito.ataques_usados,
            saqueado=distrito.saqueado,
            ataques=[],
        )
        ataques_ordenados_asc = sorted(distrito.ataques, key=lambda a: a.destruccion)
        mapa_nuevos: dict[tuple[str, int], tuple[datetime, int]] = {}
        for atk_asc in ataques_ordenados_asc:
            clave = (
                sentido,
                registro.clan_tag,
                registro.clan_nombre,
                distrito.id,
                atk_asc.atacante_tag,
                atk_asc.destruccion,
            )
            if clave in memoria_timestamps:
                mapa_nuevos[(atk_asc.atacante_tag, atk_asc.destruccion)] = memoria_timestamps[clave]
            else:
                mapa_nuevos[(atk_asc.atacante_tag, atk_asc.destruccion)] = (ahora_utc, siguiente_orden)
                siguiente_orden += 1

        for ataque in distrito.ataques:
            ts_atk, ord_atk = mapa_nuevos.get(
                (ataque.atacante_tag, ataque.destruccion), (ahora_utc, siguiente_orden)
            )
            fila_distrito.ataques.append(
                AsaltoAtaque(
                    atacante_tag=ataque.atacante_tag,
                    atacante_nombre=ataque.atacante_nombre,
                    estrellas=ataque.estrellas,
                    destruccion=ataque.destruccion,
                    detectado_en=ts_atk,
                    orden_aparicion=ord_atk,
                )
            )
        fila.distritos.append(fila_distrito)

    if modo_compat:
        return fila  # type: ignore[return-value]
    return fila, siguiente_orden


# =============================================================================
# MOTOR FORENSE DE AUDITORÍA DE CAPITAL (CALIBRADO + NOMENCLATURA CLARA)
# =============================================================================
def _ordenar_incursiones_cronologicamente(registros_ofensivos: list[AsaltoRegistro]) -> list[AsaltoRegistro]:
    """
    Ordena las incursiones desde la #1 (más antigua) hasta la actual (en curso):
    1. La incursión aún abierta (`distritos_destruidos < distritos_totales`) va siempre al final.
    2. Si tienen `orden_aparicion > 0`, usa el orden en que se detectaron en vivo.
    3. Para las incursiones previas sin `orden_aparicion`, mantiene el orden natural (`reg.id` ascendente).
    """
    def clave_incursion(reg: AsaltoRegistro) -> tuple:
        en_curso = 1 if reg.distritos_destruidos < reg.distritos_totales else 0
        ordenes = [
            atk.orden_aparicion or 0
            for d in reg.distritos
            for atk in d.ataques
            if (atk.orden_aparicion or 0) > 0
        ]
        min_orden_vivo = min(ordenes) if ordenes else 0
        tiene_orden_vivo = 1 if min_orden_vivo > 0 else 0
        return (en_curso, tiene_orden_vivo, min_orden_vivo, reg.id or 0)

    return sorted(registros_ofensivos, key=clave_incursion)


def construir_auditoria_capital(asalto: AsaltoCapital) -> dict:
    """
    Reconstruye la cronología real de los ataques de cada jugador y evalúa las reglas
    de remate usando nombres claros para el clan y formato compacto para móvil.
    """
    ahora_utc = datetime.now(timezone.utc)
    registros_ofensivos = _ordenar_incursiones_cronologicamente(
        [r for r in asalto.registros if r.sentido == "ofensivo"]
    )
    mapa_miembros = {m.tag: m for m in asalto.miembros}

    golpes_todos: list[dict] = []
    for idx_incursion, reg in enumerate(registros_ofensivos, start=1):
        distritos_ordenados = sorted(
            reg.distritos,
            key=lambda d: (
                min((a.orden_aparicion for a in d.ataques if (a.orden_aparicion or 0) > 0), default=0),
                d.distrito_id_juego,
            ),
        )
        for dist in distritos_ordenados:
            atks_dist_cron = sorted(dist.ataques, key=lambda x: x.destruccion)
            acum_pct = 0
            for idx_hit_dist, atk in enumerate(atks_dist_cron, start=1):
                antes = acum_pct
                despues = atk.destruccion
                aporte = max(0, despues - antes)
                oro_est = (
                    round((aporte / dist.destruccion) * dist.saqueado)
                    if dist.destruccion > 0
                    else 0
                )
                ts_utc = atk.detectado_en or asalto.ultima_actualizacion_en or ahora_utc
                if antes == 0 and despues == 100:
                    hito_base = "Pleno de 1 tiro (100%)"
                elif despues == 100:
                    hito_base = "Remate final (100%)"
                elif 70 <= despues < 100:
                    hito_base = f"Sin rematar ({despues}%)"
                elif antes == 0:
                    hito_base = "Apertura"
                else:
                    hito_base = "Avance"

                golpes_todos.append({
                    "incursion_num": idx_incursion,
                    "registro_id": reg.id,
                    "clan_rival": reg.clan_nombre,
                    "distrito_id_unico": f"{reg.id}_{dist.distrito_id_juego}",
                    "distrito_id_juego": dist.distrito_id_juego,
                    "distrito_nombre": dist.nombre,
                    "distrito_etiqueta": f"{dist.nombre} ({reg.clan_nombre})",
                    "distrito_destruccion_final": dist.destruccion,
                    "atacante_tag": atk.atacante_tag,
                    "atacante_nombre": atk.atacante_nombre,
                    "antes_pct": antes,
                    "despues_pct": despues,
                    "aporte_pct": aporte,
                    "oro_estimado": oro_est,
                    "estrellas": atk.estrellas,
                    "hito_base": hito_base,
                    "detectado_en": ts_utc,
                    "hora_peru": (ts_utc.astimezone(timezone.utc)).strftime("%H:%M UTC"),
                    "orden_aparicion": atk.orden_aparicion or 0,
                    "idx_en_distrito": idx_hit_dist,
                })
                acum_pct = despues

    total_golpes = len(golpes_todos)
    for i, g in enumerate(golpes_todos):
        g["num_bitacora"] = total_golpes - i
        g["indice_global"] = i

    golpes_por_distrito: dict[str, list[dict]] = {}
    golpes_por_jugador_bruto: dict[str, list[dict]] = {}
    for g in golpes_todos:
        golpes_por_distrito.setdefault(g["distrito_id_unico"], []).append(g)
        golpes_por_jugador_bruto.setdefault(g["atacante_tag"], []).append(g)

    auditorias_jugadores: dict[str, dict] = {}
    infractores_confirmados: list[dict] = []

    for tag_jug, lista_bruta in golpes_por_jugador_bruto.items():
        info_m = mapa_miembros.get(tag_jug)
        nombre_jug = info_m.nombre if info_m else lista_bruta[-1]["atacante_nombre"]
        oro_oficial = info_m.oro_capital_saqueado if info_m else sum(x["oro_estimado"] for x in lista_bruta)
        bono_oficial = info_m.ataques_bono if info_m else (1 if any(x["despues_pct"] == 100 for x in lista_bruta) else 0)
        limite_base = info_m.limite_ataques if info_m else 5
        max_permitidos_final = limite_base + bono_oficial

        max_pct_por_distrito: dict[str, int] = {}
        min_orden_por_distrito: dict[str, int] = {}
        for g in lista_bruta:
            d_uid = g["distrito_id_unico"]
            max_pct_por_distrito[d_uid] = max(max_pct_por_distrito.get(d_uid, 0), g["despues_pct"])
            if g["orden_aparicion"] > 0:
                prev_o = min_orden_por_distrito.get(d_uid, 999999)
                min_orden_por_distrito[d_uid] = min(prev_o, g["orden_aparicion"])

        def clave_orden_jugador(g: dict) -> tuple:
            d_uid = g["distrito_id_unico"]
            ord_vivo = min_orden_por_distrito.get(d_uid, 0)
            tiene_vivo = 1 if ord_vivo > 0 else 0
            fue_incompleto_sin_ts = (
                1 if (ord_vivo == 0 and max_pct_por_distrito.get(d_uid, 0) < 100) else 0
            )
            return (
                g["incursion_num"],
                tiene_vivo,
                ord_vivo,
                fue_incompleto_sin_ts,
                g["distrito_id_juego"],
                g["despues_pct"],
            )

        mis_golpes = sorted(lista_bruta, key=clave_orden_jugador)

        bono_desbloqueado = False
        for idx_tiro, g in enumerate(mis_golpes, start=1):
            if g["despues_pct"] == 100:
                bono_desbloqueado = True
            techo_actual = limite_base + (1 if (bono_desbloqueado or bono_oficial > 0) else 0)
            restantes = max(0, techo_actual - idx_tiro)
            g["tiro_personal_num"] = idx_tiro
            g["tiro_personal_txt"] = f"{idx_tiro}/{max_permitidos_final}"
            g["tiros_restantes_despues"] = restantes

        distritos_tocados_orden: list[str] = []
        for g in mis_golpes:
            if g["distrito_id_unico"] not in distritos_tocados_orden:
                distritos_tocados_orden.append(g["distrito_id_unico"])

        distritos_sin_rematar: list[dict] = []
        distritos_abiertos_relevantes: list[dict] = []
        infracciones_jugador: list[dict] = []

        for d_uid in distritos_tocados_orden:
            todos_en_d = golpes_por_distrito[d_uid]
            mis_en_d = [x for x in mis_golpes if x["distrito_id_unico"] == d_uid]
            ultimo_mio = mis_en_d[-1]

            if ultimo_mio["despues_pct"] < 100:
                posteriores_ajenos = [
                    x for x in todos_en_d
                    if x["despues_pct"] > ultimo_mio["despues_pct"] and x["atacante_tag"] != tag_jug
                ]
                limpieza_ajena_txt = None
                limpieza_corta_movil = None
                cerrado_de_un_solo_tiro_ajeno = False
                if posteriores_ajenos:
                    rem = posteriores_ajenos[0]
                    if rem["despues_pct"] == 100:
                        cerrado_de_un_solo_tiro_ajeno = True
                    limpieza_ajena_txt = (
                        f"{rem['atacante_nombre']} ({rem['antes_pct']}%->{rem['despues_pct']}%, {rem['oro_estimado']} oro)"
                    )
                    limpieza_corta_movil = (
                        f"Lo cerró {rem['atacante_nombre']} (+{rem['aporte_pct']}%, {rem['oro_estimado']} oro)"
                    )
                    ultimo_mio["limpieza_ajena_detalle"] = limpieza_corta_movil

                mis_posteriores_otro_dist = [
                    x for x in mis_golpes
                    if x["tiro_personal_num"] > ultimo_mio["tiro_personal_num"]
                    and x["distrito_id_unico"] != d_uid
                ]

                es_franja_remate = (
                    ultimo_mio["despues_pct"] >= 70
                    or (len(mis_en_d) >= 2 and ultimo_mio["despues_pct"] >= 65 and cerrado_de_un_solo_tiro_ajeno)
                )

                reg_abierto = {
                    "distrito": ultimo_mio["distrito_etiqueta"],
                    "dejado_en_pct": ultimo_mio["despues_pct"],
                    "en_tiro": ultimo_mio["tiro_personal_txt"],
                    "num_bitacora": ultimo_mio["num_bitacora"],
                    "hora": ultimo_mio["hora_peru"],
                    "restantes_en_ese_momento": ultimo_mio["tiros_restantes_despues"],
                    "golpes_propios_en_distrito": len(mis_en_d),
                    "es_franja_remate": es_franja_remate,
                    "limpiado_por_companero": limpieza_ajena_txt,
                    "fuga_a_distrito": (
                        mis_posteriores_otro_dist[0]["distrito_etiqueta"]
                        if mis_posteriores_otro_dist
                        else None
                    ),
                }

                # Se contabiliza como distrito abierto relevante si quedó >= 50% o le dio >= 2 golpes
                if ultimo_mio["despues_pct"] >= 50 or len(mis_en_d) >= 2:
                    distritos_abiertos_relevantes.append(reg_abierto)
                if es_franja_remate:
                    distritos_sin_rematar.append(reg_abierto)

                # REGLA 1: Abandono de distrito en franja de remate (>=70%) teniendo ataques disponibles
                if (
                    es_franja_remate
                    and ultimo_mio["tiros_restantes_despues"] > 0
                    and mis_posteriores_otro_dist
                ):
                    sig = mis_posteriores_otro_dist[0]
                    infracciones_jugador.append({
                        "regla_vulnerada": "Abandono de distrito con ataques disponibles",
                        "gravedad": "Falta Grave",
                        "explicacion": (
                            f"En su Tiro {ultimo_mio['tiro_personal_txt']} dejó '{ultimo_mio['distrito_etiqueta']}' "
                            f"al {ultimo_mio['despues_pct']}% quedándole {ultimo_mio['tiros_restantes_despues']} "
                            f"ataque(s) libre(s), y saltó a '{sig['distrito_etiqueta']}'"
                            + (f" (lo tuvo que cerrar {limpieza_ajena_txt})." if limpieza_ajena_txt else ".")
                        ),
                    })
                    ultimo_mio["alerta_forense"] = (
                        f"🚨 Abandonado al {ultimo_mio['despues_pct']}% (quedaban {ultimo_mio['tiros_restantes_despues']} tiros)"
                    )

                # REGLA 3: Dejar distrito en >=80% con ataques disponibles sin usarlos
                elif (
                    ultimo_mio["tiros_restantes_despues"] > 0
                    and ultimo_mio["despues_pct"] >= 80
                    and len(mis_golpes) < max_permitidos_final
                ):
                    minutos_transcurridos = (ahora_utc - ultimo_mio["detectado_en"]).total_seconds() / 60.0
                    if limpieza_ajena_txt or minutos_transcurridos >= 15.0:
                        infracciones_jugador.append({
                            "regla_vulnerada": "Distrito dejado a medias con ataques sin usar",
                            "gravedad": "Falta Grave",
                            "explicacion": (
                                f"En su Tiro {ultimo_mio['tiro_personal_txt']} dejó '{ultimo_mio['distrito_etiqueta']}' "
                                f"al {ultimo_mio['despues_pct']}% quedándole {ultimo_mio['tiros_restantes_despues']} "
                                f"ataque(s) sin gastar."
                            ),
                        })
                        ultimo_mio["alerta_forense"] = (
                            f"🚨 Dejado al {ultimo_mio['despues_pct']}% con tiros pendientes"
                        )

        # REGLA 2: Doble distrito sin rematar (al menos 1 en franja de remate >=70% y otro >=50% con tiros libres previos)
        tiene_doble_infraccion = len(distritos_sin_rematar) >= 2 or (
            len(distritos_sin_rematar) == 1
            and len(distritos_abiertos_relevantes) >= 2
            and any(d["restantes_en_ese_momento"] > 0 for d in distritos_abiertos_relevantes)
        )
        if tiene_doble_infraccion:
            lista_mostrar = (
                distritos_sin_rematar
                if len(distritos_sin_rematar) >= 2
                else distritos_abiertos_relevantes
            )
            resumen_inc = " y ".join(
                f"'{d['distrito']}' al {d['dejado_en_pct']}% (Tiro {d['en_tiro']})"
                for d in lista_mostrar
            )
            infracciones_jugador.append({
                "regla_vulnerada": "Doble distrito sin rematar (máximo permitido: 1 al quedarte sin tiros)",
                "gravedad": "Falta Grave",
                "explicacion": (
                    f"Dejó {len(lista_mostrar)} distritos inconclusos en la misma jornada: {resumen_inc}. "
                    "Solo se tolera dejar 1 distrito abierto cuando te quedas en 0 ataques restantes."
                ),
            })
            for d_ab in lista_mostrar:
                for g in mis_golpes:
                    if g["num_bitacora"] == d_ab["num_bitacora"]:
                        g.setdefault(
                            "alerta_forense",
                            f"🚨 Distrito sin rematar ({g['despues_pct']}%)",
                        )

        # Construir cronología del jugador en formato Tarjeta Móvil (2 líneas de <= 38 caracteres)
        cronologia_movil: list[str] = []
        for g in mis_golpes:
            estado_corto = g.get("alerta_forense") or g["hito_base"]
            linea_1 = f"• *Tiro {g['tiro_personal_txt']}* • {g['distrito_etiqueta']}"
            linea_2 = (
                f"  └ `{g['antes_pct']}% ➔ {g['despues_pct']}%` (`{g['oro_estimado']}` oro) "
                f"• Quedaban `{g['tiros_restantes_despues']}` • {estado_corto}"
            )
            bloque = f"{linea_1}\n{linea_2}"
            if g.get("limpieza_ajena_detalle"):
                bloque += f"\n  └ 🛠️ _{g['limpieza_ajena_detalle']}_"
            cronologia_movil.append(bloque)

        if infracciones_jugador:
            veredicto = f"🚨 INFRACCIÓN CONFIRMADA ({len(infracciones_jugador)} falta(s) al reglamento)"
        elif len(distritos_sin_rematar) == 1 and distritos_sin_rematar[0]["restantes_en_ese_momento"] == 0:
            d0 = distritos_sin_rematar[0]
            veredicto = (
                f"✅ CUMPLIÓ REGLAMENTO (Dejó 1 único distrito '{d0['distrito']}' al {d0['dejado_en_pct']}% "
                f"en su último tiro {d0['en_tiro']} porque ya no le quedaban ataques)"
            )
        else:
            veredicto = "✅ LIMPIO (Cumplió correctamente con el reglamento de remates)"

        ficha_auditoria = {
            "tag": tag_jug,
            "nick": nombre_jug,
            "tiros_usados": len(mis_golpes),
            "tiros_permitidos": max_permitidos_final,
            "tiros_txt": f"{len(mis_golpes)}/{max_permitidos_final}",
            "oro_total": oro_oficial,
            "promedio_oro": round(oro_oficial / len(mis_golpes)) if mis_golpes else 0,
            "distritos_sin_rematar_cant": len(distritos_sin_rematar),
            "distritos_sin_rematar_detalle": distritos_sin_rematar,
            "tiene_infraccion": len(infracciones_jugador) > 0,
            "veredicto_sistema": veredicto,
            "cargos_infraccion": infracciones_jugador,
            "cronologia_detallada": cronologia_movil,
        }
        auditorias_jugadores[tag_jug] = ficha_auditoria
        if infracciones_jugador:
            infractores_confirmados.append(ficha_auditoria)

    bitacora_enriquecida = []
    for g in reversed(golpes_todos):
        nota = g.get("alerta_forense") or g["hito_base"]
        bitacora_enriquecida.append(
            f"#{g['num_bitacora']}|{g['atacante_nombre']}|"
            f"Tiro {g.get('tiro_personal_txt', '?')}(Rest:{g.get('tiros_restantes_despues', '?')})|"
            f"{g['distrito_etiqueta']}|{g['antes_pct']}%->{g['despues_pct']}%|"
            f"{g['oro_estimado']} oro|{nota}"
        )

    return {
        "asalto_id": asalto.id,
        "estado": asalto.estado,
        "oro_total": asalto.oro_capital_total,
        "ataques_totales": asalto.ataques_totales,
        "incursiones": asalto.asaltos_completados,
        "distritos_destruidos": asalto.distritos_rivales_destruidos,
        "infractores_confirmados": infractores_confirmados,
        "auditorias_por_tag": auditorias_jugadores,
        "bitacora_enriquecida": bitacora_enriquecida,
    }


async def listar_asaltos(sesion: AsyncSession, limite: int) -> list[AsaltoCapital]:
    """Devuelve los fines de semana de asaltos guardados, del más reciente al más antiguo."""
    resultado = await sesion.execute(
        select(AsaltoCapital).order_by(AsaltoCapital.inicio.desc()).limit(limite)
    )
    return list(resultado.scalars().all())


async def obtener_asalto(sesion: AsyncSession, asalto_id: int) -> AsaltoCapital | None:
    """Devuelve un fin de semana de asaltos guardado por id, con todo su detalle cargado."""
    resultado = await sesion.execute(
        select(AsaltoCapital)
        .where(AsaltoCapital.id == asalto_id)
        .options(
            selectinload(AsaltoCapital.miembros),
            selectinload(AsaltoCapital.registros)
            .selectinload(AsaltoRegistro.distritos)
            .selectinload(AsaltoDistrito.ataques),
        )
    )
    return resultado.scalar_one_or_none()