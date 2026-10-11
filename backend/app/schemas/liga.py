"""Esquemas del resumen de la Liga de Guerras de Clanes (CWL)."""

from typing import Literal

from pydantic import BaseModel

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


class ResumenLigaOut(BaseModel):
    """Temporada de liga completa: sus rondas y el desempeño de cada miembro."""

    temporada: str | None
    rondas: list[GuerraResumenOut]
    miembros: list[MiembroLigaOut]