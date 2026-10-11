"""Modelo de los enfrentamientos de todo el grupo de la Liga de Guerras de Clanes."""

from datetime import datetime

from sqlalchemy import DateTime, Float, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LigaEnfrentamiento(Base):
    """
    Una guerra de una ronda de la liga entre dos clanes cualquiera del grupo.

    A diferencia de Guerra, que guarda con todo detalle solo las guerras de
    nuestro clan, aquí se guardan las de los ocho clanes, pero solo con el
    resumen de cada bando: lo justo para armar la clasificación del grupo
    y la vista de rondas, sin miembros ni ataques.

    "a" y "b" siguen el orden en que Supercell entrega los dos clanes, que
    no significa nada: ninguno de los dos lados es "el local" ni "el nuestro".
    """

    __tablename__ = "liga_enfrentamientos"

    id: Mapped[int] = mapped_column(primary_key=True)
    temporada: Mapped[str] = mapped_column(String(10), index=True)
    ronda: Mapped[int]
    war_tag: Mapped[str] = mapped_column(String(20), unique=True)
    estado: Mapped[str] = mapped_column(String(20))
    tamano_equipo: Mapped[int | None]
    inicio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    clan_a_tag: Mapped[str] = mapped_column(String(20))
    clan_a_nombre: Mapped[str] = mapped_column(String(50))
    clan_a_nivel: Mapped[int]
    clan_a_estrellas: Mapped[int]
    clan_a_destruccion: Mapped[float] = mapped_column(Float)

    clan_b_tag: Mapped[str] = mapped_column(String(20))
    clan_b_nombre: Mapped[str] = mapped_column(String(50))
    clan_b_nivel: Mapped[int]
    clan_b_estrellas: Mapped[int]
    clan_b_destruccion: Mapped[float] = mapped_column(Float)

    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )