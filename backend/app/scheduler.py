"""Programador de capturas automáticas y alertas proactivas de S.T.A.C.Y."""

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.db.sesion import FabricaSesion
from app.models.guerra import Guerra
from app.services import asaltos as servicio_asaltos
from app.services import capturas as servicio_capturas
from app.services import guerras as servicio_guerras
from app.services import stacy_proactiva
from app.services.clash_client import ClashApiError, ClashClient

logger = logging.getLogger("clanmanager.scheduler")


async def capturar_periodicamente(cliente: ClashClient) -> None:
    """Tarea programada: crea una captura del clan y la guarda."""
    async with FabricaSesion() as sesion:
        try:
            captura = await servicio_capturas.crear_captura(sesion, cliente)
        except ClashApiError as error:
            logger.error("Falló la captura automática: %s", error)
            return

    logger.info(
        "Captura automática guardada: id=%s clan=%s miembros=%s",
        captura.id, captura.nombre_clan, captura.total_miembros,
    )


async def capturar_guerra_periodicamente(
    cliente: ClashClient, programador: AsyncIOScheduler
) -> None:
    """
    Sondea la guerra actual y agenda los 4 hitos proactivos de WhatsApp:
    1. INICIO (inicio + 1 min)
    2. CORTE_5H (inicio + 5 horas + 1 min) -> Apertura de Mapa Libre
    3. ULTIMAS_3H (fin - 3 horas) -> Alerta roja de pendientes
    4. FINAL (fin + 2 min) -> Cierre definitivo y resumen final
    """
    ahora = datetime.now(timezone.utc)

    async with FabricaSesion() as sesion:
        ultima = await servicio_guerras.ultima_guerra_conocida(sesion)

    if ultima is not None and ultima.inicio is not None:
        # Asegurar que los hitos futuros queden agendados aunque estemos en preparación
        _programar_hitos_guerra(programador, cliente, ultima)
        if ultima.preparacion_inicio <= ahora < ultima.inicio:
            logger.debug(
                "Guerra %s todavía en preparación, hitos agendados hasta el día de batalla",
                ultima.id,
            )
            return

    async with FabricaSesion() as sesion:
        try:
            guerra = await servicio_guerras.guardar_guerra_actual(sesion, cliente)
        except ClashApiError as error:
            logger.error("Falló el sondeo de guerra: %s", error)
            return

    if guerra is None:
        logger.debug("Sondeo de guerra: el clan no está en guerra ahora mismo")
        return

    logger.info(
        "Guerra actualizada: id=%s estado=%s rival=%s estrellas=%s/%s",
        guerra.id, guerra.estado, guerra.rival_nombre, guerra.clan_estrellas, guerra.rival_estrellas,
    )

    _programar_hitos_guerra(programador, cliente, guerra)


def _programar_hitos_guerra(
    programador: AsyncIOScheduler, cliente: ClashClient, guerra: Guerra
) -> None:
    """Agenda en APScheduler los DateTriggers futuros para la guerra actual."""
    ahora = datetime.now(timezone.utc)
    ts_base = f"{guerra.preparacion_inicio.timestamp():.0f}"
    es_cwl = bool(guerra.war_tag)

    # 1. Alerta de Inicio de Guerra (inicio + 1 min)
    if guerra.inicio is not None:
        disparo_inicio = guerra.inicio + timedelta(minutes=1)
        if disparo_inicio > ahora:
            programador.add_job(
                ejecutar_hito_guerra,
                trigger=DateTrigger(run_date=disparo_inicio),
                args=[cliente, "INICIO"],
                id=f"alerta_guerra_inicio_{ts_base}",
                replace_existing=True,
            )
            logger.info("Alerta INICIO de guerra %s programada para %s", guerra.id, disparo_inicio)

        # 2. Alerta de Corte de 5 Horas / Mapa Libre (solo Guerra Clásica)
        if not es_cwl:
            disparo_5h = guerra.inicio + timedelta(hours=5, minutes=1)
            if disparo_5h > ahora:
                programador.add_job(
                    ejecutar_hito_guerra,
                    trigger=DateTrigger(run_date=disparo_5h),
                    args=[cliente, "CORTE_5H"],
                    id=f"alerta_guerra_5h_{ts_base}",
                    replace_existing=True,
                )
                logger.info("Alerta CORTE_5H (Mapa Libre) de guerra %s programada para %s", guerra.id, disparo_5h)

    if guerra.fin is not None:
        # 3. Alerta Roja de Últimas 3 Horas (fin - 3 horas)
        disparo_3h = guerra.fin - timedelta(hours=3)
        if disparo_3h > ahora:
            programador.add_job(
                ejecutar_hito_guerra,
                trigger=DateTrigger(run_date=disparo_3h),
                args=[cliente, "ULTIMAS_3H"],
                id=f"alerta_guerra_3h_{ts_base}",
                replace_existing=True,
            )
            logger.info("Alerta ULTIMAS_3H de guerra %s programada para %s", guerra.id, disparo_3h)

        # 4. Captura Final + Resumen de Cierre (fin + 2 min)
        disparo_final = guerra.fin + timedelta(
            minutes=settings.guerra_captura_final_demora_minutos
        )
        if disparo_final > ahora:
            programador.add_job(
                capturar_guerra_una_vez,
                trigger=DateTrigger(run_date=disparo_final),
                args=[cliente],
                id=f"captura_guerra_final_{ts_base}",
                replace_existing=True,
            )
            logger.info("Captura y Alerta FINAL de guerra %s programada para %s", guerra.id, disparo_final)


