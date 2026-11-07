# === ARCHIVO: ClanManager\backend\app\services\stacy_ai.py ===
"""Orquestador híbrido con Auto-Descubrimiento de Modelos Vigentes (/v1/models), Balanceador y ReAct."""

import json
import logging
import re
import time

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.stacy import StacyMensajeWhatsapp
from app.services.clash_client import ClashClient
from app.services.stacy_knowledge import (
    construir_prompt_enrutador_etapa1,
    construir_prompt_redactor_etapa2,
)
from app.services.stacy_tools import (
    ejecutar_herramienta_stacy,
    identificar_miembro_por_telefono,
)

logger = logging.getLogger("clanmanager.stacy_ai")

# =============================================================================
# ESTADO EN RAM: CIRCUIT BREAKERS, TELEMETRÍA Y CATÁLOGO AUTO-DESCUBIERTO
# =============================================================================
# _CIRCUIT_BREAKER_429: Bloqueo global (429, 5xx, Timeout, Respuesta vacía)
_CIRCUIT_BREAKER_429: dict[str, float] = {}
# _CIRCUIT_BREAKER_TOOLS_E1: Bloqueo exclusivo para Etapa 1 cuando un modelo falla al usar tools (400)
_CIRCUIT_BREAKER_TOOLS_E1: dict[str, float] = {}
# _MODELOS_DADOS_DE_BAJA: Modelos que respondieron 404 Not Found o 410 Gone (excluidos por 24h)
_MODELOS_DADOS_DE_BAJA: dict[str, float] = {}

_MOTIVO_BLOQUEO: dict[str, str] = {}
_ESTADO_MODELOS: dict[str, dict] = {}

_CATALOGO_DINAMICO: dict[str, list[dict] | float] = {
    "ultima_exploracion_ts": 0.0,
    "etapa_1": [],
    "etapa_2": [],
}

TTL_EXPLORACION_SEGUNDOS = 21600.0  # Re-explorar cada 6 horas automáticamente
MAX_ITERACIONES_ETAPA_1 = 3
UMBRAL_TOKENS_SUAVE_60S = 3800
COOLDOWN_ENTRE_LLAMADAS_SEG = 3.0

# Semillas iniciales por defecto (actualizadas al catálogo real vigente en Groq y NVIDIA)
SEMILLA_ETAPA_1 = [
    {"activo": True, "proveedor": "GROQ",      "modelo": "qwen/qwen3.8-27b"},
    {"activo": True, "proveedor": "GROQ",      "modelo": "openai/gpt-oss-120b"},
    {"activo": True, "proveedor": "NVIDIA",    "modelo": "deepseek-ai/deepseek-v4.1-flash"},
    {"activo": True, "proveedor": "NVIDIA",    "modelo": "mistralai/mistral-large-4-1t-a52b"},
    {"activo": True, "proveedor": "NVIDIA",    "modelo": "moonshotai/kimi-k2.6"},
    {"activo": True, "proveedor": "GROQ",      "modelo": "openai/gpt-oss-20b"},
    {"activo": True, "proveedor": "ANTHROPIC", "modelo": "claude-haiku-5-5"},
]

SEMILLA_ETAPA_2 = [
    {"activo": True, "proveedor": "GROQ",      "modelo": "openai/gpt-oss-120b"},
    {"activo": True, "proveedor": "NVIDIA",    "modelo": "deepseek-ai/deepseek-v4.1-flash"},
    {"activo": True, "proveedor": "GROQ",      "modelo": "qwen/qwen3.8-27b"},
    {"activo": True, "proveedor": "NVIDIA",    "modelo": "mistralai/mistral-large-4-1t-a52b"},
    {"activo": True, "proveedor": "NVIDIA",    "modelo": "moonshotai/kimi-k2.6"},
    {"activo": True, "proveedor": "NVIDIA",    "modelo": "google/gemma-4-31b-it"},
    {"activo": True, "proveedor": "GROQ",      "modelo": "openai/gpt-oss-20b"},
    {"activo": True, "proveedor": "NVIDIA",    "modelo": "nvidia/nemotron-3-super-120b-a12b"},
    {"activo": True, "proveedor": "ANTHROPIC", "modelo": "claude-haiku-5-5"},
    {"activo": True, "proveedor": "ANTHROPIC", "modelo": "claude-sonnet-5-5"},
]

# Ranking de preferencia para filtrar el catálogo de NVIDIA (/v1/models)
PREFERENCIA_NVIDIA_E1 = [
    "deepseek-ai/deepseek-v4.1-flash",
    "mistralai/mistral-large-4-1t-a52b",
    "moonshotai/kimi-k2.6",
    "mistralai/mistral-large-2-instruct",
    "z-ai/glm-5.3-flash",
    "minimaxai/minimax-m3.1-flash",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/llama-3.1-nemotron-70b-instruct",
]

PREFERENCIA_NVIDIA_E2 = [
    "deepseek-ai/deepseek-v4.1-flash",
    "mistralai/mistral-large-4-1t-a52b",
    "moonshotai/kimi-k2.6",
    "google/gemma-4-31b-it",
    "nvidia/nemotron-3-super-120b-a12b",
    "z-ai/glm-5.3-flash",
    "minimaxai/minimax-m3.1-flash",
    "mistralai/mistral-large-2-instruct",
    "nvidia/llama-3.1-nemotron-ultra-253b-v1",
]

PATRONES_EXCLUIDOS_MODELOS = (
    "whisper", "orpheus", "guard", "safeguard", "embed", "reward",
    "parse", "translate", "deplot", "kosmos", "fuyu", "neva", "vila",
    "nvclip", "detector", "calibration", "glimmer", "starcoder",
    "codellama", "codegemma", "llama2", "allam",
)

