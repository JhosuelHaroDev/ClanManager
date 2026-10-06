"""
Esquemas para leer guerras ya guardadas en nuestra base de datos.

Se separan de los de app/schemas/guerra.py porque tienen una forma
distinta: los de guerra.py reflejan la respuesta anidada de Supercell
(miembros dentro de cada bando, ataques dentro de cada miembro), mientras
que estos reflejan cómo guardamos los datos, en dos listas planas al
mismo nivel que la guerra: sus miembros y sus ataques.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MiembroGuerraGuardadoOut(BaseModel):
    """Un participante de la guerra, tal como quedó guardado."""

    model_config = ConfigDict(from_attributes=True)

    tag: str
    nombre: str
    nivel_ayuntamiento: int
    posicion_mapa: int
    es_propio: bool
    ataques_recibidos: int


class AtaqueGuerraGuardadoOut(BaseModel):
    """Un ataque de la guerra, tal como quedó guardado."""

    model_config = ConfigDict(from_attributes=True)

    orden: int
    atacante_tag: str
    atacante_nombre: str
    defensor_tag: str
    defensor_nombre: str
    estrellas: int
    destruccion: float
    duracion_segundos: int | None = None


class GuerraResumenOut(BaseModel):
    """Resumen de una guerra guardada, sin miembros ni ataques."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    estado: str
    # Presentes solo si es una guerra de la Liga de Guerras de Clanes (CWL);
    # None en una guerra clásica.
    war_tag: str | None
    liga_temporada: str | None
    liga_ronda: int | None
    tamano_equipo: int | None
    ataques_por_miembro: int | None
    clan_nivel: int
    clan_estrellas: int
    clan_destruccion: float
    clan_ataques_usados: int | None
    rival_nombre: str
    rival_nivel: int
    rival_estrellas: int
    rival_destruccion: float
    inicio: datetime | None
    fin: datetime | None
    ultima_actualizacion_en: datetime


class GuerraDetalleOut(GuerraResumenOut):
    """
    Una guerra guardada, con el detalle completo de miembros y ataques.

    Hereda de GuerraResumenOut los campos básicos, incluidos el tamaño del
    equipo, los niveles de clan y los ataques usados; aquí solo se agrega
    lo que únicamente tiene sentido en la vista de detalle.
    """

    modificador_batalla: str | None
    preparacion_inicio: datetime

    clan_tag: str
    clan_nombre: str
    clan_experiencia_ganada: int | None

    rival_tag: str

    miembros: list[MiembroGuerraGuardadoOut]
    ataques: list[AtaqueGuerraGuardadoOut]