"""Modelos de las guerras de clanes."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Guerra(Base):
    """
    Estado de una guerra clásica, propia o en curso.

    A diferencia de Captura, esta tabla no acumula una fila nueva por cada
    sondeo: cada guerra tiene una sola fila, identificada por su fecha de
    inicio de preparación, que se actualiza en el lugar a medida que la
    guerra avanza, hasta quedar fija una vez que termina.
    """

    __tablename__ = "guerras"
    __table_args__ = (UniqueConstraint("preparacion_inicio"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    estado: Mapped[str] = mapped_column(String(20))
    tamano_equipo: Mapped[int | None]
    ataques_por_miembro: Mapped[int | None]
    modificador_batalla: Mapped[str | None] = mapped_column(String(20))

    preparacion_inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    inicio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Presente solo en guerras de la Liga de Guerras de Clanes (CWL): es el
    # identificador único que entrega Supercell para esa guerra puntual.
    # NULL en guerras clásicas, donde no existe tal identificador.
    war_tag: Mapped[str | None] = mapped_column(String(20), unique=True)
    liga_temporada: Mapped[str | None] = mapped_column(String(10))
    liga_ronda: Mapped[int | None]

    # Mayor número de orden registrado dentro de las primeras 5h de batalla (Regla de Espejo)
    max_orden_5h: Mapped[int | None]

    clan_tag: Mapped[str] = mapped_column(String(20))
    clan_nombre: Mapped[str] = mapped_column(String(50))
    clan_nivel: Mapped[int]
    clan_estrellas: Mapped[int]
    clan_destruccion: Mapped[float] = mapped_column(Float)
    clan_ataques_usados: Mapped[int | None]
    clan_experiencia_ganada: Mapped[int | None]

    rival_tag: Mapped[str] = mapped_column(String(20))
    rival_nombre: Mapped[str] = mapped_column(String(50))
    rival_nivel: Mapped[int]
    rival_estrellas: Mapped[int]
    rival_destruccion: Mapped[float] = mapped_column(Float)

    primera_captura_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ultima_actualizacion_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    miembros: Mapped[list["GuerraMiembro"]] = relationship(
        back_populates="guerra", cascade="all, delete-orphan"
    )
    ataques: Mapped[list["GuerraAtaque"]] = relationship(
        back_populates="guerra", cascade="all, delete-orphan"
    )


class GuerraMiembro(Base):
    """Un participante de la guerra, propio o rival."""

    __tablename__ = "guerra_miembros"
    __table_args__ = (UniqueConstraint("guerra_id", "tag"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    guerra_id: Mapped[int] = mapped_column(
        ForeignKey("guerras.id", ondelete="CASCADE"), index=True
    )
    tag: Mapped[str] = mapped_column(String(20), index=True)
    nombre: Mapped[str] = mapped_column(String(50))
    nivel_ayuntamiento: Mapped[int]
    posicion_mapa: Mapped[int]
    # True si es miembro de nuestro clan, False si es del rival.
    es_propio: Mapped[bool]
    ataques_recibidos: Mapped[int]

    guerra: Mapped["Guerra"] = relationship(back_populates="miembros")


class GuerraAtaque(Base):
    """
    Un ataque individual dentro de una guerra, de cualquiera de los dos bandos.

    No se referencia contra GuerraMiembro por clave foránea: guardar el tag
    y el nombre directamente aquí evita una relación autorreferenciada
    innecesaria, ya que atacante y defensor son ambos miembros de la misma
    guerra pero de bandos distintos.
    """

    __tablename__ = "guerra_ataques"
    __table_args__ = (UniqueConstraint("guerra_id", "atacante_tag", "orden"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    guerra_id: Mapped[int] = mapped_column(
        ForeignKey("guerras.id", ondelete="CASCADE"), index=True
    )
    orden: Mapped[int]
    atacante_tag: Mapped[str] = mapped_column(String(20), index=True)
    atacante_nombre: Mapped[str] = mapped_column(String(50))
    defensor_tag: Mapped[str] = mapped_column(String(20), index=True)
    defensor_nombre: Mapped[str] = mapped_column(String(50))
    estrellas: Mapped[int]
    destruccion: Mapped[float] = mapped_column(Float)
    duracion_segundos: Mapped[int | None]

    guerra: Mapped["Guerra"] = relationship(back_populates="ataques")