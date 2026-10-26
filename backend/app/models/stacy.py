"""Modelos del cerebro de S.T.A.C.Y.: directorio de WhatsApp, grafo de memoria y telemetría."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DirectorioMiembro(Base):
    """
    Registro persistente de identidad y contacto de un miembro del clan.

    A diferencia de CapturaMiembro (que es una foto histórica), esta tabla
    mantiene el vínculo permanente entre el #TAG de Supercell, su número de
    WhatsApp y sus advertencias (strikes) vigentes.
    """

    __tablename__ = "directorio_miembros"

    tag: Mapped[str] = mapped_column(String(20), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(60), index=True)
    whatsapp_telefono: Mapped[str | None] = mapped_column(
        String(25), unique=True, index=True
    )
    strikes_acumulados: Mapped[int] = mapped_column(Integer, default=0)
    notas_liderazgo: Mapped[str | None] = mapped_column(Text)
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StacyNodoMemoria(Base):
    """
    Un nodo dentro del Grafo de Memoria de S.T.A.C.Y.

    Puede representar a un jugador ('JUGADOR'), una cuenta secundaria
    ('CUENTA_SECUNDARIA'), un motivo de ausencia ('AUSENCIA') o un acuerdo
    táctico ('ACUERDO').
    """

    __tablename__ = "stacy_nodos_memoria"

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo_nodo: Mapped[str] = mapped_column(String(30), index=True)
    referencia_tag: Mapped[str | None] = mapped_column(String(20), index=True)
    nombre_entidad: Mapped[str] = mapped_column(String(80), index=True)
    propiedades: Mapped[dict | None] = mapped_column(JSONB)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class StacyAristaGrafo(Base):
    """
    Una relación dirigida (Sujeto -> Relación -> Objeto) en el Grafo de Memoria.

    Ejemplos de tipo_relacion:
    - 'CAMBIO_ESPEJO_CON' (entre dos jugadores para una guerra específica)
    - 'ES_CUENTA_SECUNDARIA_DE' (entre dos cuentas del clan)
    - 'TIENE_AUSENCIA_JUSTIFICADA' (entre un jugador y un motivo temporal)
    - 'RECIBIO_STRIKE_POR' (registro disciplinario)
    """

    __tablename__ = "stacy_aristas_grafo"

    id: Mapped[int] = mapped_column(primary_key=True)
    nodo_origen_id: Mapped[int] = mapped_column(
        ForeignKey("stacy_nodos_memoria.id", ondelete="CASCADE"), index=True
    )
    tipo_relacion: Mapped[str] = mapped_column(String(40), index=True)
    nodo_destino_id: Mapped[int] = mapped_column(
        ForeignKey("stacy_nodos_memoria.id", ondelete="CASCADE"), index=True
    )
    guerra_id: Mapped[int | None] = mapped_column(
        ForeignKey("guerras.id", ondelete="SET NULL"), index=True
    )
    registrado_por: Mapped[str | None] = mapped_column(String(60))
    nota_explicativa: Mapped[str | None] = mapped_column(Text)
    es_activa: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expira_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    nodo_origen: Mapped["StacyNodoMemoria"] = relationship(
        foreign_keys=[nodo_origen_id]
    )
    nodo_destino: Mapped["StacyNodoMemoria"] = relationship(
        foreign_keys=[nodo_destino_id]
    )


class StacyMensajeWhatsapp(Base):
    """
    Historial conversacional de corto plazo, escudo de idempotencia y
    telemetría de costos del pipeline híbrido de S.T.A.C.Y.
    """

    __tablename__ = "stacy_mensajes_whatsapp"

    id_message_wa: Mapped[str] = mapped_column(String(60), primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(50), index=True)
    telefono_remitente: Mapped[str] = mapped_column(String(25))
    nombre_whatsapp: Mapped[str | None] = mapped_column(String(60))
    jugador_tag_vinculado: Mapped[str | None] = mapped_column(
        String(20), index=True
    )
    nivel_acceso_aplicado: Mapped[str] = mapped_column(String(25))

    mensaje_usuario: Mapped[str] = mapped_column(Text)
    respuesta_stacy: Mapped[str | None] = mapped_column(Text)

    modelo_etapa_1: Mapped[str | None] = mapped_column(String(50))
    modelo_etapa_2: Mapped[str | None] = mapped_column(String(50))
    herramientas_usadas: Mapped[list | None] = mapped_column(JSONB)
    tokens_totales: Mapped[int] = mapped_column(Integer, default=0)
    costo_total_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latencia_segundos: Mapped[float] = mapped_column(Float, default=0.0)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )