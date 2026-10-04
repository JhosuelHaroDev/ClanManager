"""Endpoints relacionados con las guerras de clanes."""

from fastapi import APIRouter, HTTPException, Query

from app.api.dependencias import ClienteClash, SesionBD
from app.schemas.guerra import GuerraActualOut, GuerraRegistroOut
from app.schemas.guerra_guardada import GuerraDetalleOut, GuerraResumenOut
from app.services import guerras as servicio_guerras

router = APIRouter(prefix="/guerras", tags=["guerras"])


@router.get("/actual")
async def guerra_actual(cliente: ClienteClash) -> GuerraActualOut:
    """
    Devuelve la guerra clásica en curso, consultada en vivo a Supercell.

    Si el clan no está en guerra en este momento, el resultado trae
    estado "notInWar" y el resto de los campos en null.
    """
    datos = await cliente.obtener_guerra_actual()
    return GuerraActualOut.desde_api(datos)

@router.post("/actual")
async def sondear_guerra_actual(cliente: ClienteClash, sesion: SesionBD) -> dict:
    """
    Dispara manualmente un sondeo de la guerra actual: la consulta a
    Supercell y la guarda o actualiza en el historial, igual que hace el
    programador automático. Pensado para el botón de refresco manual del
    frontend.
    """
    guerra = await servicio_guerras.guardar_guerra_actual(sesion, cliente)
    return {"guardada": guerra is not None}

@router.get("/registro")
async def registro_guerras(
    cliente: ClienteClash, limite: int = Query(default=10, ge=1, le=50)
) -> list[GuerraRegistroOut]:
    """
    Devuelve el historial resumido de guerras pasadas.

    Requiere que el clan tenga su registro de guerra en público; si está
    privado, Supercell responde con error y esta llamada falla con un 502.
    """
    datos = await cliente.obtener_registro_guerras(limite)
    return GuerraRegistroOut.lista_desde_api(datos)

@router.get("/historial")
async def listar_guerras(
    sesion: SesionBD, limite: int = Query(default=20, ge=1, le=200)
) -> list[GuerraResumenOut]:
    """Devuelve las guerras guardadas por nuestro propio programador, de la más reciente a la más antigua."""
    guerras = await servicio_guerras.listar_guerras(sesion, limite)
    return [GuerraResumenOut.model_validate(g) for g in guerras]


@router.get("/historial/{guerra_id}")
async def obtener_guerra(guerra_id: int, sesion: SesionBD) -> GuerraDetalleOut:
    """Devuelve el detalle de una guerra guardada, con sus miembros y ataques."""
    guerra = await servicio_guerras.obtener_guerra(sesion, guerra_id)
    if guerra is None:
        raise HTTPException(status_code=404, detail="Guerra no encontrada")
    return GuerraDetalleOut.model_validate(guerra)