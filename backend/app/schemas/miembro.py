"""Esquemas de datos de los miembros del clan."""

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class MiembroOut(BaseModel):
    """Miembro del clan tal como lo devuelve nuestra API al frontend."""

    # Permite construir el esquema a partir de objetos de la base de datos,
    # además de a partir de diccionarios.
    model_config = ConfigDict(from_attributes=True)

    tag: str
    nombre: str
    rol: str
    nivel_experiencia: int
    nivel_ayuntamiento: int
    trofeos: int
    donaciones: int
    donaciones_recibidas: int
    # Liga actual del sistema de batallas clasificatorias. Puede faltar si
    # el jugador no tiene liga asignada.
    liga: str | None = None

    # Posición del miembro dentro del ranking interno del clan.
    rango_clan: int | None = None
    rango_clan_anterior: int | None = None
    # Aldea de constructor: null en cuentas muy antiguas, o en registros
    # guardados antes de que empezáramos a leer estos campos.
    trofeos_base: int | None = None
    liga_base: str | None = None

    # Niveles de héroe de la aldea principal. Ninguno viene en la lista de
    # miembros del clan: solo se llenan cuando se combinan con los datos
    # del jugador individual, vía con_heroes, como se hace al crear una
    # captura. En el endpoint en vivo de miembros quedan en None.
    nivel_rey_barbaro: int | None = None
    nivel_reina_arquera: int | None = None
    nivel_gran_centinela: int | None = None
    nivel_principe_esbirro: int | None = None
    nivel_luchadora_real: int | None = None
    nivel_duque_dragon: int | None = None

    # Traduce el nombre de héroe en inglés que entrega la API al nombre
    # del campo correspondiente en español. Es el único lugar que conoce
    # esa correspondencia.
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
        Devuelve una copia de este miembro con los niveles de héroe
        rellenados a partir del detalle crudo de /players/{tag}.

        Solo toma los héroes de la aldea principal ("home"); los de la
        aldea de constructor no nos interesan para esto.
        """
        niveles: dict[str, int] = {}
        for heroe in jugador.get("heroes", []):
            if heroe.get("village") != "home":
                continue
            campo = self._CAMPO_POR_HEROE.get(heroe.get("name"))
            if campo:
                niveles[campo] = heroe["level"]
        return self.model_copy(update=niveles)

    @classmethod
    def desde_api(cls, datos: dict) -> "MiembroOut":
        """
        Construye un miembro a partir del diccionario crudo de Supercell.

        Esta clase es el único lugar que conoce los nombres de campo de la API externa.
        """
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
        """Construye la lista de miembros a partir del detalle completo del clan."""
        return [cls.desde_api(miembro) for miembro in clan["memberList"]]


class PuntoHistorialOut(MiembroOut):
    """Estado de un miembro en un momento dado de su historial de capturas."""

    capturado_en: datetime