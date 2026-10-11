"""Servicio de consulta del resumen de la Liga de Guerras de Clanes (CWL)."""

from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.guerra import Guerra, GuerraAtaque
from app.models.liga import LigaEnfrentamiento
from app.schemas.guerra import GuerraActualOut
from app.schemas.liga import (
    ClanClasificacionOut,
    EnfrentamientoOut,
    MiembroLigaOut,
    RondaMiembroOut,
)

# Estrellas extra que da la liga por cada guerra ganada.
BONO_POR_VICTORIA = 10
# Una liga estándar tiene ocho clanes y por lo tanto siete rondas.
TOTAL_RONDAS = 7


async def temporada_mas_reciente(sesion: AsyncSession) -> str | None:
    """Devuelve la temporada de CWL más reciente que tenemos guardada, o None si no hay ninguna."""
    resultado = await sesion.execute(
        select(func.max(Guerra.liga_temporada)).where(Guerra.war_tag.is_not(None))
    )
    return resultado.scalar_one_or_none()


async def listar_rondas(sesion: AsyncSession, temporada: str) -> list[Guerra]:
    """Devuelve las rondas guardadas de una temporada, en orden, con miembros y ataques cargados."""
    resultado = await sesion.execute(
        select(Guerra)
        .where(Guerra.liga_temporada == temporada)
        .order_by(Guerra.liga_ronda)
        .options(selectinload(Guerra.miembros), selectinload(Guerra.ataques))
    )
    return list(resultado.scalars().all())


def calcular_rendimiento(rondas: list[Guerra]) -> list[MiembroLigaOut]:
    """
    Calcula el desempeño de cada miembro propio a lo largo de las rondas.

    Una ronda aporta a un miembro si estaba en su alineación (aparece
    como miembro propio de esa guerra). Si estaba y no atacó, cuenta como
    ataque perdido solo cuando la ronda ya terminó; en una ronda en
    curso queda "pendiente", porque todavía puede atacar.

    Función pura: no toca la base de datos, solo transforma lo ya cargado.
    """
    numeros_de_ronda = [r.liga_ronda for r in rondas if r.liga_ronda is not None]
    fichas: dict[str, dict] = {}

    for ronda in rondas:
        propios = {m.tag: m for m in ronda.miembros if m.es_propio}

        ataques_por_tag: dict[str, list[GuerraAtaque]] = {}
        for ataque in ronda.ataques:
            if ataque.atacante_tag in propios:
                ataques_por_tag.setdefault(ataque.atacante_tag, []).append(ataque)

        for tag, miembro in propios.items():
            ficha = fichas.setdefault(
                tag, {"nombre": miembro.nombre, "th": miembro.nivel_ayuntamiento, "por_ronda": {}}
            )
            # Las rondas vienen en orden, así que el último valor es el más reciente.
            ficha["nombre"] = miembro.nombre
            ficha["th"] = miembro.nivel_ayuntamiento

            ataques = ataques_por_tag.get(tag, [])
            if ataques:
                ficha["por_ronda"][ronda.liga_ronda] = RondaMiembroOut(
                    ronda=ronda.liga_ronda,
                    estado="ataco",
                    estrellas=sum(a.estrellas for a in ataques),
                    destruccion=max(a.destruccion for a in ataques),
                )
            else:
                estado = "sin_ataque" if ronda.estado == "warEnded" else "pendiente"
                ficha["por_ronda"][ronda.liga_ronda] = RondaMiembroOut(ronda=ronda.liga_ronda, estado=estado)

    resultado: list[MiembroLigaOut] = []
    for tag, ficha in fichas.items():
        # Las rondas donde no estaba alineado se completan explícitamente,
        # para que el frontend reciba siempre una entrada por cada ronda.
        rondas_miembro = [
            ficha["por_ronda"].get(n, RondaMiembroOut(ronda=n, estado="no_alineado"))
            for n in numeros_de_ronda
        ]
        con_ataque = [r for r in rondas_miembro if r.estado == "ataco"]

        resultado.append(
            MiembroLigaOut(
                tag=tag,
                nombre=ficha["nombre"],
                nivel_ayuntamiento=ficha["th"],
                rondas_alineado=sum(1 for r in rondas_miembro if r.estado != "no_alineado"),
                ataques_realizados=len(con_ataque),
                ataques_perdidos=sum(1 for r in rondas_miembro if r.estado == "sin_ataque"),
                estrellas_total=sum(r.estrellas or 0 for r in con_ataque),
                destruccion_promedio=(
                    sum(r.destruccion or 0 for r in con_ataque) / len(con_ataque) if con_ataque else None
                ),
                rondas=rondas_miembro,
            )
        )

    # Más estrellas primero; a igualdad, mayor destrucción promedio.
    resultado.sort(key=lambda m: (-m.estrellas_total, -(m.destruccion_promedio or 0)))
    return resultado