HERRAMIENTAS_STACY = [
    {
        "name": "consultar_guerra_actual",
        "description": "Consulta y actualiza en tiempo real los datos de guerra en PostgreSQL: 'actual' (en curso/preparación), 'pasada' (última terminada) o 'historial' (las 6+ guerras históricas, estadísticas acumuladas de jugadores o búsqueda por nombre de clan rival).",
        "input_schema": {
            "type": "object",
            "properties": {
                "periodo": {"type": "string", "enum": ["actual", "pasada", "historial"]},
                "filtro": {"type": "string", "enum": ["todos", "pendientes", "infractores", "plenos", "resumen"]},
                "nombre_jugador": {"type": "string", "description": "Opcional. Nick limpio del jugador."},
                "rival": {"type": "string", "description": "Opcional. Nombre parcial del clan rival."},
            },
        },
    },
    {
        "name": "consultar_bases_rivales",
        "description": "Actualiza y consulta las aldeas del clan enemigo en la guerra 'actual' o 'pasada'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "periodo": {"type": "string", "enum": ["actual", "pasada"]},
                "estado": {"type": "string", "enum": ["abiertas", "intactas", "cerradas", "todas"]},
                "th": {"type": "integer"},
            },
        },
    },
    {
        "name": "consultar_cwl_liga",
        "description": "Actualiza y consulta la tabla de clasificación de los 8 clanes y el rendimiento por rondas en CWL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "temporada": {"type": "string", "description": "Opcional. Ej: '2026-10'."},
            },
        },
    },
    {
        "name": "consultar_miembros_heroes",
        "description": "Consulta el Roster Oficial actualizado del clan: rango, TH, escudo de guerra (IN/OUT), donaciones, estrellas y niveles de los 6 héroes (RB, RA, GC, LR, PE, DD).",
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre_jugador": {"type": "string"},
                "th": {"type": "integer"},
                "estado_guerra": {"type": "string", "enum": ["todos", "activos", "rojo"]},
                "rango": {"type": "string", "enum": ["todos", "lider", "colider", "veterano", "miembro"]},
                "ordenar_por": {"type": "string", "enum": ["orden_clan", "mas_rusheados", "mejores_heroes", "mas_donaciones", "mas_estrellas"]},
                "limite": {"type": "integer"},
            },
        },
    },
    {
        "name": "consultar_jugador_en_vivo",
        "description": "Petición directa a Supercell para UN miembro. Úsala cuando pidan equipamiento activo de héroes, puntos de Juegos del Clan o ataques ganados en temporada.",
        "input_schema": {
            "type": "object",
            "properties": {"nombre_o_tag": {"type": "string"}},
            "required": ["nombre_o_tag"],
        },
    },
    {
        "name": "consultar_asaltos_capital",
        "description": "Actualiza y consulta el Fin de Semana de Asaltos a la Capital: 'ranking' (oro, 6/6, incompletos, turistas) o 'bitacora' (golpes distrito por distrito).",
        "input_schema": {
            "type": "object",
            "properties": {
                "tipo_consulta": {"type": "string", "enum": ["ranking", "bitacora"]},
                "filtro": {"type": "string", "enum": ["todos", "sin_atacar", "incompletos", "turistas", "top_oro"]},
                "nombre_jugador": {"type": "string"},
            },
        },
    },
    {
        "name": "consultar_historial_ligas",
        "description": "Consulta el ranking y la evolución semanal de Ligas de Tropas (SUBIO, BAJO, IGUAL) en PostgreSQL.",
        "input_schema": {
            "type": "object",
            "properties": {"nombre_jugador": {"type": "string"}},
        },
    },
    {
        "name": "gestionar_memoria_grafo",
        "description": "Consulta o guarda recuerdos en el Grafo de Memoria de S.T.A.C.Y. (cambios de espejo acordados, ausencias justificadas, cuentas secundarias o notas de liderazgo).",
        "input_schema": {
            "type": "object",
            "properties": {
                "accion": {"type": "string", "enum": ["consultar", "guardar_relaciones"]},
                "sujeto": {"type": "string"},
                "tipo_relacion": {
                    "type": "string",
                    "enum": ["CAMBIO_ESPEJO_CON", "TIENE_AUSENCIA_JUSTIFICADA", "ES_CUENTA_SECUNDARIA_DE", "NOTA_TACTICA"],
                },
                "objeto": {"type": "string"},
                "nota_explicativa": {"type": "string"},
            },
            "required": ["accion"],
        },
    },
    {
        "name": "consultar_guia_estrategica_coc",
        "description": "Consulta la Biblioteca Táctica Oficial de S.T.A.C.Y. (equipamiento meta, ejércitos por TH, Hammer Jam, reglas).",
        "input_schema": {
            "type": "object",
            "properties": {
                "categoria": {
                    "type": "string",
                    "enum": [
                        "heroes_y_equipamiento_meta",
                        "estrategias_ataque_por_th",
                        "economia_y_eventos_2026",
                        "capital_y_modos_clan",
                        "normativa_y_rangos_stacy",
                    ],
                },
            },
            "required": ["categoria"],
        },
    },
    {
        "name": "buscar_en_internet",
        "description": "Búsqueda web en tiempo real sobre novedades de Clash of Clans (TH19, Hammer Jam, parches).",
        "input_schema": {
            "type": "object",
            "properties": {"consulta": {"type": "string"}},
            "required": ["consulta"],
        },
    },
]


# =============================================================================
# EXPLORADOR AUTOMÁTICO DE MODELOS VIGENTES (/v1/models)
# =============================================================================
def _extraer_tamano_billones(model_id: str) -> int:
    """Extrae el tamaño estimado en billones de parámetros (ej. '120b' -> 120) para ordenar."""
    m = re.search(r"(\d+)b\b", model_id.lower())
    if m:
        return int(m.group(1))
    if "1t" in model_id.lower():
        return 1000
    return 25


