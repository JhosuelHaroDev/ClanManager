"""Esquemas del resumen de la Liga de Guerras de Clanes (CWL)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.guerra_guardada import GuerraResumenOut

# Qué pasó con un miembro en una ronda concreta:
#   "ataco": ya hizo su ataque.
#   "pendiente": está en la alineación, la ronda aún no termina y no ha atacado.
#   "sin_ataque": estaba en la alineación, la ronda terminó y no atacó.
#   "no_alineado": no estaba en la alineación de esa ronda.
EstadoAtaque = Literal["ataco", "pendiente", "sin_ataque", "no_alineado"]


class RondaMiembroOut(BaseModel):
    """Desempeño de un miembro en una ronda de la liga."""

    ronda: int
    estado: EstadoAtaque
    estrellas: int | None = None
    destruccion: float | None = None


class MiembroLigaOut(BaseModel):
    """Desempeño acumulado de un miembro a lo largo de la temporada de liga."""

    tag: str
    nombre: str
    nivel_ayuntamiento: int
    rondas_alineado: int
    ataques_realizados: int
    # Rondas ya terminadas en las que estaba alineado y no atacó.
    ataques_perdidos: int
    estrellas_total: int
    destruccion_promedio: float | None
    rondas: list[RondaMiembroOut]


class EnfrentamientoOut(BaseModel):
    """Una guerra de una ronda entre dos clanes cualquiera del grupo."""

    model_config = ConfigDict(from_attributes=True)

    war_tag: str
    ronda: int
    estado: str
    tamano_equipo: int | None
    inicio: datetime | None
    fin: datetime | None

    clan_a_tag: str
    clan_a_nombre: str
    clan_a_nivel: int
    clan_a_estrellas: int
    clan_a_destruccion: float

    clan_b_tag: str
    clan_b_nombre: str
    clan_b_nivel: int
    clan_b_estrellas: int
    clan_b_destruccion: float

    # Quién ganó, solo cuando la guerra ya terminó: "a", "b" o "empate".
    ganador: Literal["a", "b", "empate"] | None = None


class ClanClasificacionOut(BaseModel):
    """Una fila de la clasificación del grupo."""

    posicion: int
    tag: str
    nombre: str
    nivel: int
    es_propio: bool
    # Estrellas totales: las conseguidas en combate más 10 por cada guerra ganada.
    estrellas: int
    estrellas_en_combate: int
    estrellas_bono: int
    # Suma del porcentaje de destrucción de todas las bases de cada guerra.
    destruccion: int
    victorias: int
    derrotas: int
    empates: int


class ResumenLigaOut(BaseModel):
    """Temporada de liga completa: clasificación, rondas del grupo y desempeño de cada miembro."""

    temporada: str | None
    ronda_actual: int | None
    total_rondas: int
    clasificacion: list[ClanClasificacionOut]
    enfrentamientos: list[EnfrentamientoOut]
    # Las guerras de nuestro clan, con todo su detalle.
    rondas: list[GuerraResumenOut]
    miembros: list[MiembroLigaOut]