async def ejecutar_hito_guerra(cliente: ClashClient, tipo_evento: str) -> None:
    """Ejecuta el sondeo puntual y dispara el anuncio proactivo de S.T.A.C.Y. en WhatsApp."""
    try:
        await stacy_proactiva.disparar_alerta_guerra(cliente, tipo_evento=tipo_evento)
    except Exception as exc:
        logger.exception("Error ejecutando hito proactivo %s: %s", tipo_evento, exc)


async def capturar_guerra_una_vez(cliente: ClashClient) -> None:
    """Captura final garantizada al terminar la guerra + envío del resumen de cierre a WhatsApp."""
    async with FabricaSesion() as sesion:
        try:
            guerra = await servicio_guerras.guardar_guerra_actual(sesion, cliente)
        except ClashApiError as error:
            logger.error("Falló la captura final de guerra: %s", error)
            return

    if guerra is not None:
        logger.info(
            "Captura final de guerra registrada: id=%s estado=%s estrellas=%s/%s",
            guerra.id, guerra.estado, guerra.clan_estrellas, guerra.rival_estrellas,
        )
        await ejecutar_hito_guerra(cliente, "FINAL")


async def capturar_liga_una_vez(cliente: ClashClient) -> None:
    """Tarea programada: sondea la Liga de Guerras de Clanes (CWL) actual."""
    async with FabricaSesion() as sesion:
        try:
            resultado = await servicio_guerras.guardar_liga_actual(sesion, cliente)
        except ClashApiError as error:
            logger.debug("Sin Liga de Guerras de Clanes activa o falló el sondeo: %s", error)
            return

    for guerra in resultado.guerras_propias:
        logger.info(
            "Guerra de CWL actualizada: ronda=%s id=%s estado=%s rival=%s estrellas=%s/%s",
            guerra.liga_ronda, guerra.id, guerra.estado, guerra.rival_nombre,
            guerra.clan_estrellas, guerra.rival_estrellas,
        )


def _inicio_ventana_mas_reciente(ahora: datetime) -> datetime:
    dias_desde_inicio = (ahora.weekday() - settings.asalto_inicio_dia_semana) % 7
    candidato = datetime(
        ahora.year, ahora.month, ahora.day, settings.asalto_inicio_hora_utc, 0, 0, tzinfo=timezone.utc
    ) - timedelta(days=dias_desde_inicio)
    if candidato > ahora:
        candidato -= timedelta(days=7)
    return candidato


def _dentro_de_ventana_de_asaltos(ahora: datetime) -> bool:
    inicio = _inicio_ventana_mas_reciente(ahora)
    dias_duracion = (settings.asalto_fin_dia_semana - settings.asalto_inicio_dia_semana) % 7
    horas_duracion = settings.asalto_fin_hora_utc - settings.asalto_inicio_hora_utc
    duracion = timedelta(days=dias_duracion, hours=horas_duracion)
    if duracion <= timedelta():
        duracion += timedelta(days=7)

    fin = inicio + duracion + timedelta(minutes=settings.asalto_captura_final_demora_minutos)
    return inicio <= ahora < fin


async def capturar_asalto_periodicamente(cliente: ClashClient) -> None:
    """Tarea programada: guarda o actualiza el fin de semana de asaltos más reciente."""
    ahora = datetime.now(timezone.utc)
    if not _dentro_de_ventana_de_asaltos(ahora):
        logger.debug("Fuera de la ventana del Fin de Semana de Asaltos, se pospone el sondeo")
        return

    async with FabricaSesion() as sesion:
        try:
            asalto = await servicio_asaltos.guardar_asalto_actual(sesion, cliente)
        except ClashApiError as error:
            logger.error("Falló el sondeo de asaltos: %s", error)
            return

    if asalto is None:
        return

    logger.info(
        "Asalto actualizado: id=%s estado=%s oro_total=%s ataques=%s",
        asalto.id, asalto.estado, asalto.oro_capital_total, asalto.ataques_totales,
    )


def crear_programador(cliente: ClashClient) -> AsyncIOScheduler:
    """Crea el programador con las tareas de captura y alertas proactivas."""
    programador = AsyncIOScheduler()
    programador.add_job(
        capturar_periodicamente,
        trigger=IntervalTrigger(minutes=settings.captura_intervalo_minutos),
        args=[cliente],
        id="captura_periodica",
        coalesce=True,
        max_instances=1,
    )
    programador.add_job(
        capturar_guerra_periodicamente,
        trigger=IntervalTrigger(minutes=settings.guerra_intervalo_minutos),
        args=[cliente, programador],
        id="captura_guerra_periodica",
        coalesce=True,
        max_instances=1,
    )
    programador.add_job(
        capturar_liga_una_vez,
        trigger=IntervalTrigger(minutes=settings.liga_intervalo_minutos),
        args=[cliente],
        id="captura_liga_periodica",
        coalesce=True,
        max_instances=1,
    )
    programador.add_job(
        capturar_asalto_periodicamente,
        trigger=IntervalTrigger(minutes=settings.asalto_intervalo_minutos),
        args=[cliente],
        id="captura_asalto_periodica",
        coalesce=True,
        max_instances=1,
    )
    return programador