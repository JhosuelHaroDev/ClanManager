"""Programador de capturas automáticas del clan."""

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
from app.services.clash_client import ClashApiError, ClashClient

logger = logging.getLogger("clanmanager.scheduler")


async def capturar_periodicamente(cliente: ClashClient) -> None:
    """
    Tarea programada: crea una captura del clan y la guarda.

    Abre su propia sesión de base de datos, porque no hay una petición
    HTTP de la que tomarla como en los endpoints. Si la captura falla, el
    error se registra y no se propaga, para que un fallo puntual no
    detenga las capturas programadas siguientes.
    """
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


async def capturar_guerra_periodicamente(cliente: ClashClient, programador: AsyncIOScheduler) -> None:
    """
    Tarea programada: decide si vale la pena sondear la guerra actual ahora
    mismo, y si es así, la guarda o actualiza.

    Si ya sabemos, por una captura anterior, que la guerra actual todavía
    está en su día de preparación, no se hace ninguna llamada a la API:
    nada relevante cambia durante la preparación, así que sondear en ese
    tramo solo gastaría peticiones contra el proxy comunitario sin
    aportar nada nuevo. En cualquier otro caso, incluido no saber nada
    todavía, sí se sondea.
    """
    ahora = datetime.now(timezone.utc)

    async with FabricaSesion() as sesion:
        ultima = await servicio_guerras.ultima_guerra_conocida(sesion)

    if ultima is not None and ultima.inicio is not None:
        if ultima.preparacion_inicio <= ahora < ultima.inicio:
            logger.debug(
                "Guerra %s todavía en preparación, se pospone el sondeo hasta el día de batalla",
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

    _programar_captura_final(programador, cliente, guerra)


def _programar_captura_final(programador: AsyncIOScheduler, cliente: ClashClient, guerra: Guerra) -> None:
    """
    Agrega, si hace falta, una captura única justo después del fin de la
    guerra, para no perder ataques de último minuto.

    id_job se deriva de la fecha de preparación de la guerra, así que
    programarla de nuevo en un sondeo posterior, mientras la guerra siga
    siendo la misma, actualiza la misma tarea en vez de duplicarla.
    """
    if guerra.fin is None:
        return

    disparo = guerra.fin + timedelta(minutes=settings.guerra_captura_final_demora_minutos)

    if disparo <= datetime.now(timezone.utc):
        # El momento previsto ya pasó. Si la captura final todavía no se
        # disparó por alguna razón, volver a programarla aquí la haría
        # correr de inmediato, y si ya se disparó, no hay nada que hacer.
        return

    id_job = f"captura_guerra_final_{guerra.preparacion_inicio.timestamp():.0f}"

    programador.add_job(
        capturar_guerra_una_vez,
        trigger=DateTrigger(run_date=disparo),
        args=[cliente],
        id=id_job,
        replace_existing=True,
    )
    logger.info("Captura final de la guerra %s programada para %s", guerra.id, disparo)


async def capturar_guerra_una_vez(cliente: ClashClient) -> None:
    """
    Captura de guerra sin la lógica de ahorro de capturar_guerra_periodicamente.

    La usa la captura final garantizada, que debe ejecutarse sí o sí en el
    momento programado, sin evaluar si "vale la pena".
    """
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

async def capturar_liga_una_vez(cliente: ClashClient) -> None:
    """
    Tarea programada: sondea la Liga de Guerras de Clanes (CWL) actual.

    Si el clan no está participando en una CWL ahora mismo, Supercell
    responde con un error, que se trata igual que cualquier otro fallo de
    la API: se registra y no detiene el resto de las tareas programadas.
    """
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
    """Calcula el inicio del Fin de Semana de Asaltos más reciente en o antes de 'ahora'."""
    dias_desde_inicio = (ahora.weekday() - settings.asalto_inicio_dia_semana) % 7
    candidato = datetime(
        ahora.year, ahora.month, ahora.day, settings.asalto_inicio_hora_utc, 0, 0, tzinfo=timezone.utc
    ) - timedelta(days=dias_desde_inicio)
    if candidato > ahora:
        candidato -= timedelta(days=7)
    return candidato

def _dentro_de_ventana_de_asaltos(ahora: datetime) -> bool:
    """
    Indica si 'ahora' cae dentro de la ventana semanal en la que puede
    haber un Fin de Semana de Asaltos activo, con un margen extra al
    final para alcanzar a capturar los números ya asentados.
    """
    inicio = _inicio_ventana_mas_reciente(ahora)

    dias_duracion = (settings.asalto_fin_dia_semana - settings.asalto_inicio_dia_semana) % 7
    horas_duracion = settings.asalto_fin_hora_utc - settings.asalto_inicio_hora_utc
    duracion = timedelta(days=dias_duracion, hours=horas_duracion)
    if duracion <= timedelta():
        # Si fin e inicio calculan una duración de cero o negativa, es que
        # el evento dura toda la semana hasta la próxima ocurrencia.
        duracion += timedelta(days=7)

    fin = inicio + duracion + timedelta(minutes=settings.asalto_captura_final_demora_minutos)
    return inicio <= ahora < fin

async def capturar_asalto_periodicamente(cliente: ClashClient) -> None:
    """
    Tarea programada: guarda o actualiza el fin de semana de asaltos más
    reciente, solo durante la ventana semanal en la que puede haber uno
    activo.

    Fuera de esa ventana, calculada según el calendario configurado, no
    tiene sentido sondear: no va a haber datos nuevos hasta el próximo
    viernes, así que hacerlo solo gastaría peticiones contra el proxy
    comunitario sin aportar nada.
    """
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
        logger.debug("Sondeo de asaltos: todavía no hay ningún fin de semana registrado")
        return

    logger.info(
        "Asalto actualizado: id=%s estado=%s oro_total=%s ataques=%s",
        asalto.id, asalto.estado, asalto.oro_capital_total, asalto.ataques_totales,
    )

def crear_programador(cliente: ClashClient) -> AsyncIOScheduler:
    """
    Crea el programador con las tareas de captura ya registradas.

    No lo inicia: quien lo crea decide cuándo llamar a .start() y .shutdown().
    """
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