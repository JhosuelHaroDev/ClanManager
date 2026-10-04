"""Endpoint con el resumen general del clan."""

from fastapi import APIRouter

from app.api.dependencias import ClienteClash
from app.schemas.clan import ClanOut

router = APIRouter(prefix="/clan", tags=["clan"])


@router.get("")
async def obtener_resumen_clan(cliente: ClienteClash) -> ClanOut:
    """Devuelve los datos generales del clan, consultados en vivo a Supercell."""
    datos = await cliente.obtener_clan()
    return ClanOut.desde_api(datos)