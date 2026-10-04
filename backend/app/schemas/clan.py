"""Esquema con el resumen del clan, para encabezados y pantallas generales."""

from pydantic import BaseModel


class ClanOut(BaseModel):
    """Datos generales del clan, sin la lista de miembros."""

    tag: str
    nombre: str
    nivel: int
    miembros: int
    puntos_clan: int | None = None
    guerras_ganadas: int | None = None
    racha_victorias: int | None = None
    trofeos_requeridos: int | None = None
    descripcion: str | None = None

    @classmethod
    def desde_api(cls, datos: dict) -> "ClanOut":
        return cls(
            tag=datos["tag"],
            nombre=datos["name"],
            nivel=datos["clanLevel"],
            miembros=datos["members"],
            puntos_clan=datos.get("clanPoints"),
            guerras_ganadas=datos.get("warWins"),
            racha_victorias=datos.get("warWinStreak"),
            trofeos_requeridos=datos.get("requiredTrophies"),
            descripcion=datos.get("description"),
        )