async def explorar_y_actualizar_modelos_vigentes(forzar: bool = False) -> dict:
    """
    Consulta los catálogos en vivo de Groq y NVIDIA (/v1/models), filtra los modelos
    de texto/herramientas activos y actualiza las colas de Etapa 1 y Etapa 2 en RAM.
    """
    ahora_ts = time.time()
    ultima = float(_CATALOGO_DINAMICO.get("ultima_exploracion_ts") or 0.0)
    if (
        not forzar
        and _CATALOGO_DINAMICO.get("etapa_1")
        and _CATALOGO_DINAMICO.get("etapa_2")
        and (ahora_ts - ultima) < TTL_EXPLORACION_SEGUNDOS
    ):
        return {
            "actualizado": False,
            "etapa_1": len(_CATALOGO_DINAMICO["etapa_1"]),  # type: ignore[arg-type]
            "etapa_2": len(_CATALOGO_DINAMICO["etapa_2"]),  # type: ignore[arg-type]
        }

    groq_e1: list[str] = []
    groq_e2: list[str] = []
    nvidia_e1: list[str] = []
    nvidia_e2: list[str] = []

    async with httpx.AsyncClient(timeout=8.0) as http:
        # 1. Explorar catálogo vivo de GROQ
        if settings.groq_api_key:
            try:
                r_groq = await http.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                )
                if r_groq.status_code == 200:
                    items_groq = r_groq.json().get("data") or []
                    candidatos_g1: list[tuple[int, str]] = []
                    candidatos_g2: list[tuple[int, str]] = []
                    for m in items_groq:
                        m_id = str(m.get("id") or "")
                        m_low = m_id.lower()
                        if not m.get("active", True):
                            continue
                        if any(p in m_low for p in PATRONES_EXCLUIDOS_MODELOS):
                            continue
                        if _MODELOS_DADOS_DE_BAJA.get(m_id, 0) > ahora_ts:
                            continue
                        in_mod = m.get("input_modalities") or ["text"]
                        out_mod = m.get("output_modalities") or ["text"]
                        if "text" not in in_mod or "text" not in out_mod:
                            continue
                        ctx = int(m.get("context_window") or 0)
                        if ctx < 16384:
                            continue

                        features = m.get("supported_features") or []
                        tamano = _extraer_tamano_billones(m_id)

                        # En Etapa 1 priorizar modelos medianos/rápidos con soporte nativo de 'tools'
                        if "tools" in features:
                            peso_e1 = 100 if (24 <= tamano <= 70) else (80 if tamano > 70 else 60)
                            candidatos_g1.append((peso_e1, m_id))

                        # En Etapa 2 priorizar los modelos más grandes para redacción
                        candidatos_g2.append((tamano, m_id))

                    candidatos_g1.sort(key=lambda x: -x[0])
                    candidatos_g2.sort(key=lambda x: -x[0])
                    groq_e1 = [cid for _, cid in candidatos_g1]
                    groq_e2 = [cid for _, cid in candidatos_g2]
            except httpx.HTTPError as e:
                logger.warning("No se pudo explorar /v1/models de Groq: %s", e)

        # 2. Explorar catálogo vivo de NVIDIA NIM
        if settings.nvidia_api_key:
            try:
                r_nv = await http.get(
                    "https://integrate.api.nvidia.com/v1/models",
                    headers={"Authorization": f"Bearer {settings.nvidia_api_key}"},
                )
                if r_nv.status_code == 200:
                    items_nv = r_nv.json().get("data") or []
                    disponibles_nv = {
                        str(m.get("id") or "")
                        for m in items_nv
                        if m.get("id") and _MODELOS_DADOS_DE_BAJA.get(str(m.get("id")), 0) <= ahora_ts
                    }
                    nvidia_e1 = [m for m in PREFERENCIA_NVIDIA_E1 if m in disponibles_nv]
                    nvidia_e2 = [m for m in PREFERENCIA_NVIDIA_E2 if m in disponibles_nv]
            except httpx.HTTPError as e:
                logger.warning("No se pudo explorar /v1/models de NVIDIA: %s", e)

    # 3. Intercalar inteligentemente Groq y NVIDIA para no concentrar ráfagas en un solo proveedor
    nueva_cola_e1: list[dict] = []
    max_len_1 = max(len(groq_e1), len(nvidia_e1))
    for i in range(max_len_1):
        if i < len(groq_e1):
            nueva_cola_e1.append({"activo": True, "proveedor": "GROQ", "modelo": groq_e1[i]})
        if i < len(nvidia_e1):
            nueva_cola_e1.append({"activo": True, "proveedor": "NVIDIA", "modelo": nvidia_e1[i]})

    nueva_cola_e2: list[dict] = []
    max_len_2 = max(len(groq_e2), len(nvidia_e2))
    for i in range(max_len_2):
        if i < len(groq_e2):
            nueva_cola_e2.append({"activo": True, "proveedor": "GROQ", "modelo": groq_e2[i]})
        if i < len(nvidia_e2):
            nueva_cola_e2.append({"activo": True, "proveedor": "NVIDIA", "modelo": nvidia_e2[i]})

    # Si por algún error de red ambas listas quedaron vacías, usar las semillas filtradas
    if not nueva_cola_e1:
        nueva_cola_e1 = [
            x for x in SEMILLA_ETAPA_1
            if x["proveedor"] != "ANTHROPIC" and _MODELOS_DADOS_DE_BAJA.get(x["modelo"], 0) <= ahora_ts
        ]
    if not nueva_cola_e2:
        nueva_cola_e2 = [
            x for x in SEMILLA_ETAPA_2
            if x["proveedor"] != "ANTHROPIC" and _MODELOS_DADOS_DE_BAJA.get(x["modelo"], 0) <= ahora_ts
        ]

    # Agregar el respaldo económico de Anthropic siempre al final
    nueva_cola_e1.append({"activo": True, "proveedor": "ANTHROPIC", "modelo": "claude-haiku-5-5"})
    nueva_cola_e2.append({"activo": True, "proveedor": "ANTHROPIC", "modelo": "claude-haiku-5-5"})
    nueva_cola_e2.append({"activo": True, "proveedor": "ANTHROPIC", "modelo": "claude-sonnet-5-5"})

    _CATALOGO_DINAMICO["ultima_exploracion_ts"] = ahora_ts
    _CATALOGO_DINAMICO["etapa_1"] = nueva_cola_e1
    _CATALOGO_DINAMICO["etapa_2"] = nueva_cola_e2

    logger.info(
        "Catálogo de modelos auto-descubierto: E1=%s | E2=%s",
        [m["modelo"] for m in nueva_cola_e1],
        [m["modelo"] for m in nueva_cola_e2],
    )
    return {
        "actualizado": True,
        "modelos_etapa_1": [f"{m['proveedor']}:{m['modelo']}" for m in nueva_cola_e1],
        "modelos_etapa_2": [f"{m['proveedor']}:{m['modelo']}" for m in nueva_cola_e2],
    }


# =============================================================================
# GESTOR DE CUOTAS EN VENTANA DESLIZANTE (60s) Y CIRCUIT BREAKER SEPARADO
# =============================================================================
def _obtener_estado_modelo(modelo: str) -> dict:
    est = _ESTADO_MODELOS.get(modelo)
    if est is None:
        est = {
            "eventos_tokens": [],
            "ultimo_uso_ts": 0.0,
            "fallos_429_consecutivos": 0,
        }
        _ESTADO_MODELOS[modelo] = est
    return est


