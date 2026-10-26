"""integrar stacy y auditoria de 5 horas

Revision ID: e8f1a2b3c4d5
Revises: dd4e69da0e33
Create Date: 2026-10-26 01:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e8f1a2b3c4d5'
down_revision: Union[str, Sequence[str], None] = 'dd4e69da0e33'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Nuevas columnas en tablas existentes
    op.add_column('capturas_miembros', sa.Column('preferencia_guerra', sa.String(length=10), nullable=True))
    op.add_column('capturas_miembros', sa.Column('estrellas_guerra', sa.Integer(), nullable=True))
    op.add_column('guerras', sa.Column('max_orden_5h', sa.Integer(), nullable=True))

    # 2. Tabla de directorio permanente de miembros (WhatsApp + Strikes)
    op.create_table(
        'directorio_miembros',
        sa.Column('tag', sa.String(length=20), nullable=False),
        sa.Column('nombre', sa.String(length=60), nullable=False),
        sa.Column('whatsapp_telefono', sa.String(length=25), nullable=True),
        sa.Column('strikes_acumulados', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('notas_liderazgo', sa.Text(), nullable=True),
        sa.Column('actualizado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('tag'),
    )
    op.create_index(op.f('ix_directorio_miembros_nombre'), 'directorio_miembros', ['nombre'], unique=False)
    op.create_index(op.f('ix_directorio_miembros_whatsapp_telefono'), 'directorio_miembros', ['whatsapp_telefono'], unique=True)

    # 3. Tabla de Nodos del Grafo de Memoria de S.T.A.C.Y.
    op.create_table(
        'stacy_nodos_memoria',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tipo_nodo', sa.String(length=30), nullable=False),
        sa.Column('referencia_tag', sa.String(length=20), nullable=True),
        sa.Column('nombre_entidad', sa.String(length=80), nullable=False),
        sa.Column('propiedades', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('creado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_stacy_nodos_memoria_nombre_entidad'), 'stacy_nodos_memoria', ['nombre_entidad'], unique=False)
    op.create_index(op.f('ix_stacy_nodos_memoria_referencia_tag'), 'stacy_nodos_memoria', ['referencia_tag'], unique=False)
    op.create_index(op.f('ix_stacy_nodos_memoria_tipo_nodo'), 'stacy_nodos_memoria', ['tipo_nodo'], unique=False)

    # 4. Tabla de Aristas del Grafo de Memoria de S.T.A.C.Y.
    op.create_table(
        'stacy_aristas_grafo',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nodo_origen_id', sa.Integer(), nullable=False),
        sa.Column('tipo_relacion', sa.String(length=40), nullable=False),
        sa.Column('nodo_destino_id', sa.Integer(), nullable=False),
        sa.Column('guerra_id', sa.Integer(), nullable=True),
        sa.Column('registrado_por', sa.String(length=60), nullable=True),
        sa.Column('nota_explicativa', sa.Text(), nullable=True),
        sa.Column('es_activa', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('creado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expira_en', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['guerra_id'], ['guerras.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['nodo_destino_id'], ['stacy_nodos_memoria.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['nodo_origen_id'], ['stacy_nodos_memoria.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_stacy_aristas_grafo_es_activa'), 'stacy_aristas_grafo', ['es_activa'], unique=False)
    op.create_index(op.f('ix_stacy_aristas_grafo_guerra_id'), 'stacy_aristas_grafo', ['guerra_id'], unique=False)
    op.create_index(op.f('ix_stacy_aristas_grafo_nodo_destino_id'), 'stacy_aristas_grafo', ['nodo_destino_id'], unique=False)
    op.create_index(op.f('ix_stacy_aristas_grafo_nodo_origen_id'), 'stacy_aristas_grafo', ['nodo_origen_id'], unique=False)
    op.create_index(op.f('ix_stacy_aristas_grafo_tipo_relacion'), 'stacy_aristas_grafo', ['tipo_relacion'], unique=False)

    # 5. Tabla de Historial de WhatsApp y Telemetría Híbrida
    op.create_table(
        'stacy_mensajes_whatsapp',
        sa.Column('id_message_wa', sa.String(length=60), nullable=False),
        sa.Column('chat_id', sa.String(length=50), nullable=False),
        sa.Column('telefono_remitente', sa.String(length=25), nullable=False),
        sa.Column('nombre_whatsapp', sa.String(length=60), nullable=True),
        sa.Column('jugador_tag_vinculado', sa.String(length=20), nullable=True),
        sa.Column('nivel_acceso_aplicado', sa.String(length=25), nullable=False),
        sa.Column('mensaje_usuario', sa.Text(), nullable=False),
        sa.Column('respuesta_stacy', sa.Text(), nullable=True),
        sa.Column('modelo_etapa_1', sa.String(length=50), nullable=True),
        sa.Column('modelo_etapa_2', sa.String(length=50), nullable=True),
        sa.Column('herramientas_usadas', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('tokens_totales', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('costo_total_usd', sa.Float(), nullable=False, server_default='0'),
        sa.Column('latencia_segundos', sa.Float(), nullable=False, server_default='0'),
        sa.Column('creado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id_message_wa'),
    )
    op.create_index(op.f('ix_stacy_mensajes_whatsapp_chat_id'), 'stacy_mensajes_whatsapp', ['chat_id'], unique=False)
    op.create_index(op.f('ix_stacy_mensajes_whatsapp_creado_en'), 'stacy_mensajes_whatsapp', ['creado_en'], unique=False)
    op.create_index(op.f('ix_stacy_mensajes_whatsapp_jugador_tag_vinculado'), 'stacy_mensajes_whatsapp', ['jugador_tag_vinculado'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_stacy_mensajes_whatsapp_jugador_tag_vinculado'), table_name='stacy_mensajes_whatsapp')
    op.drop_index(op.f('ix_stacy_mensajes_whatsapp_creado_en'), table_name='stacy_mensajes_whatsapp')
    op.drop_index(op.f('ix_stacy_mensajes_whatsapp_chat_id'), table_name='stacy_mensajes_whatsapp')
    op.drop_table('stacy_mensajes_whatsapp')

    op.drop_index(op.f('ix_stacy_aristas_grafo_tipo_relacion'), table_name='stacy_aristas_grafo')
    op.drop_index(op.f('ix_stacy_aristas_grafo_nodo_origen_id'), table_name='stacy_aristas_grafo')
    op.drop_index(op.f('ix_stacy_aristas_grafo_nodo_destino_id'), table_name='stacy_aristas_grafo')
    op.drop_index(op.f('ix_stacy_aristas_grafo_guerra_id'), table_name='stacy_aristas_grafo')
    op.drop_index(op.f('ix_stacy_aristas_grafo_es_activa'), table_name='stacy_aristas_grafo')
    op.drop_table('stacy_aristas_grafo')

    op.drop_index(op.f('ix_stacy_nodos_memoria_tipo_nodo'), table_name='stacy_nodos_memoria')
    op.drop_index(op.f('ix_stacy_nodos_memoria_referencia_tag'), table_name='stacy_nodos_memoria')
    op.drop_index(op.f('ix_stacy_nodos_memoria_nombre_entidad'), table_name='stacy_nodos_memoria')
    op.drop_table('stacy_nodos_memoria')

    op.drop_index(op.f('ix_directorio_miembros_whatsapp_telefono'), table_name='directorio_miembros')
    op.drop_index(op.f('ix_directorio_miembros_nombre'), table_name='directorio_miembros')
    op.drop_table('directorio_miembros')

    op.drop_column('guerras', 'max_orden_5h')
    op.drop_column('capturas_miembros', 'estrellas_guerra')
    op.drop_column('capturas_miembros', 'preferencia_guerra')