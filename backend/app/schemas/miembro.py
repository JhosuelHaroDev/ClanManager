"""Esquemas de datos de los miembros del clan."""

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class MiembroOut(BaseModel):
    """Miembro del clan tal como lo devuelve nuestra API y se guarda en CapturaMiembro."""

    model_config = ConfigDict(from_attributes=True)

    tag: str
    nombre: str
    rol: str
    nivel_experiencia: int
    nivel_ayuntamiento: int
    trofeos: int
    donaciones: int
    donaciones_recibidas: int
    liga: str | None = None

    rango_clan: int | None = None
    rango_clan_anterior: int | None = None
    trofeos_base: int | None = None
    liga_base: str | None = None

    preferencia_guerra: str | None = None
    estrellas_guerra: int | None = None

    nivel_rey_barbaro: int | None = None
    nivel_reina_arquera: int | None = None
    nivel_gran_centinela: int | None = None
    nivel_principe_esbirro: int | None = None
    nivel_luchadora_real: int | None = None
    nivel_duque_dragon: int | None = None

    _CAMPO_POR_HEROE: ClassVar[dict[str, str]] = {
        "Barbarian King": "nivel_rey_barbaro",
        "Archer Queen": "nivel_reina_arquera",
        "Grand Warden": "nivel_gran_centinela",
        "Minion Prince": "nivel_principe_esbirro",
        "Royal Champion": "nivel_luchadora_real",
        "Dragon Duke": "nivel_duque_dragon",
    }

    def con_heroes(self, jugador: dict) -> "MiembroOut":
        """
        Devuelve una copia de este miembro con los niveles de los 6 héroes,
        su preferencia de guerra ('in'/'out') y sus estrellas de guerra.
        """
        actualizaciones: dict[str, int | str | None] = {
            "preferencia_guerra": jugador.get("warPreference"),
            "estrellas_guerra": jugador.get("warStars"),
        }
        for heroe in jugador.get("heroes", []):
            if heroe.get("village") != "home":
                continue
            campo = self._CAMPO_POR_HEROE.get(heroe.get("name"))
            if campo:
                actualizaciones[campo] = heroe["level"]
        return self.model_copy(update=actualizaciones)

    @classmethod
    def desde_api(cls, datos: dict) -> "MiembroOut":
        return cls(
            tag=datos["tag"],
            nombre=datos["name"],
            rol=datos["role"],
            nivel_experiencia=datos["expLevel"],
            nivel_ayuntamiento=datos["townHallLevel"],
            trofeos=datos["trophies"],
            donaciones=datos["donations"],
            donaciones_recibidas=datos["donationsReceived"],
            liga=(datos.get("leagueTier") or {}).get("name"),
            rango_clan=datos.get("clanRank"),
            rango_clan_anterior=datos.get("previousClanRank"),
            trofeos_base=datos.get("builderBaseTrophies"),
            liga_base=(datos.get("builderBaseLeague") or {}).get("name"),
        )

    @classmethod
    def lista_desde_clan(cls, clan: dict) -> list["MiembroOut"]:
        return [cls.desde_api(miembro) for miembro in clan["memberList"]]


class PuntoHistorialOut(MiembroOut):
    """Estado de un miembro en un momento dado de su historial de capturas."""

    capturado_en: datetime