def _tokens_consumidos_ultimos_60s(modelo: str, ahora_ts: float) -> int:
    est = _obtener_estado_modelo(modelo)
    corte = ahora_ts - 60.0
    est["eventos_tokens"] = [(ts, tok) for ts, tok in est["eventos_tokens"] if ts >= corte]
    return sum(tok for _, tok in est["eventos_tokens"])


def _registrar_exito_modelo(modelo: str, tokens_usados: int, numero_etapa: int = 2) -> None:
    ahora_ts = time.time()
    est = _obtener_estado_modelo(modelo)
    est["ultimo_uso_ts"] = ahora_ts
    est["fallos_429_consecutivos"] = 0
    if tokens_usados > 0:
        est["eventos_tokens"].append((ahora_ts, tokens_usados))
    _CIRCUIT_BREAKER_429.pop(modelo, None)
    if numero_etapa == 1:
        _CIRCUIT_BREAKER_TOOLS_E1.pop(modelo, None)
    _MOTIVO_BLOQUEO.pop(modelo, None)


def _registrar_fallo_modelo(
    modelo: str,
    error_str: str,
    retry_after: float | None = None,
    numero_etapa: int = 1,
) -> str:
    """
    Clasifica el error y aplica el bloqueo adecuado:
    - 404 / 410: Baja definitiva por 24h + invalida caché de exploración.
    - 400 en Etapa 1: Bloqueo SOLO para Etapa 1 (Tools), dejándolo libre para Etapa 2.
    - 429: Bloqueo global escalonado.
    - 5xx / Timeout / Vacío: Bloqueo corto de 40s.
    """
    ahora_ts = time.time()
    est = _obtener_estado_modelo(modelo)
    err_low = str(error_str or "").lower()

    # 1. Modelo eliminado o deprecado por el proveedor (404 / 410)
    if "404" in err_low or "410" in err_low or "not found" in err_low or "decommissioned" in err_low:
        _MODELOS_DADOS_DE_BAJA[modelo] = ahora_ts + 86400.0
        _CIRCUIT_BREAKER_429[modelo] = ahora_ts + 86400.0
        _MOTIVO_BLOQUEO[modelo] = "Baja"
        # Forzar re-exploración en el siguiente turno
        _CATALOGO_DINAMICO["ultima_exploracion_ts"] = 0.0
        return "Baja"

    # 2. Límite de cuota (429 Rate Limit)
    if "429" in err_low or "rate_limit" in err_low or "rate limit" in err_low:
        est["fallos_429_consecutivos"] += 1
        if retry_after and retry_after > 0:
            enfriamiento = min(max(retry_after, 30.0), 600.0)
        else:
            enfriamiento = 60.0 * min(est["fallos_429_consecutivos"], 5)
        _CIRCUIT_BREAKER_429[modelo] = ahora_ts + enfriamiento
        _MOTIVO_BLOQUEO[modelo] = "429"
        return "429"

    # 3. Error de generación de Tools en Etapa 1 (400): NO bloquear para Etapa 2
    if "400" in err_low:
        if numero_etapa == 1:
            _CIRCUIT_BREAKER_TOOLS_E1[modelo] = ahora_ts + 60.0
            return "400-T"
        _CIRCUIT_BREAKER_429[modelo] = ahora_ts + 30.0
        _MOTIVO_BLOQUEO[modelo] = "400"
        return "400"

    # 4. Respuesta truncada o vacía por exceso de pensamiento
    if "vacía" in err_low or "vacia" in err_low or "sin texto" in err_low or "length" in err_low:
        if numero_etapa == 1:
            _CIRCUIT_BREAKER_TOOLS_E1[modelo] = ahora_ts + 45.0
            return "Len-T"
        _CIRCUIT_BREAKER_429[modelo] = ahora_ts + 40.0
        _MOTIVO_BLOQUEO[modelo] = "Vacío"
        return "Vacío"

    # 5. Timeouts o caídas 5xx del servidor
    if any(k in err_low for k in ("timeout", "timed out", "connecterror", "500", "502", "503", "504")):
        _CIRCUIT_BREAKER_429[modelo] = ahora_ts + 40.0
        _MOTIVO_BLOQUEO[modelo] = "5xx"
        return "5xx"

    _CIRCUIT_BREAKER_429[modelo] = ahora_ts + 25.0
    _MOTIVO_BLOQUEO[modelo] = "Err"
    return "Err"


def _construir_cola_activa(
    numero_etapa: int,
    modelos_usados_consulta: set[str] | None = None,
) -> list[dict]:
    """
    Construye la cola activa a partir del catálogo auto-descubierto y rota los modelos
    gratuitos según su frescura y consumo en los últimos 60 segundos.
    """
    keys = {
        "ANTHROPIC": settings.anthropic_api_key,
        "GROQ": settings.groq_api_key,
        "NVIDIA": settings.nvidia_api_key,
    }
    catalogo_e1 = _CATALOGO_DINAMICO.get("etapa_1") or SEMILLA_ETAPA_1
    catalogo_e2 = _CATALOGO_DINAMICO.get("etapa_2") or SEMILLA_ETAPA_2
    base = catalogo_e1 if numero_etapa == 1 else catalogo_e2  # type: ignore[assignment]

    usados = modelos_usados_consulta or set()
    ahora_ts = time.time()

    gratuitos: list[tuple[float, int, dict]] = []
    pagos: list[dict] = []

    for idx, item in enumerate(base):  # type: ignore[arg-type]
        if not item.get("activo"):
            continue
        prov = item["proveedor"].upper()
        api_key = keys.get(prov)
        if not api_key:
            continue

        modelo = item["modelo"]
        if _MODELOS_DADOS_DE_BAJA.get(modelo, 0) > ahora_ts:
            continue

        if prov == "ANTHROPIC":
            pagos.append({
                "nombre": "Anthropic",
                "tipo": "ANTHROPIC",
                "url": "https://api.anthropic.com/v1/messages",
                "api_key": api_key,
                "modelo": modelo,
                "es_pago": True,
            })
            continue

        cfg = {
            "nombre": "Groq" if prov == "GROQ" else "NVIDIA",
            "tipo": "OPENAI_COMPAT",
            "url": (
                "https://api.groq.com/openai/v1/chat/completions"
                if prov == "GROQ"
                else "https://integrate.api.nvidia.com/v1/chat/completions"
            ),
            "api_key": api_key,
            "modelo": modelo,
            "es_pago": False,
        }

        est = _obtener_estado_modelo(modelo)
        tok_60s = _tokens_consumidos_ultimos_60s(modelo, ahora_ts)
        seg_desde_ultimo = ahora_ts - est["ultimo_uso_ts"]

        penalizacion = 0.0
        if modelo in usados:
            penalizacion += 100.0
        if seg_desde_ultimo < COOLDOWN_ENTRE_LLAMADAS_SEG:
            penalizacion += 50.0
        if tok_60s >= UMBRAL_TOKENS_SUAVE_60S:
            penalizacion += 80.0 + (tok_60s / 1000.0)
        else:
            penalizacion += (tok_60s / 2000.0)

        gratuitos.append((penalizacion, idx, cfg))

    gratuitos.sort(key=lambda x: (x[0], x[1]))
    return [g[2] for g in gratuitos] + pagos


