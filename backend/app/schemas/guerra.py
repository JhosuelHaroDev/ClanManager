"""Esquemas de datos de las guerras de clanes."""

from datetime import datetime, timezone

from pydantic import BaseModel


def _parsear_fecha_coc(valor: str | None) -> datetime | None:
    """
    Convierte una fecha en el formato propio de Supercell, por ejemplo
    "20261214T024715.000Z", a un datetime con zona horaria UTC.

    Devuelve None si el valor no vino, en vez de fallar, porque algunos
    estados de guerra no incluyen fechas.
    """
    if not valor:
        return None
    return datetime.strptime(valor, "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=timezone.utc)


class AtaqueGuerraOut(BaseModel):
    """Un ataque individual dentro de una guerra."""

    orden: int
    atacante_tag: str
    atacante_nombre: str | None = None
    defensor_tag: str
    defensor_nombre: str | None = None
    estrellas: int
    destruccion: float
    # No siempre viene incluida, según el endpoint consultado.
    duracion_segundos: int | None = None

    @classmethod
    def _desde_api(cls, datos: dict, nombres: dict[str, str]) -> "AtaqueGuerraOut":
        return cls(
            orden=datos["order"],
            atacante_tag=datos["attackerTag"],
            atacante_nombre=nombres.get(datos["attackerTag"]),
            defensor_tag=datos["defenderTag"],
            defensor_nombre=nombres.get(datos["defenderTag"]),
            estrellas=datos["stars"],
            destruccion=datos["destructionPercentage"],
            duracion_segundos=datos.get("duration"),
        )


class MiembroGuerraOut(BaseModel):
    """Estado de un miembro, propio o rival, dentro de una guerra."""

    tag: str
    nombre: str
    # Ojo: en el objeto de guerra este campo llega como "townhallLevel",
    # con hache minúscula, a diferencia de "townHallLevel" en /members.
    nivel_ayuntamiento: int
    posicion_mapa: int
    ataques_realizados: list[AtaqueGuerraOut]
    ataques_recibidos: int
    mejor_ataque_recibido: AtaqueGuerraOut | None = None

    @classmethod
    def _desde_api(cls, datos: dict, nombres: dict[str, str]) -> "MiembroGuerraOut":
        mejor = datos.get("bestOpponentAttack")
        return cls(
            tag=datos["tag"],
            nombre=datos["name"],
            nivel_ayuntamiento=datos["townhallLevel"],
            posicion_mapa=datos["mapPosition"],
            ataques_realizados=[
                AtaqueGuerraOut._desde_api(a, nombres) for a in datos.get("attacks", [])
            ],
            ataques_recibidos=datos.get("opponentAttacks", 0),
            mejor_ataque_recibido=(
                AtaqueGuerraOut._desde_api(mejor, nombres) if mejor else None
            ),
        )


class BandoGuerraOut(BaseModel):
    """Resumen de uno de los dos clanes participantes en la guerra actual."""

    tag: str
    nombre: str
    nivel_clan: int
    estrellas: int
    destruccion: float
    ataques_usados: int | None = None
    # Solo tiene sentido para el propio clan, no para el rival.
    experiencia_ganada: int | None = None
    miembros: list[MiembroGuerraOut]

    @classmethod
    def _desde_api(cls, datos: dict, nombres: dict[str, str]) -> "BandoGuerraOut":
        return cls(
            tag=datos["tag"],
            nombre=datos["name"],
            nivel_clan=datos["clanLevel"],
            estrellas=datos["stars"],
            destruccion=datos["destructionPercentage"],
            ataques_usados=datos.get("attacks"),
            experiencia_ganada=datos.get("expEarned"),
            miembros=[
                MiembroGuerraOut._desde_api(m, nombres) for m in datos.get("members", [])
            ],
        )


class GuerraActualOut(BaseModel):
    """Guerra clásica en curso o más reciente, tal como la ve el clan ahora mismo."""

    estado: str
    tamano_equipo: int | None = None
    # No viene en guerras de la Liga de Guerras de Clanes (CWL).
    ataques_por_miembro: int | None = None
    modificador_batalla: str | None = None
    preparacion_inicio: datetime | None = None
    inicio: datetime | None = None
    fin: datetime | None = None
    clan: BandoGuerraOut | None = None
    rival: BandoGuerraOut | None = None

    @classmethod
    def desde_api(cls, datos: dict) -> "GuerraActualOut":
        """
        Construye la guerra a partir del diccionario crudo de Supercell.

        Si el clan no está en guerra, "clan" y "opponent" no vienen en la
        respuesta, así que el resultado queda con estado "notInWar" y el
        resto de los campos en None.
        """
        clan_datos = datos.get("clan")
        rival_datos = datos.get("opponent")

        # Mapa de tag a nombre, combinando ambos bandos, para poder mostrar
        # el nombre del atacante y del defensor en cada ataque sin tener
        # que buscarlo aparte cada vez.
        nombres: dict[str, str] = {}
        for bando in (clan_datos, rival_datos):
            for miembro in (bando or {}).get("members", []):
                nombres[miembro["tag"]] = miembro["name"]

        return cls(
            estado=datos["state"],
            tamano_equipo=datos.get("teamSize"),
            ataques_por_miembro=datos.get("attacksPerMember"),
            modificador_batalla=datos.get("battleModifier"),
            preparacion_inicio=_parsear_fecha_coc(datos.get("preparationStartTime")),
            inicio=_parsear_fecha_coc(datos.get("startTime")),
            fin=_parsear_fecha_coc(datos.get("endTime")),
            # Cuando el clan no está en guerra, Supercell no omite las
            # claves "clan" y "opponent": las manda como objetos casi
            # vacíos, con badgeUrls y ceros, pero sin "tag". Por eso no
            # basta con comprobar que la clave exista; hay que comprobar
            # que de verdad traiga un tag antes de intentar construir el
            # bando completo.
            clan=BandoGuerraOut._desde_api(clan_datos, nombres) if clan_datos and clan_datos.get("tag") else None,
            rival=BandoGuerraOut._desde_api(rival_datos, nombres) if rival_datos and rival_datos.get("tag") else None,
        )


class ResumenBandoGuerraOut(BaseModel):
    """Resumen de un bando dentro de una entrada del registro de guerras."""

    tag: str | None = None
    nombre: str | None = None
    nivel_clan: int | None = None
    estrellas: int
    destruccion: float
    ataques: int | None = None
    experiencia_ganada: int | None = None

    @classmethod
    def _desde_api(cls, datos: dict) -> "ResumenBandoGuerraOut":
        return cls(
            tag=datos.get("tag"),
            nombre=datos.get("name"),
            nivel_clan=datos.get("clanLevel"),
            estrellas=datos["stars"],
            destruccion=datos["destructionPercentage"],
            ataques=datos.get("attacks"),
            experiencia_ganada=datos.get("expEarned"),
        )


class GuerraRegistroOut(BaseModel):
    """
    Una guerra pasada, según el registro público de Supercell.

    A diferencia de GuerraActualOut, aquí Supercell solo entrega el
    resumen de cada bando, sin el detalle de ataques por miembro. Por
    eso guardar nuestro propio historial, capturando la guerra mientras
    está en curso, sigue siendo necesario.
    """

    resultado: str
    tamano_equipo: int
    ataques_por_miembro: int | None = None
    fin: datetime
    clan: ResumenBandoGuerraOut
    rival: ResumenBandoGuerraOut

    @classmethod
    def desde_api(cls, datos: dict) -> "GuerraRegistroOut":
        return cls(
            resultado=datos["result"],
            tamano_equipo=datos["teamSize"],
            ataques_por_miembro=datos.get("attacksPerMember"),
            fin=_parsear_fecha_coc(datos["endTime"]),
            clan=ResumenBandoGuerraOut._desde_api(datos["clan"]),
            rival=ResumenBandoGuerraOut._desde_api(datos["opponent"]),
        )

    @classmethod
    def lista_desde_api(cls, items: list[dict]) -> list["GuerraRegistroOut"]:
        return [cls.desde_api(item) for item in items]