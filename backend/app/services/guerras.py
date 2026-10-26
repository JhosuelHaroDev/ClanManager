"""Servicio para guardar y actualizar el registro de guerras, clásicas y de la Liga de Guerras de Clanes."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.guerra import Guerra, GuerraAtaque, GuerraMiembro
from app.models.liga import LigaEnfrentamiento
from app.schemas.guerra import BandoGuerraOut, GuerraActualOut
from app.services.clash_client import ClashApiError, ClashClient, normalizar_tag
from app.services.liga import guardar_enfrentamiento

async def guardar_guerra_actual(sesion: AsyncSession, cliente: ClashClient) -> Guerra | None:
    """
    Consulta la guerra clásica actual y guarda o actualiza su registro.

    Si el clan no está en guerra, no hay nada que guardar y devuelve None.
    Se identifica por su fecha de inicio de preparación, que es única
    para una guerra clásica.
    """
    datos = await cliente.obtener_guerra_actual()
    guerra_actual = GuerraActualOut.desde_api(datos)

    if guerra_actual.clan is None or guerra_actual.rival is None:
        return None
    if guerra_actual.preparacion_inicio is None:
        return None

    return await _guardar_o_actualizar(
        sesion,
        guerra_actual,
        filtro=(Guerra.preparacion_inicio == guerra_actual.preparacion_inicio),
        datos_extra={},
    )

@dataclass
class ResultadoSondeoLiga:
    """Qué hizo un sondeo de la liga, para que quien lo pidió pueda informarlo."""

    en_liga: bool
    guerras_propias: list[Guerra]
    enfrentamientos_consultados: int


async def guardar_liga_actual(sesion: AsyncSession, cliente: ClashClient) -> ResultadoSondeoLiga:
    """
    Sondea el grupo de la Liga de Guerras de Clanes (CWL) actual y guarda
    todas las guerras de cada ronda ya disponible.

    De cada guerra del grupo, sea de nuestro clan o no, se guarda el
    resumen en LigaEnfrentamiento, que alimenta la clasificación y la
    vista de rondas. De las de nuestro clan, además, se guarda el detalle
    completo en Guerra. Las guerras ya terminadas no se vuelven a pedir a
    Supercell: su resultado ya no cambia. Los marcadores "#0" son rondas
    que Supercell todavía no reveló.
    """
    grupo = await cliente.obtener_grupo_liga_guerras()

    # Fuera de una CWL, Supercell puede responder con un error 404, que
    # sube como ClashApiError, o con una respuesta sin temporada. Como
    # con notInWar en las guerras clásicas, no se asume que los campos
    # existan: sin temporada no hay liga que guardar.
    temporada = grupo.get("season")
    if not temporada:
        return ResultadoSondeoLiga(en_liga=False, guerras_propias=[], enfrentamientos_consultados=0)

    nuestro_tag = normalizar_tag(settings.clan_tag)
    propias: list[Guerra] = []
    consultados = 0

    for numero_ronda, ronda in enumerate(grupo.get("rounds", []), start=1):
        for war_tag in ronda.get("warTags", []):
            if war_tag == "#0":
                continue  # Ronda todavía no revelada por Supercell.
            if await _ya_es_definitiva(sesion, war_tag, nuestro_tag):
                continue

            try:
                datos = await cliente.obtener_guerra_liga(war_tag)
            except ClashApiError as error:
                if error.status_code == 404:
                    continue  # Esa guerra todavía no existe; se reintenta en el próximo sondeo.
                raise
            consultados += 1

            await guardar_enfrentamiento(sesion, datos, war_tag, temporada, numero_ronda)

            tags_involucrados = {datos.get("clan", {}).get("tag"), datos.get("opponent", {}).get("tag")}
            if nuestro_tag in tags_involucrados:
                guerra = await _persistir_guerra_liga(sesion, datos, war_tag, temporada, numero_ronda)
                if guerra is not None:
                    propias.append(guerra)

    await sesion.commit()
    return ResultadoSondeoLiga(en_liga=True, guerras_propias=propias, enfrentamientos_consultados=consultados)


async def _ya_es_definitiva(sesion: AsyncSession, war_tag: str, nuestro_tag: str) -> bool:
    """
    Indica si una guerra del grupo ya terminó y está bien guardada, de modo
    que no hace falta volver a pedirla a Supercell.

    Si es una guerra de nuestro clan, además de haber terminado, debe
    tener guardado su detalle con nuestro clan del lado correcto. Esa
    segunda condición es lo que permite que guerras guardadas con los
    lados invertidos, por un error anterior, se vuelvan a pedir una vez
    y queden corregidas.
    """
    resultado = await sesion.execute(
        select(LigaEnfrentamiento).where(LigaEnfrentamiento.war_tag == war_tag)
    )
    enfrentamiento = resultado.scalar_one_or_none()
    if enfrentamiento is None or enfrentamiento.estado != "warEnded":
        return False
    if nuestro_tag not in (enfrentamiento.clan_a_tag, enfrentamiento.clan_b_tag):
        return True

    resultado = await sesion.execute(select(Guerra).where(Guerra.war_tag == war_tag))
    guerra = resultado.scalar_one_or_none()
    return guerra is not None and guerra.clan_tag == nuestro_tag and guerra.estado == "warEnded"


def _orientar_hacia_nuestro_clan(datos: dict, nuestro_tag: str) -> dict:
    """
    Devuelve la guerra con nuestro clan siempre en el lado "clan".

    En una guerra de CWL, Supercell no garantiza que "clan" sea el nuestro:
    puede venir como "opponent". Si no se corrige, los marcadores, los
    miembros y los ataques de ambos bandos quedan intercambiados.
    """
    if datos.get("opponent", {}).get("tag") == nuestro_tag:
        return {**datos, "clan": datos["opponent"], "opponent": datos.get("clan")}
    return datos

async def _persistir_guerra_liga(
    sesion: AsyncSession, datos: dict, war_tag: str, temporada: str, ronda: int
) -> Guerra | None:
    """Guarda o actualiza una guerra de CWL ya identificada, dado su JSON crudo."""
    guerra_actual = GuerraActualOut.desde_api(
        _orientar_hacia_nuestro_clan(datos, normalizar_tag(settings.clan_tag))
    )

    if guerra_actual.clan is None or guerra_actual.rival is None:
        return None
    if guerra_actual.preparacion_inicio is None:
        return None

    return await _guardar_o_actualizar(
        sesion,
        guerra_actual,
        filtro=(Guerra.war_tag == war_tag),
        datos_extra={"war_tag": war_tag, "liga_temporada": temporada, "liga_ronda": ronda},
    )


async def _guardar_o_actualizar(
    sesion: AsyncSession,
    guerra_actual: GuerraActualOut,
    *,
    filtro,
    datos_extra: dict,
) -> Guerra:
    """
    Crea o actualiza en el lugar la fila de Guerra que cumple el filtro dado.

    Compartida entre guerras clásicas y de CWL: lo único que cambia entre
    ambas es cómo se identifica la fila (filtro) y qué datos adicionales
    lleva al crearla (datos_extra, por ejemplo el war_tag y la ronda).
    """
    resultado = await sesion.execute(
        select(Guerra).where(filtro).options(selectinload(Guerra.miembros), selectinload(Guerra.ataques))
    )
    guerra = resultado.scalar_one_or_none()

    if guerra is None:
        guerra = Guerra(preparacion_inicio=guerra_actual.preparacion_inicio, **datos_extra)
        sesion.add(guerra)
    else:
        # La API siempre entrega el estado acumulado hasta el momento, así
        # que reconstruir desde cero es más simple y más seguro que tratar
        # de aplicar solo lo que cambió. flush() fuerza a que el borrado de
        # las filas viejas se ejecute antes de insertar las nuevas: sin
        # esto, SQLAlchemy puede mandar ambas operaciones en un orden que
        # choca contra la restricción de unicidad de (guerra_id, tag).
        guerra.miembros.clear()
        guerra.ataques.clear()
        await sesion.flush()

    _actualizar_datos_generales(guerra, guerra_actual)
    _agregar_miembros_y_ataques(guerra, guerra_actual.clan, es_propio=True)
    _agregar_miembros_y_ataques(guerra, guerra_actual.rival, es_propio=False)

    await sesion.commit()
    return guerra


def _actualizar_datos_generales(guerra: Guerra, actual: GuerraActualOut) -> None:
    """Copia los campos simples de la guerra y actualiza el corte de las 5 horas."""
    guerra.estado = actual.estado
    guerra.tamano_equipo = actual.tamano_equipo
    guerra.ataques_por_miembro = actual.ataques_por_miembro
    guerra.modificador_batalla = actual.modificador_batalla
    guerra.inicio = actual.inicio
    guerra.fin = actual.fin

    guerra.clan_tag = actual.clan.tag
    guerra.clan_nombre = actual.clan.nombre
    guerra.clan_nivel = actual.clan.nivel_clan
    guerra.clan_estrellas = actual.clan.estrellas
    guerra.clan_destruccion = actual.clan.destruccion
    guerra.clan_ataques_usados = actual.clan.ataques_usados
    guerra.clan_experiencia_ganada = actual.clan.experiencia_ganada

    guerra.rival_tag = actual.rival.tag
    guerra.rival_nombre = actual.rival.nombre
    guerra.rival_nivel = actual.rival.nivel_clan
    guerra.rival_estrellas = actual.rival.estrellas
    guerra.rival_destruccion = actual.rival.destruccion

    # Auditoría automática de la Regla de las 5 Horas:
    # Si estamos dentro de las primeras 5 horas desde el inicio de batalla,
    # guardamos el mayor 'orden' de ataque visto hasta ese instante.
    if actual.inicio is not None:
        ahora_utc = datetime.now(timezone.utc)
        limite_5h = actual.inicio + timedelta(hours=5)
        if ahora_utc <= limite_5h:
            ordenes = [
                atk.orden
                for bando in (actual.clan, actual.rival)
                if bando is not None
                for m in bando.miembros
                for atk in m.ataques_realizados
            ]
            max_actual = max(ordenes, default=0)
            guerra.max_orden_5h = max(guerra.max_orden_5h or 0, max_actual)


def _agregar_miembros_y_ataques(guerra: Guerra, bando: BandoGuerraOut, *, es_propio: bool) -> None:
    """Agrega los miembros de un bando y los ataques que cada uno realizó."""
    for miembro in bando.miembros:
        guerra.miembros.append(
            GuerraMiembro(
                tag=miembro.tag,
                nombre=miembro.nombre,
                nivel_ayuntamiento=miembro.nivel_ayuntamiento,
                posicion_mapa=miembro.posicion_mapa,
                es_propio=es_propio,
                ataques_recibidos=miembro.ataques_recibidos,
            )
        )
        for ataque in miembro.ataques_realizados:
            guerra.ataques.append(
                GuerraAtaque(
                    orden=ataque.orden,
                    atacante_tag=ataque.atacante_tag,
                    atacante_nombre=ataque.atacante_nombre or miembro.nombre,
                    defensor_tag=ataque.defensor_tag,
                    defensor_nombre=ataque.defensor_nombre or "",
                    estrellas=ataque.estrellas,
                    destruccion=ataque.destruccion,
                    duracion_segundos=ataque.duracion_segundos,
                )
            )


async def listar_guerras(sesion: AsyncSession, limite: int) -> list[Guerra]:
    """
    Devuelve las guerras clásicas guardadas, de la más reciente a la más
    antigua.

    Excluye las rondas de CWL a propósito: war_tag IS NULL es justo lo
    que distingue a una guerra clásica de una de liga en esta tabla. Las
    rondas de CWL se listan aparte, agrupadas por temporada y ronda, no
    mezcladas en este historial.
    """
    resultado = await sesion.execute(
        select(Guerra)
        .where(Guerra.war_tag.is_(None))
        .order_by(Guerra.preparacion_inicio.desc())
        .limit(limite)
    )
    return list(resultado.scalars().all())


async def obtener_guerra(sesion: AsyncSession, guerra_id: int) -> Guerra | None:
    """Devuelve una guerra guardada por id, con sus miembros y ataques cargados."""
    resultado = await sesion.execute(
        select(Guerra)
        .where(Guerra.id == guerra_id)
        .options(selectinload(Guerra.miembros), selectinload(Guerra.ataques))
    )
    return resultado.scalar_one_or_none()


async def ultima_guerra_conocida(sesion: AsyncSession) -> Guerra | None:
    """Devuelve la guerra clásica más reciente que tenemos registrada, o None si no hay ninguna."""
    resultado = await sesion.execute(
        select(Guerra)
        .where(Guerra.war_tag.is_(None))
        .order_by(Guerra.preparacion_inicio.desc())
        .limit(1)
    )
    return resultado.scalar_one_or_none()