# --- Enfrentamientos de todo el grupo y clasificación --------------------


async def guardar_enfrentamiento(
    sesion: AsyncSession, datos: dict, war_tag: str, temporada: str, ronda: int
) -> LigaEnfrentamiento | None:
    """
    Guarda o actualiza el resumen de una guerra del grupo, dado su JSON crudo.

    Devuelve None si la respuesta no trae los dos clanes con su tag.
    """
    actual = GuerraActualOut.desde_api(datos)
    if actual.clan is None or actual.rival is None:
        return None

    resultado = await sesion.execute(
        select(LigaEnfrentamiento).where(LigaEnfrentamiento.war_tag == war_tag)
    )
    fila = resultado.scalar_one_or_none()
    if fila is None:
        fila = LigaEnfrentamiento(war_tag=war_tag)
        sesion.add(fila)

    fila.temporada = temporada
    fila.ronda = ronda
    fila.estado = actual.estado
    fila.tamano_equipo = actual.tamano_equipo
    fila.inicio = actual.inicio
    fila.fin = actual.fin

    fila.clan_a_tag = actual.clan.tag
    fila.clan_a_nombre = actual.clan.nombre
    fila.clan_a_nivel = actual.clan.nivel_clan
    fila.clan_a_estrellas = actual.clan.estrellas
    fila.clan_a_destruccion = actual.clan.destruccion

    fila.clan_b_tag = actual.rival.tag
    fila.clan_b_nombre = actual.rival.nombre
    fila.clan_b_nivel = actual.rival.nivel_clan
    fila.clan_b_estrellas = actual.rival.estrellas
    fila.clan_b_destruccion = actual.rival.destruccion

    await sesion.flush()
    return fila


async def listar_enfrentamientos(sesion: AsyncSession, temporada: str) -> list[LigaEnfrentamiento]:
    """Devuelve todos los enfrentamientos guardados de una temporada, por ronda."""
    resultado = await sesion.execute(
        select(LigaEnfrentamiento)
        .where(LigaEnfrentamiento.temporada == temporada)
        .order_by(LigaEnfrentamiento.ronda, LigaEnfrentamiento.id)
    )
    return list(resultado.scalars().all())


def ganador_de(
    estado: str, estrellas_a: int, destruccion_a: float, estrellas_b: int, destruccion_b: float
) -> Literal["a", "b", "empate"] | None:
    """
    Quién ganó una guerra, con el mismo criterio del juego: más estrellas, y
    si empatan, mayor destrucción. Devuelve None si la guerra no terminó,
    porque el resultado todavía no es definitivo.
    """
    if estado != "warEnded":
        return None
    if estrellas_a != estrellas_b:
        return "a" if estrellas_a > estrellas_b else "b"
    if destruccion_a != destruccion_b:
        return "a" if destruccion_a > destruccion_b else "b"
    return "empate"