def _resumir_datos_para_react(datos_recolectados: list[dict]) -> list[dict]:
    """Comprime los resultados para la verificación de suficiencia en Rondas 2 y 3."""
    resumenes = []
    for item in datos_recolectados:
        res_original = item.get("resultado_datos")
        if not isinstance(res_original, dict):
            resumenes.append(item)
            continue

        compacto: dict = {}
        for k, v in res_original.items():
            if isinstance(v, list) and len(v) > 3:
                compacto[k] = {
                    "total_filas": len(v),
                    "muestra": v[:2],
                }
            else:
                compacto[k] = v

        resumenes.append({
            "herramienta": item.get("herramienta"),
            "parametros": item.get("parametros"),
            "resumen_resultado": compacto,
        })
    return resumenes


def _calcular_costo_usd(modelo: str, usage: dict | None) -> float:
    if not usage:
        return 0.0
    m = modelo.lower()
    in_tok = int(usage.get("input_tokens") or 0)
    out_tok = int(usage.get("output_tokens") or 0)
    cw_tok = int(usage.get("cache_creation_input_tokens") or 0)
    cr_tok = int(usage.get("cache_read_input_tokens") or 0)

    if "haiku-5-5" in m or "haiku-5.5" in m:
        r_in, r_out, r_cw, r_cr = 0.10, 0.50, 0.125, 0.01
    elif "haiku-4-5" in m or "haiku-4.5" in m:
        r_in, r_out, r_cw, r_cr = 1.00, 5.00, 1.25, 0.10
    elif "sonnet-5" in m:
        r_in, r_out, r_cw, r_cr = 2.00, 10.00, 2.50, 0.10
    elif "sonnet-4" in m:
        r_in, r_out, r_cw, r_cr = 3.00, 15.00, 3.75, 0.30
    else:
        return 0.0

    return ((in_tok * r_in) + (out_tok * r_out) + (cw_tok * r_cw) + (cr_tok * r_cr)) / 1_000_000.0


def _limpiar_formato_whatsapp(texto: str) -> str:
    s = re.sub(r"\*\*(.*?)\*\*", r"*\1*", str(texto or ""))
    s = re.sub(r"^#{1,6}\s*(.+)$", r"▸ *\1*", s, flags=re.MULTILINE)
    s = re.sub(r"\*\*+", "*", s)
    s = re.sub(r"^[ \t]*[-*]\s+", "• ", s, flags=re.MULTILINE)
    s = re.sub(r"^[ \t]*\d+\.\s+", "• ", s, flags=re.MULTILINE)
    s = re.sub(r"^[-─═_]{3,}$", "━━━━━━━━━━━━", s, flags=re.MULTILINE)

    lineas_optimizadas: list[str] = []
    for linea in s.split("\n"):
        if linea.startswith("• ") and len(linea) > 44:
            partes = re.split(r"\s+(?:[–—|]|-(?!\s*>))\s+", linea[2:].strip())
            if len(partes) >= 3:
                encabezado = f"• {partes[0].strip()} • {partes[1].strip()}"
                detalle = " • ".join(p.strip() for p in partes[2:] if p.strip())
                lineas_optimizadas.append(encabezado)
                lineas_optimizadas.append(f"  └ {detalle}")
                continue
        lineas_optimizadas.append(linea)

    s = "\n".join(lineas_optimizadas)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


async def _obtener_memoria_corto_plazo(sesion: AsyncSession, chat_id: str) -> str:
    if not chat_id:
        return ""
    res = await sesion.execute(
        select(StacyMensajeWhatsapp)
        .where(
            StacyMensajeWhatsapp.chat_id == chat_id,
            StacyMensajeWhatsapp.respuesta_stacy.is_not(None),
        )
        .order_by(StacyMensajeWhatsapp.creado_en.desc())
        .limit(4)
    )
    ultimos = list(reversed(res.scalars().all()))
    if not ultimos:
        return ""
    lineas = ["[HISTORIAL RECIENTE DEL CHAT (Solo para contexto de conversación)]:"]
    for m in ultimos:
        autor = m.nombre_whatsapp or "Miembro"
        resp_corta = (m.respuesta_stacy or "").split("\n━━━━━━━━━━━━")[0][:200].replace("\n", " ")
        lineas.append(f"- {autor}: \"{m.mensaje_usuario[:120]}\" -> S.T.A.C.Y.: \"{resp_corta}...\"")
    return "\n".join(lineas) + "\n\n"


