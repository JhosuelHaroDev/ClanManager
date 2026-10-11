"""Endpoints de la Liga de Guerras de Clanes (CWL)."""

from fastapi import APIRouter

from app.api.dependencias import ClienteClash, SesionBD
from app.schemas.guerra_guardada import GuerraResumenOut
from app.schemas.liga import ResumenLigaOut
from app.services import guerras as servicio_guerras
from app.services import liga as servicio_liga
from app.services.clash_client import ClashApiError

router = APIRouter(prefix="/liga", tags=["liga"])


@router.get("/resumen")
async def resumen_liga(sesion: SesionBD, temporada: str | None = None) -> ResumenLigaOut:
    """
    Devuelve las rondas de una temporada de CWL y el desempeño de cada
    miembro, a partir de lo que tenemos guardado.

    Sin el parámetro 'temporada' usa la más reciente. Si todavía no hay
    ninguna liga guardada, responde con listas vacías en vez de un error.
    """
    temporada = temporada or await servicio_liga.temporada_mas_reciente(sesion)
    if temporada is None:
        return ResumenLigaOut(temporada=None, rondas=[], miembros=[])

    rondas = await servicio_liga.listar_rondas(sesion, temporada)
    return ResumenLigaOut(
        temporada=temporada,
        rondas=[GuerraResumenOut.model_validate(r) for r in rondas],
        miembros=servicio_liga.calcular_rendimiento(rondas),
    )


@router.post("/sondeo")
async def sondear_liga(cliente: ClienteClash, sesion: SesionBD) -> dict:
    """
    Dispara manualmente un sondeo de la CWL: consulta el grupo en Supercell
    y guarda o actualiza cada ronda ya disponible. Pensado para el botón
    de refresco manual del frontend.
    """
    try:
        guardadas = await servicio_guerras.guardar_liga_actual(sesion, cliente)
    except ClashApiError as error:
        # Si el clan no participa en una CWL, Supercell responde 404. Para
        # el botón de refresco eso no es un fallo, solo no hay nada que traer.
        if error.status_code == 404:
            return {"en_liga": False, "rondas_guardadas": 0}
        raise
    return {"en_liga": bool(guardadas), "rondas_guardadas": len(guardadas)}