def a_enfrentamiento_out(fila: LigaEnfrentamiento) -> EnfrentamientoOut:
    """Convierte la fila guardada al esquema de salida, agregando quién ganó."""
    salida = EnfrentamientoOut.model_validate(fila)
    ganador = ganador_de(
        fila.estado,
        fila.clan_a_estrellas, fila.clan_a_destruccion,
        fila.clan_b_estrellas, fila.clan_b_destruccion,
    )
    return salida.model_copy(update={"ganador": ganador})


def ronda_actual(enfrentamientos: list[LigaEnfrentamiento]) -> int | None:
    """
    Número de la ronda en la que está la liga ahora mismo.

    Es la ronda en día de batalla; si no hay ninguna, la primera que sigue
    en preparación; y si todas terminaron, la última.
    """
    estado_por_ronda = {e.ronda: e.estado for e in enfrentamientos}
    if not estado_por_ronda:
        return None

    en_batalla = [r for r, estado in estado_por_ronda.items() if estado == "inWar"]
    if en_batalla:
        return max(en_batalla)
    en_preparacion = [r for r, estado in estado_por_ronda.items() if estado == "preparation"]
    if en_preparacion:
        return min(en_preparacion)
    return max(estado_por_ronda)


def calcular_clasificacion(
    enfrentamientos: list[LigaEnfrentamiento], nuestro_tag: str
) -> list[ClanClasificacionOut]:
    """
    Arma la clasificación del grupo a partir de todos los enfrentamientos.

    Cada clan suma las estrellas que consiguió en combate, más 10 por cada
    guerra ganada que ya terminó, y la destrucción de todas las bases.
    Ordena por estrellas y, a igualdad, por destrucción.

    Función pura: no toca la base de datos.
    """
    acumulado: dict[str, dict] = {}

    for e in enfrentamientos:
        ganador = ganador_de(
            e.estado,
            e.clan_a_estrellas, e.clan_a_destruccion,
            e.clan_b_estrellas, e.clan_b_destruccion,
        )
        equipo = e.tamano_equipo or 15
        lados = (
            ("a", e.clan_a_tag, e.clan_a_nombre, e.clan_a_nivel, e.clan_a_estrellas, e.clan_a_destruccion),
            ("b", e.clan_b_tag, e.clan_b_nombre, e.clan_b_nivel, e.clan_b_estrellas, e.clan_b_destruccion),
        )
        for lado, tag, nombre, nivel, estrellas, destruccion in lados:
            fila = acumulado.setdefault(
                tag,
                {"nombre": nombre, "nivel": nivel, "estrellas": 0, "destruccion": 0,
                 "victorias": 0, "derrotas": 0, "empates": 0},
            )
            fila["nombre"], fila["nivel"] = nombre, nivel
            fila["estrellas"] += estrellas
            # El porcentaje del clan es el promedio de sus bases; multiplicarlo
            # por el tamaño del equipo da la suma, que siempre es un entero.
            fila["destruccion"] += round(destruccion * equipo)
            if ganador == lado:
                fila["victorias"] += 1
            elif ganador == "empate":
                fila["empates"] += 1
            elif ganador is not None:
                fila["derrotas"] += 1

    clanes = [
        ClanClasificacionOut(
            posicion=0,
            tag=tag,
            nombre=f["nombre"],
            nivel=f["nivel"],
            es_propio=tag == nuestro_tag,
            estrellas=f["estrellas"] + BONO_POR_VICTORIA * f["victorias"],
            estrellas_en_combate=f["estrellas"],
            estrellas_bono=BONO_POR_VICTORIA * f["victorias"],
            destruccion=f["destruccion"],
            victorias=f["victorias"],
            derrotas=f["derrotas"],
            empates=f["empates"],
        )
        for tag, f in acumulado.items()
    ]
    clanes.sort(key=lambda c: (-c.estrellas, -c.destruccion))
    return [c.model_copy(update={"posicion": i}) for i, c in enumerate(clanes, start=1)]