async def procesar_consulta_stacy(
    mensaje_usuario: str,
    nombre_remitente: str,
    telefono_remitente: str,
    chat_id: str,
    sesion: AsyncSession,
    cliente: ClashClient,
) -> dict:
    """
    Verifica/explora los modelos vigentes, ejecuta el ciclo ReAct en Etapa 1 rotando
    entre proveedores y redacta la respuesta final en Etapa 2 con un modelo fresco.
    """
    t_inicio = time.monotonic()

    pregunta = re.sub(
        r"(@~?S\.?T\.?A\.?C\.?Y\.?|@" + settings.bot_phone_number + r"|@" + settings.bot_phone_number.lstrip("51") + r")",
        "",
        str(mensaje_usuario or ""),
        flags=re.IGNORECASE,
    ).strip()

    if not pregunta:
        return {
            "respuesta": "⚡ *S.T.A.C.Y. EN LÍNEA*\n\nDime qué necesitas revisar del clan: guerra en vivo, historial, aldeas abiertas, héroes, capital, ligas o acuerdos en memoria.",
            "nivel_acceso": "GENERAL",
            "jugador_tag": None,
            "modelo_e1": "none",
            "modelo_e2": "none",
            "tools": [],
            "tokens": 0,
            "costo": 0.0,
            "latencia": 0.0,
        }

    # Auto-explorar catálogo de modelos activos si el TTL expiró o si algún modelo dio 404/410
    await explorar_y_actualizar_modelos_vigentes()

    perfil = await identificar_miembro_por_telefono(sesion, telefono_remitente)
    if perfil:
        ctx_remitente = (
            f"[NIVEL DE ACCESO: {perfil['nivel_acceso']}]\n"
            f"[Remitente Verificado: {perfil['nombre_limpio']} | Rango en el clan: {perfil['rango']} | "
            f"Tag: {perfil['tag']} | TH{perfil['th']}]\n"
        )
        nivel_acceso = perfil["nivel_acceso"]
        jugador_tag = perfil["tag"]
    else:
        ctx_remitente = (
            "[NIVEL DE ACCESO: NO_VINCULADO]\n"
            f"[Remitente en WhatsApp: {nombre_remitente or 'Usuario'} (Sin número vinculado en el directorio del clan)]\n"
        )
        nivel_acceso = "NO_VINCULADO"
        jugador_tag = None

    memoria_chat = await _obtener_memoria_corto_plazo(sesion, chat_id)
    prompt_base = f"{memoria_chat}{ctx_remitente}Mensaje del usuario: \"{pregunta}\""

    cola_inicial_e1 = _construir_cola_activa(1)
    cola_inicial_e2 = _construir_cola_activa(2)
    if not cola_inicial_e1 or not cola_inicial_e2:
        return {
            "respuesta": "⚠️ *Error de Configuración:* Define al menos una API Key en las variables de entorno.",
            "nivel_acceso": nivel_acceso,
            "jugador_tag": jugador_tag,
            "modelo_e1": "err",
            "modelo_e2": "err",
            "tools": [],
            "tokens": 0,
            "costo": 0.0,
            "latencia": 0.0,
        }

    historial_saltos: list[str] = []
    modelos_usados_consulta: set[str] = set()
    modelos_e1_nombres: list[str] = []
    modelo_e1 = "skip"
    tools_usadas: list[str] = []
    datos_recolectados: list[dict] = []
    firmas_ejecutadas: set[str] = set()
    tokens_totales = 0
    costo_total = 0.0
    iteraciones_e1 = 0

    async with httpx.AsyncClient(timeout=25.0) as http_ia:
        # =====================================================================
        # 🔹 ETAPA 1: BUCLE AGÉNTICO ReAct CON ROTACIÓN ENTRE PROVEEDORES
        # =====================================================================
        for ronda in range(1, MAX_ITERACIONES_ETAPA_1 + 1):
            if ronda == 1:
                prompt_iteracion = prompt_base
            else:
                resumen_ligero = _resumir_datos_para_react(datos_recolectados)
                prompt_iteracion = (
                    f"{prompt_base}\n\n"
                    f"[HERRAMIENTAS YA EJECUTADAS ({len(datos_recolectados)} herramienta(s))]:\n"
                    f"{json.dumps(resumen_ligero, ensure_ascii=False)}\n\n"
                    "[VERIFICACIÓN DE SUFICIENCIA]: Los datos completos de las herramientas anteriores ya están "
                    "listos para la Etapa 2. Si ya cubren lo solicitado por el usuario, NO llames ninguna "
                    "herramienta y responde únicamente: DATOS_COMPLETOS"
                )

            exito_ronda = False
            nuevas_tools_en_ronda = 0
            cola_ronda_e1 = _construir_cola_activa(1, modelos_usados_consulta)

            for prov1 in cola_ronda_e1:
                ahora_ts = time.time()
                m_id = prov1["modelo"]
                nombre_corto = m_id.split("/")[-1]

                if _CIRCUIT_BREAKER_429.get(m_id, 0) > ahora_ts:
                    motivo = _MOTIVO_BLOQUEO.get(m_id, "429")
                    historial_saltos.append(f"E1:{nombre_corto}[{motivo}]")
                    continue
                if _CIRCUIT_BREAKER_TOOLS_E1.get(m_id, 0) > ahora_ts:
                    historial_saltos.append(f"E1:{nombre_corto}[400-T]")
                    continue

                res1 = await _llamar_enrutador_etapa1(http_ia, prov1, prompt_iteracion)
                if res1["exito"]:
                    exito_ronda = True
                    iteraciones_e1 = ronda
                    modelos_usados_consulta.add(m_id)
                    if nombre_corto not in modelos_e1_nombres:
                        modelos_e1_nombres.append(nombre_corto)

                    u1 = res1.get("usage") or {}
                    tok_ronda = sum(
                        int(u1.get(k) or 0)
                        for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
                    )
                    tokens_totales += tok_ronda
                    costo_total += _calcular_costo_usd(m_id, u1)
                    _registrar_exito_modelo(m_id, tok_ronda, numero_etapa=1)

                    tool_calls = res1.get("tool_calls") or []
                    for tc in tool_calls:
                        nombre_fn = tc["name"]
                        args_tool = dict(tc.get("args") or {})
                        firma = f"{nombre_fn}:{json.dumps(args_tool, sort_keys=True, ensure_ascii=False)}"

                        if firma in firmas_ejecutadas:
                            continue
                        firmas_ejecutadas.add(firma)
                        nuevas_tools_en_ronda += 1
                        tools_usadas.append(nombre_fn)

                        if perfil and perfil.get("nombre_limpio"):
                            args_tool["_remitente_verificado"] = perfil["nombre_limpio"]

                        salida = await ejecutar_herramienta_stacy(nombre_fn, args_tool, sesion, cliente)
                        datos_recolectados.append({
                            "herramienta": nombre_fn,
                            "parametros": tc.get("args") or {},
                            "resultado_datos": salida,
                        })
                    break

                etiqueta_err = _registrar_fallo_modelo(
                    m_id,
                    str(res1.get("error") or ""),
                    res1.get("retry_after"),
                    numero_etapa=1,
                )
                historial_saltos.append(f"E1:{nombre_corto}[{etiqueta_err}]")

            # Cortocircuito inteligente: si ya recolectó >= 3 herramientas en paralelo en Ronda 1,
            # o si no pidió más herramientas, pasar directo a la Etapa 2 sin gastar más rondas
            if not exito_ronda or nuevas_tools_en_ronda == 0 or len(datos_recolectados) >= 3:
                break

        if modelos_e1_nombres:
            modelo_e1 = "+".join(modelos_e1_nombres)[:50]

        # =====================================================================
        # 🔹 ETAPA 2: CEREBRO REDACTOR DE S.T.A.C.Y. (CON MODELO FRESCO)
        # =====================================================================
        prompt_e2 = prompt_base
        if datos_recolectados:
            prompt_e2 += (
                "\n\n[DATOS EN TIEMPO REAL EXTRAÍDOS Y VERIFICADOS EN POSTGRESQL / API SUPERCELL]:\n"
                f"{json.dumps(datos_recolectados, ensure_ascii=False)}\n\n"
                "INSTRUCCIÓN DE REDACCIÓN: Responde en ESPAÑOL basándote estrictamente en estos datos verificados. "
                "Sé directa, natural y variada; NO menciones los héroes ni la guerra del remitente salvo que él haya preguntado por sí mismo."
            )
        else:
            prompt_e2 += (
                "\n\n[NOTA: Consulta conversacional que no requirió extraer tablas. "
                "Responde con naturalidad y brevedad como S.T.A.C.Y., sin inventar estadísticas]."
            )

        ultimo_err_e2 = ""
        cola_balanceada_e2 = _construir_cola_activa(2, modelos_usados_consulta)

        for prov2 in cola_balanceada_e2:
            ahora_ts = time.time()
            m_id2 = prov2["modelo"]
            nombre_corto2 = m_id2.split("/")[-1]

            # En Etapa 2 solo importa el bloqueo global (429/5xx/Baja), NO el bloqueo de Tools de E1
            if _CIRCUIT_BREAKER_429.get(m_id2, 0) > ahora_ts:
                motivo = _MOTIVO_BLOQUEO.get(m_id2, "429")
                historial_saltos.append(f"E2:{nombre_corto2}[{motivo}]")
                continue

            res2 = await _llamar_redactor_etapa2(http_ia, prov2, prompt_e2)
            if res2["exito"] and res2.get("texto"):
                modelo_e2 = nombre_corto2[:50]
                u2 = res2.get("usage") or {}
                tok_e2 = sum(
                    int(u2.get(k) or 0)
                    for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
                )
                tokens_totales += tok_e2
                costo_total += _calcular_costo_usd(m_id2, u2)
                _registrar_exito_modelo(m_id2, tok_e2, numero_etapa=2)

                latencia = round(time.monotonic() - t_inicio, 1)
                texto_final = _limpiar_formato_whatsapp(res2["texto"])

                if settings.mostrar_firma_modelo:
                    txt_costo = f" (${costo_total:.4f})" if costo_total > 0 else " ($0 Gratis)"
                    nota_salto = f"\n↪ _Saltó: {', '.join(historial_saltos)}_" if historial_saltos else ""
                    info_tools = f"{len(tools_usadas)}t/{iteraciones_e1}i" if tools_usadas else "0t"
                    texto_final += (
                        f"\n━━━━━━━━━━━━\n🤖 _S.T.A.C.Y. [{modelo_e1} ➔ {modelo_e2}] • "
                        f"🛠️ {info_tools} • ⏱️ {latencia}s • 🪙 {tokens_totales:,} tok{txt_costo}_{nota_salto}"
                    )

                return {
                    "respuesta": texto_final,
                    "nivel_acceso": nivel_acceso,
                    "jugador_tag": jugador_tag,
                    "modelo_e1": modelo_e1,
                    "modelo_e2": modelo_e2,
                    "tools": tools_usadas,
                    "tokens": tokens_totales,
                    "costo": costo_total,
                    "latencia": latencia,
                }

            ultimo_err_e2 = str(res2.get("error") or "Error E2")
            etiqueta_err2 = _registrar_fallo_modelo(
                m_id2,
                ultimo_err_e2,
                res2.get("retry_after"),
                numero_etapa=2,
            )
            historial_saltos.append(f"E2:{nombre_corto2}[{etiqueta_err2}]")

    return {
        "respuesta": f"❌ *Error temporal en los motores de S.T.A.C.Y.:* {ultimo_err_e2}",
        "nivel_acceso": nivel_acceso,
        "jugador_tag": jugador_tag,
        "modelo_e1": modelo_e1,
        "modelo_e2": "fail",
        "tools": tools_usadas,
        "tokens": tokens_totales,
        "costo": costo_total,
        "latencia": round(time.monotonic() - t_inicio, 1),
    }


