"""Servicio para crear y consultar capturas históricas del clan con concurrencia controlada."""

import asyncio
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.captura import Captura, CapturaMiembro
from app.schemas.miembro import MiembroOut
from app.services.clash_client import ClashApiError, ClashClient, normalizar_tag

# Máximo 6 peticiones simultáneas a Supercell para evitar bloqueos HTTP 429
_SEMAFORO_PERFILES_COC = asyncio.Semaphore(6)


async def _enriquecer_miembro_seguro(
    cliente: ClashClient, datos_miembro: dict
) -> CapturaMiembro:
    """Consulta el perfil individual respetando el semáforo de 6 conexiones máximas."""
    miembro = MiembroOut.desde_api(datos_miembro)
    async with _SEMAFORO_PERFILES_COC:
        try:
            jugador = await cliente.obtener_jugador(miembro.tag)
            miembro = miembro.con_heroes(jugador)
        except ClashApiError:
            # Si falla un perfil puntual, se conserva el miembro con sus datos base
            pass
        await asyncio.sleep(0.05)
    return CapturaMiembro(**miembro.model_dump())


async def crear_captura(sesion: AsyncSession, cliente: ClashClient) -> Captura:
    """
    Consulta el estado actual del clan y descarga los perfiles de los miembros
    en micro-lotes controlados por semáforo (~1.5s total sin saturar la API).
    """
    clan = await cliente.obtener_clan()
    lista_miembros_raw = clan.get("memberList", [])

    tareas = [
        _enriquecer_miembro_seguro(cliente, datos)
        for datos in lista_miembros_raw
    ]
    miembros = list(await asyncio.gather(*tareas))

    captura = Captura(
        tag_clan=clan["tag"],
        nombre_clan=clan["name"],
        nivel_clan=clan["clanLevel"],
        total_miembros=clan["members"],
        miembros=miembros,
    )

    sesion.add(captura)
    await sesion.commit()
    return captura


async def obtener_ultima_captura(sesion: AsyncSession) -> Captura | None:
    """Devuelve la captura más reciente, con sus miembros ya cargados, o None si no hay ninguna."""
    resultado = await sesion.execute(
        select(Captura)
        .order_by(Captura.capturado_en.desc())
        .limit(1)
        .options(selectinload(Captura.miembros))
    )
    return resultado.scalar_one_or_none()


async def listar_capturas(sesion: AsyncSession, limite: int) -> list[Captura]:
    """Devuelve las capturas más recientes, de la más nueva a la más antigua."""
    resultado = await sesion.execute(
        select(Captura).order_by(Captura.capturado_en.desc()).limit(limite)
    )
    return list(resultado.scalars().all())


async def obtener_captura(sesion: AsyncSession, captura_id: int) -> Captura | None:
    """Devuelve una captura por id, con sus miembros ya cargados."""
    resultado = await sesion.execute(
        select(Captura)
        .where(Captura.id == captura_id)
        .options(selectinload(Captura.miembros))
    )
    return resultado.scalar_one_or_none()


async def historial_miembro(
    sesion: AsyncSession, tag: str, limite: int
) -> list[CapturaMiembro]:
    """Devuelve el historial de un miembro a través de las capturas guardadas."""
    resultado = await sesion.execute(
        select(CapturaMiembro)
        .join(Captura)
        .where(CapturaMiembro.tag == normalizar_tag(tag))
        .order_by(Captura.capturado_en.desc())
        .limit(limite)
        .options(selectinload(CapturaMiembro.captura))
    )
    return list(resultado.scalars().all())


async def obtener_captura_desde(
    sesion: AsyncSession, fecha: datetime
) -> Captura | None:
    """Primera captura registrada en o después de la fecha dada."""
    resultado = await sesion.execute(
        select(Captura)
        .where(Captura.capturado_en >= fecha)
        .order_by(Captura.capturado_en.asc())
        .limit(1)
        .options(selectinload(Captura.miembros))
    )
    return resultado.scalar_one_or_none()


async def obtener_captura_hasta(
    sesion: AsyncSession, fecha: datetime
) -> Captura | None:
    """Última captura registrada en o antes de la fecha dada."""
    resultado = await sesion.execute(
        select(Captura)
        .where(Captura.capturado_en <= fecha)
        .order_by(Captura.capturado_en.desc())
        .limit(1)
        .options(selectinload(Captura.miembros))
    )
    return resultado.scalar_one_or_none()


def calcular_evolucion(inicial: Captura, final: Captura) -> list[dict]:
    """Compara el estado de cada miembro entre dos capturas."""
    por_tag_inicial = {m.tag: m for m in inicial.miembros}

    evolucion = []
    for miembro_final in final.miembros:
        miembro_inicial = por_tag_inicial.get(miembro_final.tag)
        if miembro_inicial is None:
            continue

        rango_delta = None
        if (
            miembro_inicial.rango_clan is not None
            and miembro_final.rango_clan is not None
        ):
            rango_delta = miembro_inicial.rango_clan - miembro_final.rango_clan

        evolucion.append({
            "tag": miembro_final.tag,
            "nombre": miembro_final.nombre,
            "donaciones_inicial": miembro_inicial.donaciones,
            "donaciones_final": miembro_final.donaciones,
            "donaciones_delta": miembro_final.donaciones - miembro_inicial.donaciones,
            "donaciones_reinicio": miembro_final.donaciones < miembro_inicial.donaciones,
            "trofeos_inicial": miembro_inicial.trofeos,
            "trofeos_final": miembro_final.trofeos,
            "trofeos_delta": miembro_final.trofeos - miembro_inicial.trofeos,
            "trofeos_reinicio": miembro_final.trofeos < miembro_inicial.trofeos,
            "rango_clan_inicial": miembro_inicial.rango_clan,
            "rango_clan_final": miembro_final.rango_clan,
            "rango_delta": rango_delta,
        })

    return evolucion