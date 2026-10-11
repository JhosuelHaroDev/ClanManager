"""Endpoints de la Liga de Guerras de Clanes (CWL)."""

from fastapi import APIRouter

from app.api.dependencias import ClienteClash, SesionBD
from app.config import settings
from app.schemas.guerra_guardada import GuerraResumenOut
from app.schemas.liga import ResumenLigaOut
from app.services import guerras as servicio_guerras
from app.services import liga as servicio_liga
from app.services.clash_client import ClashApiError, normalizar_tag

router = APIRouter(prefix="/liga", tags=["liga"])


@router.get("/resumen")
async def resumen_liga(sesion: SesionBD, temporada: str | None = None) -> ResumenLigaOut:
    """
    Devuelve una temporada de CWL completa a partir de lo que tenemos
    guardado: la clasificación del grupo, las guerras de cada ronda, y el
    desempeño de cada miembro de nuestro clan.

    Sin el parámetro 'temporada' usa la más reciente. Si todavía no hay
    ninguna liga guardada, responde con listas vacías en vez de un error.
    """
    temporada = temporada or await servicio_liga.temporada_mas_reciente(sesion)
    if temporada is None:
        return ResumenLigaOut(
            temporada=None, ronda_actual=None, total_rondas=servicio_liga.TOTAL_RONDAS,
            clasificacion=[], enfrentamientos=[], rondas=[], miembros=[],
        )

    rondas = await servicio_liga.listar_rondas(sesion, temporada)
    enfrentamientos = await servicio_liga.listar_enfrentamientos(sesion, temporada)
    nuestro_tag = normalizar_tag(settings.clan_tag)

    return ResumenLigaOut(
        temporada=temporada,
        ronda_actual=servicio_liga.ronda_actual(enfrentamientos),
        total_rondas=servicio_liga.TOTAL_RONDAS,
        clasificacion=servicio_liga.calcular_clasificacion(enfrentamientos, nuestro_tag),
        enfrentamientos=[servicio_liga.a_enfrentamiento_out(e) for e in enfrentamientos],
        rondas=[GuerraResumenOut.model_validate(r) for r in rondas],
        miembros=servicio_liga.calcular_rendimiento(rondas),
    )


@router.post("/sondeo")
async def sondear_liga(cliente: ClienteClash, sesion: SesionBD) -> dict:
    """
    Dispara manualmente un sondeo de la CWL: consulta el grupo en Supercell
    y guarda todas las guerras de cada ronda ya disponible. Pensado para el
    botón de refresco manual del frontend.
    """
    try:
        resultado = await servicio_guerras.guardar_liga_actual(sesion, cliente)
    except ClashApiError as error:
        # Si el clan no participa en una CWL, Supercell responde 404. Para
        # el botón de refresco eso no es un fallo, solo no hay nada que traer.
        if error.status_code == 404:
            return {"en_liga": False, "guerras_consultadas": 0}
        raise
    return {"en_liga": resultado.en_liga, "guerras_consultadas": resultado.enfrentamientos_consultados}