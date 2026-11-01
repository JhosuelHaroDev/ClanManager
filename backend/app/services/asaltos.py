"""Servicio de Asaltos a la Capital con Sondeo en 2 Etapas y Motor Forense (Gatillos A, B y C)."""

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

# Marca de tiempo del último golpe nuevo detectado (para evaluar el Timeout de 15 min del Gatillo C)
_ULTIMO_CAMBIO_DETECTADO_UTC: datetime | None = None


def hay_posible_timeout_pendiente(ahora_utc: datetime) -> bool:
    """Indica si transcurrieron >= 15 min desde el último golpe para revisar el Gatillo C."""
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
    ETAPA 1 (Centinela en RAM): Consulta el número `totalAttacks` en Supercell.
    Si es igual al del sondeo anterior y no se fuerza, ignora la Etapa 2 (0 escrituras en BD).
    ETAPA 2 (Sondeo Profundo): Si `totalAttacks` aumentó, sincroniza en PostgreSQL preservando
    las marcas de tiempo `detectado_en` de los golpes anteriores.
    Devuelve: (AsaltoCapital, hubo_nuevos_ataques)
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
        # Etapa 1: Sin cambios en el contador de ataques -> 0 consultas a PostgreSQL
        return None, False

    # Etapa 2: El número de ataques aumentó (o cambió el estado) -> Sondeo Profundo
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

    # Mapa para preservar (detectado_en, orden_aparicion) de golpes ya registrados
    # Clave: (sentido, clan_tag, num_incursion_sentido, distrito_id_juego, atacante_tag, destruccion)
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
        contadores_sentido: dict[str, int] = {"ofensivo": 0, "defensivo": 0}
        for reg_old in asalto.registros:
            idx_inc = contadores_sentido.get(reg_old.sentido, 0)
            contadores_sentido[reg_old.sentido] = idx_inc + 1
            for dist_old in reg_old.distritos:
                for atk_old in dist_old.ataques:
                    ts = atk_old.detectado_en or ahora_utc
                    ord_ap = atk_old.orden_aparicion or 0
                    if ord_ap > max_orden_previo:
                        max_orden_previo = ord_ap
                    clave = (
                        reg_old.sentido,
                        reg_old.clan_tag,
                        idx_inc,
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

    for sentido, lista in (
        ("ofensivo", asalto_actual.ataques_realizados),
        ("defensivo", asalto_actual.ataques_recibidos),
    ):
        for idx_inc, registro_datos in enumerate(lista):
            fila_reg, siguiente_orden = _construir_registro(
                registro_datos,
                sentido,
                idx_inc=idx_inc,
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
    idx_inc: int = 0,
    memoria_timestamps: dict | None = None,
    ahora_utc: datetime | None = None,
    siguiente_orden: int = 1,
) -> tuple[AsaltoRegistro, int]:
    """Arma un AsaltoRegistro preservando la marca de tiempo de cada golpe."""
    if ahora_utc is None:
        ahora_utc = datetime.now(timezone.utc)
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
        # Ordenar de menor a mayor destrucción para asignar orden_aparicion cronológico a golpes nuevos
        ataques_ordenados_asc = sorted(distrito.ataques, key=lambda a: a.destruccion)
        mapa_nuevos: dict[tuple[str, int], tuple[datetime, int]] = {}
        for atk_asc in ataques_ordenados_asc:
            clave = (
                sentido,
                registro.clan_tag,
                idx_inc,
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

    if memoria_timestamps == {}:
        # Compatibilidad directa si alguien llama _construir_registro con 2 argumentos
        return fila  # type: ignore[return-value]
    return fila, siguiente_orden


# =============================================================================
# MOTOR FORENSE DE AUDITORÍA DE CAPITAL (GATILLOS A, B Y C)
# =============================================================================
def construir_auditoria_capital(asalto: AsaltoCapital) -> dict:
    """
    Reconstruye la cronología exacta del fin de semana de asaltos:
    - Numera los tiros de cada jugador (#1/6 al #6/6) y cuántos tiros le restaban.
    - Detecta quién tuvo que limpiar distritos dejados a medias por otro compañero.
    - Evalúa los 3 Gatillos de Infracción:
      * GATILLO A: Fuga a otro distrito dejando el anterior abierto (>=75% o tras 2 golpes >=60%) teniendo tiros.
      * GATILLO B: Acumulación de 2 o más distritos dejados sin rematar (<100%) en el mismo fin de semana.
      * GATILLO C: Dejar distrito en 80%-99% teniendo tiros disponibles y que otro compañero tenga que limpiarlo
                   o que pasen >= 15 minutos sin rematarlo.
    """
    ahora_utc = datetime.now(timezone.utc)
    registros_ofensivos = [r for r in asalto.registros if r.sentido == "ofensivo"]
    mapa_miembros = {m.tag: m for m in asalto.miembros}

    # 1. Reconstruir todos los golpes en orden cronológico (del Golpe más antiguo al más reciente)
    golpes_cronologicos: list[dict] = []
    # En Supercell attackLog[0] es la incursión más reciente y attackLog[-1] la primera incursión
    for idx_incursion, reg in enumerate(reversed(registros_ofensivos), start=1):
        for dist in reversed(reg.distritos):
            # Dentro de cada distrito, el porcentaje de destrucción siempre sube de 0% a 100%
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
                    hito_base = "ONE_SHOT(100%)"
                elif despues == 100:
                    hito_base = "REMATE_BONUS(100%)"
                elif 90 <= despues < 100:
                    hito_base = f"DEJADO_AL_{despues}%"
                elif 80 <= despues < 90:
                    hito_base = f"ABIERTO_{despues}%"
                elif antes == 0:
                    hito_base = "APERTURA"
                else:
                    hito_base = "PROGRESO"

                golpes_cronologicos.append({
                    "incursion_num": idx_incursion,
                    "registro_id": reg.id,
                    "clan_rival": reg.clan_nombre,
                    "distrito_id_unico": f"{reg.id}_{dist.distrito_id_juego}",
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

    # Numerar correlativo inverso de Bitácora (#1 = más reciente, #N = más antiguo, igual que en el PDF/Sheet)
    total_golpes = len(golpes_cronologicos)
    for i, g in enumerate(golpes_cronologicos):
        g["num_bitacora"] = total_golpes - i
        g["indice_cron"] = i

    # 2. Agrupar golpes por distrito único y por jugador para numerar Tiro 1/6 .. 6/6
    golpes_por_distrito: dict[str, list[dict]] = {}
    golpes_por_jugador: dict[str, list[dict]] = {}

    for g in golpes_cronologicos:
        golpes_por_distrito.setdefault(g["distrito_id_unico"], []).append(g)
        golpes_por_jugador.setdefault(g["atacante_tag"], []).append(g)

    # 3. Calcular para cada jugador su secuencia de tiros (1/6 a 6/6) y evaluar Gatillos A, B y C
    auditorias_jugadores: dict[str, dict] = {}
    infractores_confirmados: list[dict] = []

    for tag_jug, mis_golpes in golpes_por_jugador.items():
        info_m = mapa_miembros.get(tag_jug)
        nombre_jug = info_m.nombre if info_m else mis_golpes[-1]["atacante_nombre"]
        oro_oficial = info_m.oro_capital_saqueado if info_m else sum(x["oro_estimado"] for x in mis_golpes)
        bono_oficial = info_m.ataques_bono if info_m else (1 if any(x["despues_pct"] == 100 for x in mis_golpes) else 0)
        limite_base = info_m.limite_ataques if info_m else 5
        max_permitidos_final = limite_base + bono_oficial

        bono_desbloqueado = False
        for idx_tiro, g in enumerate(mis_golpes, start=1):
            if g["despues_pct"] == 100:
                bono_desbloqueado = True
            techo_actual = limite_base + (1 if (bono_desbloqueado or bono_oficial > 0) else 0)
            restantes = max(0, techo_actual - idx_tiro)
            g["tiro_personal_num"] = idx_tiro
            g["tiro_personal_txt"] = f"{idx_tiro}/{max_permitidos_final}"
            g["tiros_restantes_despues"] = restantes

        # Agrupar los distritos que tocó este jugador en orden de aparición
        distritos_tocados_orden: list[str] = []
        for g in mis_golpes:
            if g["distrito_id_unico"] not in distritos_tocados_orden:
                distritos_tocados_orden.append(g["distrito_id_unico"])

        distritos_inconclusos: list[dict] = []
        infracciones_jugador: list[dict] = []

        for d_uid in distritos_tocados_orden:
            todos_en_d = golpes_por_distrito[d_uid]
            mis_en_d = [x for x in todos_en_d if x["atacante_tag"] == tag_jug]
            ultimo_mio = mis_en_d[-1]

            # Verificar si el jugador dejó este distrito sin llegar al 100% en su último golpe ahí
            if ultimo_mio["despues_pct"] < 100:
                # ¿Otro compañero tuvo que rematar o atacar este distrito después de él?
                posteriores_ajenos = [
                    x for x in todos_en_d
                    if x["indice_cron"] > ultimo_mio["indice_cron"] and x["atacante_tag"] != tag_jug
                ]
                limpieza_ajena_txt = None
                if posteriores_ajenos:
                    rem = posteriores_ajenos[0]
                    limpieza_ajena_txt = (
                        f"{rem['atacante_nombre']} (Golpe #{rem['num_bitacora']}, "
                        f"{rem['antes_pct']}%->{rem['despues_pct']}%, {rem['oro_estimado']} oro)"
                    )
                    ultimo_mio["limpieza_ajena_detalle"] = limpieza_ajena_txt

                # ¿El jugador hizo otro ataque posterior en un distrito DISTINTO?
                mis_posteriores_otro_dist = [
                    x for x in mis_golpes
                    if x["indice_cron"] > ultimo_mio["indice_cron"] and x["distrito_id_unico"] != d_uid
                ]

                registro_inc = {
                    "distrito": ultimo_mio["distrito_etiqueta"],
                    "dejado_en_pct": ultimo_mio["despues_pct"],
                    "en_tiro": ultimo_mio["tiro_personal_txt"],
                    "num_bitacora": ultimo_mio["num_bitacora"],
                    "hora": ultimo_mio["hora_peru"],
                    "restantes_en_ese_momento": ultimo_mio["tiros_restantes_despues"],
                    "golpes_propios_en_distrito": len(mis_en_d),
                    "limpiado_por_companero": limpieza_ajena_txt,
                    "fuga_a_distrito": (
                        mis_posteriores_otro_dist[0]["distrito_etiqueta"]
                        if mis_posteriores_otro_dist
                        else None
                    ),
                }
                distritos_inconclusos.append(registro_inc)

                es_rango_critico = (
                    ultimo_mio["despues_pct"] >= 75
                    or (len(mis_en_d) >= 2 and ultimo_mio["despues_pct"] >= 60)
                )

                # GATILLO A: Tenía tiros disponibles, dejó el distrito en rango crítico y se fugó a otro distrito
                if ultimo_mio["tiros_restantes_despues"] > 0 and mis_posteriores_otro_dist and es_rango_critico:
                    sig = mis_posteriores_otro_dist[0]
                    infracciones_jugador.append({
                        "codigo": "GATILLO_A_FUGA_DISTRITO",
                        "gravedad": "GRAVE",
                        "explicacion": (
                            f"En su Tiro {ultimo_mio['tiro_personal_txt']} (Golpe #{ultimo_mio['num_bitacora']}, {ultimo_mio['hora_peru']}) "
                            f"dejó '{ultimo_mio['distrito_etiqueta']}' al {ultimo_mio['despues_pct']}% quedándole "
                            f"{ultimo_mio['tiros_restantes_despues']} ataque(s) disponible(s), y en su siguiente tiro se fue a atacar "
                            f"'{sig['distrito_etiqueta']}'"
                            + (f", obligando a {limpieza_ajena_txt} a limpiarlo." if limpieza_ajena_txt else ".")
                        ),
                    })
                    ultimo_mio["alerta_forense"] = (
                        f"🚨 INFRACCIÓN (GATILLO A): Abandonado al {ultimo_mio['despues_pct']}% "
                        f"quedándole {ultimo_mio['tiros_restantes_despues']} tiro(s)"
                    )

                # GATILLO C: Tenía tiros disponibles, dejó el distrito >=80% y otro compañero tuvo que limpiarlo o pasaron >=15 min
                elif ultimo_mio["tiros_restantes_despues"] > 0 and ultimo_mio["despues_pct"] >= 80:
                    minutos_transcurridos = (ahora_utc - ultimo_mio["detectado_en"]).total_seconds() / 60.0
                    if limpieza_ajena_txt:
                        infracciones_jugador.append({
                            "codigo": "GATILLO_C_LIMPIEZA_FORZADA",
                            "gravedad": "GRAVE",
                            "explicacion": (
                                f"En su Tiro {ultimo_mio['tiro_personal_txt']} (Golpe #{ultimo_mio['num_bitacora']}) "
                                f"dejó '{ultimo_mio['distrito_etiqueta']}' al {ultimo_mio['despues_pct']}% teniendo aún "
                                f"{ultimo_mio['tiros_restantes_despues']} ataque(s) disponible(s), y {limpieza_ajena_txt} tuvo que rematarlo."
                            ),
                        })
                        ultimo_mio["alerta_forense"] = (
                            f"🚨 INFRACCIÓN (GATILLO C): Dejado al {ultimo_mio['despues_pct']}% con tiros disponibles"
                        )
                    elif minutos_transcurridos >= 15.0 and len(mis_golpes) < max_permitidos_final:
                        infracciones_jugador.append({
                            "codigo": "GATILLO_C_TIMEOUT_15M",
                            "gravedad": "GRAVE",
                            "explicacion": (
                                f"Hace {int(minutos_transcurridos)} min dejó '{ultimo_mio['distrito_etiqueta']}' al "
                                f"{ultimo_mio['despues_pct']}% en su Tiro {ultimo_mio['tiro_personal_txt']} "
                                f"(Golpe #{ultimo_mio['num_bitacora']}) y se desconectó teniendo ataques disponibles."
                            ),
                        })
                        ultimo_mio["alerta_forense"] = (
                            f"🚨 INFRACCIÓN (GATILLO C): Abandonado al {ultimo_mio['despues_pct']}% (>15 min sin rematar)"
                        )

        # GATILLO B: Acumulación de 2 o más distritos sin rematar en el mismo fin de semana
        if len(distritos_inconclusos) >= 2:
            resumen_inc = ", ".join(
                f"'{d['distrito']}' al {d['dejado_en_pct']}% (Tiro {d['en_tiro']}, Golpe #{d['num_bitacora']})"
                for d in distritos_inconclusos
            )
            infracciones_jugador.append({
                "codigo": "GATILLO_B_DOBLE_INCONCLUSO",
                "gravedad": "GRAVE",
                "explicacion": (
                    f"Dejó {len(distritos_inconclusos)} distritos sin rematar en la misma jornada: {resumen_inc}. "
                    "El máximo aceptable es 1 solo cuando te quedas en 0 ataques restantes."
                ),
            })
            # Marcar el último distrito inconcluso también en la cronología
            for g in reversed(mis_golpes):
                if g["despues_pct"] < 100:
                    g.setdefault(
                        "alerta_forense",
                        f"🚨 INFRACCIÓN (GATILLO B): {len(distritos_inconclusos)}.º distrito dejado sin rematar ({g['despues_pct']}%)",
                    )
                    break

        # Construir cronología enriquecida del jugador (incluyendo los golpes de compañeros en sus mismos distritos)
        distritos_set = set(distritos_tocados_orden)
        cronologia_con_contexto: list[str] = []
        for g in golpes_cronologicos:
            if g["distrito_id_unico"] not in distritos_set:
                continue
            if g["atacante_tag"] == tag_jug:
                nota_alerta = f" | {g['alerta_forense']}" if g.get("alerta_forense") else f" | {g['hito_base']}"
                cronologia_con_contexto.append(
                    f"Tiro {g['tiro_personal_txt']} (Restaban:{g['tiros_restantes_despues']}) | "
                    f"Golpe #{g['num_bitacora']} ({g['hora_peru']}) | {g['atacante_nombre']} | "
                    f"{g['distrito_etiqueta']} | {g['antes_pct']}%->{g['despues_pct']}% (+{g['aporte_pct']}%) | "
                    f"{g['oro_estimado']} oro{nota_alerta}"
                )
            else:
                cronologia_con_contexto.append(
                    f"  ↳ [GOLPE DE COMPAÑERO EN ESE DISTRITO] | Golpe #{g['num_bitacora']} ({g['hora_peru']}) | "
                    f"{g['atacante_nombre']} | {g['distrito_etiqueta']} | "
                    f"{g['antes_pct']}%->{g['despues_pct']}% (+{g['aporte_pct']}%) | {g['oro_estimado']} oro | {g['hito_base']}"
                )

        if infracciones_jugador:
            veredicto = f"🚨 INFRACCIÓN CONFIRMADA ({len(infracciones_jugador)} cargo(s) detectado(s))"
        elif len(distritos_inconclusos) == 1 and distritos_inconclusos[0]["restantes_en_ese_momento"] == 0:
            d0 = distritos_inconclusos[0]
            veredicto = (
                f"✅ CUMPLIÓ REGLAMENTO (Dejó 1 único distrito '{d0['distrito']}' al {d0['dejado_en_pct']}% "
                f"en su último tiro {d0['en_tiro']} porque ya tenía 0 ataques disponibles)"
            )
        else:
            veredicto = "✅ LIMPIO (Todos los distritos que atacó fueron rematados correctamente)"

        ficha_auditoria = {
            "tag": tag_jug,
            "nick": nombre_jug,
            "tiros_usados": len(mis_golpes),
            "tiros_permitidos": max_permitidos_final,
            "tiros_txt": f"{len(mis_golpes)}/{max_permitidos_final}",
            "oro_total": oro_oficial,
            "promedio_oro": round(oro_oficial / len(mis_golpes)) if mis_golpes else 0,
            "distritos_sin_rematar_cant": len(distritos_inconclusos),
            "distritos_sin_rematar_detalle": distritos_inconclusos,
            "tiene_infraccion": len(infracciones_jugador) > 0,
            "veredicto_sistema": veredicto,
            "cargos_infraccion": infracciones_jugador,
            "cronologia_detallada": cronologia_con_contexto,
        }
        auditorias_jugadores[tag_jug] = ficha_auditoria
        if infracciones_jugador:
            infractores_confirmados.append(ficha_auditoria)

    # Bitácora general enriquecida (más recientes arriba, igual que en la hoja)
    bitacora_enriquecida = []
    for g in reversed(golpes_cronologicos):
        nota = g.get("alerta_forense") or g["hito_base"]
        bitacora_enriquecida.append(
            f"#{g['num_bitacora']}|{g['hora_peru']}|{g['atacante_nombre']}|"
            f"Tiro:{g.get('tiro_personal_txt', '?')}(Rest:{g.get('tiros_restantes_despues', '?')})|"
            f"{g['distrito_etiqueta']}|{g['antes_pct']}%->{g['despues_pct']}%(+{g['aporte_pct']}%)|"
            f"{g['oro_estimado']}|{nota}"
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