def _extraer_retry_after(headers: httpx.Headers) -> float | None:
    val = headers.get("retry-after")
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _rescatar_tool_calls_de_texto(texto_crudo: str) -> list[dict]:
    """
    Si un modelo OpenAI-Compat devuelve el JSON de la herramienta en content o en
    failed_generation (error 400 tool_use_failed), lo rescata sin perder la llamada.
    """
    nombres_validos = {t["name"] for t in HERRAMIENTAS_STACY}
    rescatadas: list[dict] = []

    for match in re.finditer(r"\{[\s\S]*?\}", texto_crudo):
        bloque = match.group(0)
        try:
            obj = json.loads(bloque)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        nombre = obj.get("name") or obj.get("function") or obj.get("tool")
        args = obj.get("arguments") or obj.get("parameters") or obj.get("args") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        if nombre in nombres_validos and isinstance(args, dict):
            rescatadas.append({"id": f"resc_{len(rescatadas)}", "name": nombre, "args": args})

    return rescatadas


async def _llamar_enrutador_etapa1(http: httpx.AsyncClient, prov: dict, prompt_entrada: str) -> dict:
    sys_prompt = construir_prompt_enrutador_etapa1()
    modelo_low = prov["modelo"].lower()

    if prov["tipo"] == "ANTHROPIC":
        tools_cache = [dict(t) for t in HERRAMIENTAS_STACY]
        tools_cache[-1]["cache_control"] = {"type": "ephemeral"}
        payload: dict = {
            "model": prov["modelo"],
            "max_tokens": 1024,
            "system": [{"type": "text", "text": sys_prompt, "cache_control": {"type": "ephemeral"}}],
            "tools": tools_cache,
            "messages": [{"role": "user", "content": prompt_entrada}],
        }
        if not re.search(r"-5(\b|-|\.)", prov["modelo"]):
            payload["temperature"] = 0.1

        try:
            r = await http.post(
                prov["url"],
                headers={"x-api-key": prov["api_key"], "anthropic-version": "2023-06-01"},
                json=payload,
                timeout=22.0,
            )
            if r.status_code != 200:
                return {
                    "exito": False,
                    "error": f"HTTP {r.status_code}: {r.text[:160]}",
                    "retry_after": _extraer_retry_after(r.headers),
                }
            data = r.json()
            t_calls = [
                {"id": b["id"], "name": b["name"], "args": b.get("input") or {}}
                for b in data.get("content", [])
                if b.get("type") == "tool_use"
            ]
            return {"exito": True, "tool_calls": t_calls, "usage": data.get("usage")}
        except httpx.HTTPError as e:
            return {"exito": False, "error": f"Timeout/HTTP: {e}"}

    prompt_usuario = f"{prompt_entrada}\n\n/no_think" if "qwen" in modelo_low else prompt_entrada

    tools_oa = [
        {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
        for t in HERRAMIENTAS_STACY
    ]
    # Solo se envían los parámetros estándar soportados en supported_sampling_parameters
    payload_oa: dict = {
        "model": prov["modelo"],
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": prompt_usuario},
        ],
        "tools": tools_oa,
        "tool_choice": "auto",
        "temperature": 0.1,
        "max_tokens": 1024,
    }

    try:
        r = await http.post(
            prov["url"],
            headers={"Authorization": f"Bearer {prov['api_key']}"},
            json=payload_oa,
            timeout=14.0,
        )
        if r.status_code != 200:
            # Si fue un 400 tool_use_failed de Groq con failed_generation, intentar rescatar el JSON
            if r.status_code == 400 and "failed_generation" in r.text:
                rescatadas = _rescatar_tool_calls_de_texto(r.text)
                if rescatadas:
                    return {
                        "exito": True,
                        "tool_calls": rescatadas,
                        "usage": {"input_tokens": 600, "output_tokens": 120},
                    }
            return {
                "exito": False,
                "error": f"HTTP {r.status_code}: {r.text[:160]}",
                "retry_after": _extraer_retry_after(r.headers),
            }

        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        finish_reason = str(choice.get("finish_reason") or "")

        t_calls = []
        for tc in msg.get("tool_calls") or []:
            try:
                parsed = json.loads(tc["function"].get("arguments") or "{}")
            except ValueError:
                parsed = {}
            t_calls.append({"id": tc.get("id"), "name": tc["function"]["name"], "args": parsed})

        contenido_crudo = str(msg.get("content") or "")
        if not t_calls and contenido_crudo:
            t_calls = _rescatar_tool_calls_de_texto(contenido_crudo)

        contenido_limpio = re.sub(r"<think>[\s\S]*?</think>", "", contenido_crudo, flags=re.IGNORECASE).strip()
        if not t_calls and finish_reason == "length" and not contenido_limpio:
            return {"exito": False, "error": "Respuesta truncada por length en pensamiento E1"}

        u = data.get("usage") or {}
        return {
            "exito": True,
            "tool_calls": t_calls,
            "usage": {"input_tokens": u.get("prompt_tokens", 0), "output_tokens": u.get("completion_tokens", 0)},
        }
    except httpx.HTTPError as e:
        return {"exito": False, "error": f"Timeout/HTTP: {e}"}


