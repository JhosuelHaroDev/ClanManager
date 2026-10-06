"""Servicio para guardar y actualizar el registro de guerras, clásicas y de la Liga de Guerras de Clanes."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.guerra import Guerra, GuerraAtaque, GuerraMiembro
from app.schemas.guerra import BandoGuerraOut, GuerraActualOut
from app.services.clash_client import ClashClient, normalizar_tag


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


async def guardar_liga_actual(sesion: AsyncSession, cliente: ClashClient) -> list[Guerra]:
    """
    Sondea el grupo de la Liga de Guerras de Clanes (CWL) actual y guarda o
    actualiza la guerra de nuestro clan en cada ronda ya disponible.

    Para cada ronda, si ya sabemos cuál de sus war tags es el nuestro, lo
    consulta directamente. Si no, recorre los war tags de esa ronda hasta
    encontrar el que involucra a nuestro clan, ignorando el marcador "#0"
    que Supercell usa para rondas todavía no reveladas. Una vez encontrado,
    ese war tag queda guardado junto con la guerra, así que las siguientes
    veces no hace falta volver a buscarlo.
    """
    grupo = await cliente.obtener_grupo_liga_guerras()
    temporada = grupo["season"]
    nuestro_tag = normalizar_tag(settings.clan_tag)

    guardadas: list[Guerra] = []

    for numero_ronda, ronda in enumerate(grupo.get("rounds", []), start=1):
        war_tag_conocido = await war_tag_de_ronda(sesion, temporada, numero_ronda)

        if war_tag_conocido is not None:
            datos = await cliente.obtener_guerra_liga(war_tag_conocido)
            guerra = await _persistir_guerra_liga(sesion, datos, war_tag_conocido, temporada, numero_ronda)
            if guerra is not None:
                guardadas.append(guerra)
            continue

        for war_tag in ronda.get("warTags", []):
            if war_tag == "#0":
                continue  # Ronda todavía no revelada por Supercell.

            datos = await cliente.obtener_guerra_liga(war_tag)
            tags_involucrados = {datos.get("clan", {}).get("tag"), datos.get("opponent", {}).get("tag")}
            if nuestro_tag not in tags_involucrados:
                continue  # Es la guerra de otro emparejamiento de esta ronda, no la nuestra.

            guerra = await _persistir_guerra_liga(sesion, datos, war_tag, temporada, numero_ronda)
            if guerra is not None:
                guardadas.append(guerra)
            break  # Ya encontramos la guerra de esta ronda; no seguir revisando el resto.

    return guardadas


async def _persistir_guerra_liga(
    sesion: AsyncSession, datos: dict, war_tag: str, temporada: str, ronda: int
) -> Guerra | None:
    """Guarda o actualiza una guerra de CWL ya identificada, dado su JSON crudo."""
    guerra_actual = GuerraActualOut.desde_api(datos)

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
    """Copia los campos simples de la guerra, sin tocar miembros ni ataques."""
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


async def war_tag_de_ronda(sesion: AsyncSession, temporada: str, ronda: int) -> str | None:
    """Devuelve el war tag ya conocido para una ronda de CWL, o None si no se ha resuelto todavía."""
    resultado = await sesion.execute(
        select(Guerra.war_tag).where(Guerra.liga_temporada == temporada, Guerra.liga_ronda == ronda)
    )
    return resultado.scalar_one_or_none()