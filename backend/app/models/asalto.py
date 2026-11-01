"""Modelos del Fin de Semana de Asaltos a la Capital del Clan."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AsaltoCapital(Base):
    """Un fin de semana de asaltos completo."""

    __tablename__ = "asaltos_capital"
    __table_args__ = (UniqueConstraint("inicio"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    estado: Mapped[str] = mapped_column(String(20))
    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    oro_capital_total: Mapped[int]
    asaltos_completados: Mapped[int]
    ataques_totales: Mapped[int]
    distritos_rivales_destruidos: Mapped[int]
    recompensa_ofensiva: Mapped[int]
    recompensa_defensiva: Mapped[int]

    primera_captura_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ultima_actualizacion_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    miembros: Mapped[list["AsaltoMiembro"]] = relationship(
        back_populates="asalto", cascade="all, delete-orphan"
    )
    registros: Mapped[list["AsaltoRegistro"]] = relationship(
        back_populates="asalto", cascade="all, delete-orphan"
    )


class AsaltoMiembro(Base):
    """Participación de un miembro propio en el fin de semana de asaltos."""

    __tablename__ = "asalto_miembros"
    __table_args__ = (UniqueConstraint("asalto_id", "tag"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    asalto_id: Mapped[int] = mapped_column(
        ForeignKey("asaltos_capital.id", ondelete="CASCADE"), index=True
    )
    tag: Mapped[str] = mapped_column(String(20), index=True)
    nombre: Mapped[str] = mapped_column(String(50))
    ataques_usados: Mapped[int]
    limite_ataques: Mapped[int]
    ataques_bono: Mapped[int]
    oro_capital_saqueado: Mapped[int]

    asalto: Mapped["AsaltoCapital"] = relationship(back_populates="miembros")


class AsaltoRegistro(Base):
    """Una entrada del registro de asaltos contra un clan, propia o recibida."""

    __tablename__ = "asalto_registros"

    id: Mapped[int] = mapped_column(primary_key=True)
    asalto_id: Mapped[int] = mapped_column(
        ForeignKey("asaltos_capital.id", ondelete="CASCADE"), index=True
    )
    sentido: Mapped[str] = mapped_column(String(10))
    clan_tag: Mapped[str] = mapped_column(String(20))
    clan_nombre: Mapped[str] = mapped_column(String(50))
    clan_nivel: Mapped[int]
    ataques_usados: Mapped[int]
    distritos_totales: Mapped[int]
    distritos_destruidos: Mapped[int]

    asalto: Mapped["AsaltoCapital"] = relationship(back_populates="registros")
    distritos: Mapped[list["AsaltoDistrito"]] = relationship(
        back_populates="registro", cascade="all, delete-orphan"
    )


class AsaltoDistrito(Base):
    """Un distrito, propio o rival, dentro de un registro de asaltos."""

    __tablename__ = "asalto_distritos"

    id: Mapped[int] = mapped_column(primary_key=True)
    registro_id: Mapped[int] = mapped_column(
        ForeignKey("asalto_registros.id", ondelete="CASCADE"), index=True
    )
    distrito_id_juego: Mapped[int]
    nombre: Mapped[str] = mapped_column(String(50))
    nivel: Mapped[int]
    destruccion: Mapped[int]
    estrellas: Mapped[int]
    ataques_usados: Mapped[int]
    saqueado: Mapped[int]

    registro: Mapped["AsaltoRegistro"] = relationship(back_populates="distritos")
    ataques: Mapped[list["AsaltoAtaque"]] = relationship(
        back_populates="distrito", cascade="all, delete-orphan"
    )


class AsaltoAtaque(Base):
    """Un ataque individual contra un distrito con marca de tiempo de detección."""

    __tablename__ = "asalto_ataques"

    id: Mapped[int] = mapped_column(primary_key=True)
    distrito_id: Mapped[int] = mapped_column(
        ForeignKey("asalto_distritos.id", ondelete="CASCADE"), index=True
    )
    atacante_tag: Mapped[str] = mapped_column(String(20), index=True)
    atacante_nombre: Mapped[str] = mapped_column(String(50))
    estrellas: Mapped[int]
    destruccion: Mapped[int]

    # Campos de auditoría forense (Etapa 2 de sondeo)
    detectado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    orden_aparicion: Mapped[int | None] = mapped_column(Integer)

    distrito: Mapped["AsaltoDistrito"] = relationship(back_populates="ataques")