async def _llamar_redactor_etapa2(http: httpx.AsyncClient, prov: dict, prompt_datos: str) -> dict:
    sys_prompt = construir_prompt_redactor_etapa2()
    modelo_low = prov["modelo"].lower()

    if prov["tipo"] == "ANTHROPIC":
        payload: dict = {
            "model": prov["modelo"],
            "max_tokens": 3000,
            "system": [{"type": "text", "text": sys_prompt, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": prompt_datos}],
        }
        if not re.search(r"-5(\b|-|\.)", prov["modelo"]):
            payload["temperature"] = 0.6

        try:
            r = await http.post(
                prov["url"],
                headers={"x-api-key": prov["api_key"], "anthropic-version": "2023-06-01"},
                json=payload,
                timeout=25.0,
            )
            if r.status_code != 200:
                return {
                    "exito": False,
                    "error": f"HTTP {r.status_code}: {r.text[:160]}",
                    "retry_after": _extraer_retry_after(r.headers),
                }
            data = r.json()
            texto = "\n".join(
                b["text"] for b in data.get("content", []) if b.get("type") == "text" and b.get("text")
            ).strip()
            if not texto:
                return {"exito": False, "error": f"Sin texto ({data.get('stop_reason')})"}
            return {"exito": True, "texto": texto, "usage": data.get("usage")}
        except httpx.HTTPError as e:
            return {"exito": False, "error": f"Timeout/HTTP: {e}"}

    prompt_usuario = f"{prompt_datos}\n\n/no_think" if "qwen" in modelo_low else prompt_datos

    payload_oa: dict = {
        "model": prov["modelo"],
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": prompt_usuario},
        ],
        "temperature": 0.6,
        "max_tokens": 3000,
    }

    try:
        r = await http.post(
            prov["url"],
            headers={"Authorization": f"Bearer {prov['api_key']}"},
            json=payload_oa,
            timeout=16.0,
        )
        if r.status_code != 200:
            return {
                "exito": False,
                "error": f"HTTP {r.status_code}: {r.text[:160]}",
                "retry_after": _extraer_retry_after(r.headers),
            }
        data = r.json()
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        raw_content = str(msg.get("content") or "")
        texto = re.sub(r"<think>[\s\S]*?</think>", "", raw_content, flags=re.IGNORECASE)
        texto = re.sub(r"<think>[\s\S]*$", "", texto, flags=re.IGNORECASE).strip()

        if not texto:
            return {"exito": False, "error": "Respuesta vacía en OpenAI-Compat E2"}
        u = data.get("usage") or {}
        return {
            "exito": True,
            "texto": texto,
            "usage": {"input_tokens": u.get("prompt_tokens", 0), "output_tokens": u.get("completion_tokens", 0)},
        }
    except httpx.HTTPError as e:
        return {"exito": False, "error": f"Timeout/HTTP: {e}"}