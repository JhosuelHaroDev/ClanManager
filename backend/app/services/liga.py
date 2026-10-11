"""Servicio de consulta del resumen de la Liga de Guerras de Clanes (CWL)."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.guerra import Guerra, GuerraAtaque
from app.schemas.liga import MiembroLigaOut, RondaMiembroOut


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