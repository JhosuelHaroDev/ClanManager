"""Modelos de las capturas históricas del clan."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Captura(Base):
    """
    Instantánea del clan en un momento dado.

    Cada vez que consultamos la API y guardamos el resultado se crea una
    fila aquí. Las filas nunca se modifican: el historial se construye
    acumulando capturas, lo que permite comparar cómo evolucionó cada
    miembro entre una captura y otra.
    """

    __tablename__ = "capturas"

    id: Mapped[int] = mapped_column(primary_key=True)
    # La fecha la asigna la base de datos al insertar, con zona horaria.
    capturado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    tag_clan: Mapped[str] = mapped_column(String(20))
    nombre_clan: Mapped[str] = mapped_column(String(50))
    nivel_clan: Mapped[int]
    total_miembros: Mapped[int]

    miembros: Mapped[list["CapturaMiembro"]] = relationship(
        back_populates="captura", cascade="all, delete-orphan"
    )


class CapturaMiembro(Base):
    """Estado de un miembro del clan en el momento de una captura."""

    __tablename__ = "capturas_miembros"
    # Un mismo jugador no puede aparecer dos veces dentro de la misma captura.
    __table_args__ = (UniqueConstraint("captura_id", "tag"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    captura_id: Mapped[int] = mapped_column(
        ForeignKey("capturas.id", ondelete="CASCADE"), index=True
    )
    # Índice en el tag para consultar rápido el historial de un jugador.
    tag: Mapped[str] = mapped_column(String(20), index=True)
    nombre: Mapped[str] = mapped_column(String(50))
    rol: Mapped[str] = mapped_column(String(20))
    nivel_experiencia: Mapped[int]
    nivel_ayuntamiento: Mapped[int]
    trofeos: Mapped[int]
    donaciones: Mapped[int]
    donaciones_recibidas: Mapped[int]
    # Puede ser nulo si el jugador no tiene liga asignada.
    liga: Mapped[str | None] = mapped_column(String(50))

    # Posición del miembro dentro del ranking interno del clan.
    rango_clan: Mapped[int | None]
    rango_clan_anterior: Mapped[int | None]
    # Aldea de constructor: puede ser nula en cuentas muy antiguas o en
    # capturas guardadas antes de que empezáramos a leer estos campos.
    trofeos_base: Mapped[int | None]
    liga_base: Mapped[str | None] = mapped_column(String(50))

    # Niveles de héroe de la aldea principal. Nulos si el héroe todavía no
    # está desbloqueado a ese ayuntamiento, o en capturas guardadas antes
    # de que empezáramos a leer estos datos.
    nivel_rey_barbaro: Mapped[int | None]
    nivel_reina_arquera: Mapped[int | None]
    nivel_gran_centinela: Mapped[int | None]
    nivel_principe_esbirro: Mapped[int | None]
    nivel_luchadora_real: Mapped[int | None]
    nivel_duque_dragon: Mapped[int | None]

    captura: Mapped["Captura"] = relationship(back_populates="miembros")

    @property
    def capturado_en(self) -> datetime:
        """Fecha de la captura a la que pertenece este registro."""
        return self.captura.capturado_en