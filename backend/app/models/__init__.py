"""
Paquete de modelos.

Importar los modelos aquí garantiza que queden registrados en
Base.metadata cuando Alembic ejecuta `import app.models`.
"""

from app.models.asalto import AsaltoAtaque, AsaltoCapital, AsaltoDistrito, AsaltoMiembro, AsaltoRegistro
from app.models.captura import Captura, CapturaMiembro
from app.models.guerra import Guerra, GuerraAtaque, GuerraMiembro
from app.models.liga import LigaEnfrentamiento
from app.models.stacy import (
    DirectorioMiembro,
    StacyAristaGrafo,
    StacyMensajeWhatsapp,
    StacyNodoMemoria,
)

__all__ = [
    "AsaltoAtaque", "AsaltoCapital", "AsaltoDistrito", "AsaltoMiembro", "AsaltoRegistro",
    "Captura", "CapturaMiembro", "Guerra", "GuerraAtaque", "GuerraMiembro",
    "LigaEnfrentamiento",
    "DirectorioMiembro", "StacyNodoMemoria", "StacyAristaGrafo", "StacyMensajeWhatsapp",
]