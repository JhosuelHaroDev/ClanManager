"""Orquestador híbrido asíncrono en 2 etapas de S.T.A.C.Y. con memoria de corto plazo y telemetría."""

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

# Circuit breaker en memoria para modelos con error 429 (modelo -> timestamp de expiración)
_CIRCUIT_BREAKER_429: dict[str, float] = {}

# ETAPA 1: 1° Gratis ultra rápidos (Groq/NVIDIA) -> 2° Respaldo de pago (Haiku 5.5)
COLA_ENRUTADOR_ETAPA_1 = [
    {"activo": True, "proveedor": "GROQ",      "modelo": "openai/gpt-oss-20b"},
    {"activo": True, "proveedor": "NVIDIA",    "modelo": "meta/llama-4-maverick-17b-128e-instruct"},
    {"activo": True, "proveedor": "GROQ",      "modelo": "meta-llama/llama-4-scout-17b-16e-instruct"},
    {"activo": True, "proveedor": "ANTHROPIC", "modelo": "claude-haiku-5-5"},
]

# ETAPA 2: 1° Gratis potentes (Groq/NVIDIA) -> 2° Respaldo de pago (Sonnet 5.5 / Haiku 5.5)
COLA_REDACTOR_ETAPA_2 = [
    {"activo": True, "proveedor": "GROQ",      "modelo": "openai/gpt-oss-120b"},
    {"activo": True, "proveedor": "GROQ",      "modelo": "meta-llama/llama-4-scout-17b-16e-instruct"},
    {"activo": True, "proveedor": "GROQ",      "modelo": "qwen/qwen3-32b"},
    {"activo": True, "proveedor": "NVIDIA",    "modelo": "meta/llama-4-maverick-17b-128e-instruct"},
    {"activo": True, "proveedor": "ANTHROPIC", "modelo": "claude-sonnet-5-5"},
    {"activo": True, "proveedor": "ANTHROPIC", "modelo": "claude-haiku-5-5"},
]
HERRAMIENTAS_STACY = [
    {
        "name": "consultar_guerra_actual",
        "description": "Consulta los datos de guerra clásica o CWL en PostgreSQL. Soporta 'actual' (en curso/preparación) y 'pasada'. Si no hay guerra activa, devuelve automáticamente la última terminada.",
        "input_schema": {
            "type": "object",
            "properties": {
                "periodo": {"type": "string", "enum": ["actual", "pasada"]},
                "filtro": {"type": "string", "enum": ["todos", "pendientes", "infractores", "plenos", "resumen"]},
                "nombre_jugador": {"type": "string", "description": "Opcional. Nick limpio del jugador."},
                "forzar_actualizacion": {"type": "boolean"},
            },
        },
    },
    {
        "name": "consultar_bases_rivales",
        "description": "Consulta las aldeas del clan enemigo en la guerra 'actual' o 'pasada'.",
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
        "description": "Consulta la tabla de clasificación de los 8 clanes y el rendimiento por rondas de nuestros miembros en la Liga de Guerras de Clanes (CWL).",
        "input_schema": {
            "type": "object",
            "properties": {
                "temporada": {"type": "string", "description": "Opcional. Ej: '2026-10'."},
            },
        },
    },
    {
        "name": "consultar_miembros_heroes",
        "description": "Consulta el Roster Oficial del clan en PostgreSQL: rango, TH, escudo de guerra (IN/OUT), donaciones, estrellas y niveles de los 6 héroes (RB, RA, GC, LR, PE, DD).",
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
        "description": "Petición en tiempo real a Supercell para UN miembro. Úsala SOLO cuando pidan equipamiento activo de héroes, puntos de Juegos del Clan o ataques ganados en temporada.",
        "input_schema": {
            "type": "object",
            "properties": {"nombre_o_tag": {"type": "string"}},
            "required": ["nombre_o_tag"],
        },
    },
    {
        "name": "consultar_asaltos_capital",
        "description": "Consulta el Fin de Semana de Asaltos a la Capital: 'ranking' (oro, 6/6, incompletos, turistas) o 'bitacora' (golpes distrito por distrito, % antes/después).",
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
                "sujeto": {"type": "string", "description": "Nombre del jugador o entidad origen."},
                "tipo_relacion": {
                    "type": "string",
                    "enum": ["CAMBIO_ESPEJO_CON", "TIENE_AUSENCIA_JUSTIFICADA", "ES_CUENTA_SECUNDARIA_DE", "NOTA_TACTICA"],
                },
                "objeto": {"type": "string", "description": "Segundo jugador, motivo de ausencia o cuenta."},
                "nota_explicativa": {"type": "string"},
            },
            "required": ["accion"],
        },
    },
    {
        "name": "consultar_guia_estrategica_coc",
        "description": "Consulta la Biblioteca Táctica Oficial de S.T.A.C.Y. (Octubre 2026).",
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


def _construir_cola_activa(numero_etapa: int) -> list[dict]:
    keys = {
        "ANTHROPIC": settings.anthropic_api_key,
        "GROQ": settings.groq_api_key,
        "NVIDIA": settings.nvidia_api_key,
    }
    base = COLA_ENRUTADOR_ETAPA_1 if numero_etapa == 1 else COLA_REDACTOR_ETAPA_2
    activos = []
    for item in base:
        if not item.get("activo"):
            continue
        prov = item["proveedor"].upper()
        api_key = keys.get(prov)
        if not api_key:
            continue
        if prov == "ANTHROPIC":
            activos.append({
                "nombre": "Anthropic",
                "tipo": "ANTHROPIC",
                "url": "https://api.anthropic.com/v1/messages",
                "api_key": api_key,
                "modelo": item["modelo"],
            })
        elif prov == "GROQ":
            activos.append({
                "nombre": "Groq",
                "tipo": "OPENAI_COMPAT",
                "url": "https://api.groq.com/openai/v1/chat/completions",
                "api_key": api_key,
                "modelo": item["modelo"],
            })
        elif prov == "NVIDIA":
            activos.append({
                "nombre": "NVIDIA",
                "tipo": "OPENAI_COMPAT",
                "url": "https://integrate.api.nvidia.com/v1/chat/completions",
                "api_key": api_key,
                "modelo": item["modelo"],
            })
    return activos


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
    s = re.sub(r"^[-─═_]{3,}$", "━━━━━━━━━━━━", s, flags=re.MULTILINE)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


async def _obtener_memoria_corto_plazo(sesion: AsyncSession, chat_id: str) -> str:
    """Recupera las últimas 4 interacciones del chat en PostgreSQL para dar hilo conversacional."""
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
    lineas = ["[MEMORIA RECIENTE DEL CHAT (Últimos mensajes para contexto)]:"]
    for m in ultimos:
        autor = m.nombre_whatsapp or "Miembro"
        resp_corta = (m.respuesta_stacy or "").split("\n━━━━━━━━━━━━")[0][:220].replace("\n", " ")
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
    """Ejecuta el pipeline híbrido de 2 etapas y devuelve el texto + telemetría."""
    t_inicio = time.monotonic()

    pregunta = re.sub(
        r"(@S\.?T\.?A\.?C\.?Y\.?|@Clan\s*Manager|@" + settings.bot_phone_number + r"|@" + settings.bot_phone_number.lstrip("51") + r")",
        "",
        str(mensaje_usuario or ""),
        flags=re.IGNORECASE,
    ).strip()

    if not pregunta:
        return {
            "respuesta": "⚡ *S.T.A.C.Y. EN LÍNEA*\n\nMis radares en PostgreSQL están operativos para *Melanie Stacy*. Etiquétame junto con tu consulta sobre guerra, aldeas abiertas, héroes, capital, ligas o acuerdos del clan.",
            "nivel_acceso": "GENERAL",
            "jugador_tag": None,
            "modelo_e1": "none",
            "modelo_e2": "none",
            "tools": [],
            "tokens": 0,
            "costo": 0.0,
            "latencia": 0.0,
        }

    perfil = await identificar_miembro_por_telefono(sesion, telefono_remitente)
    if perfil:
        info_g = (
            f" | Posición en Guerra Actual: {perfil['posicion_en_guerra_actual']} "
            f"({perfil['ataques_en_guerra_actual']} tiros, Tiro 1: {perfil['tiro_1_guerra_actual'] or '-'})"
            if perfil["posicion_en_guerra_actual"]
            else " | No convocado o sin guerra activa"
        )
        ctx_remitente = (
            f"[NIVEL DE ACCESO: {perfil['nivel_acceso']}]\n"
            f"[Te escribe el miembro verificado del clan: {perfil['nombre_limpio']} "
            f"(Llámale siempre \"{perfil['nombre_limpio']}\" | Rango: {perfil['rango']}, Tag: {perfil['tag']}, "
            f"TH{perfil['th']}, Escudo: {perfil['escudo_guerra']}, Héroes: {perfil['estado_heroes']}{info_g})]\n"
        )
        nivel_acceso = perfil["nivel_acceso"]
        jugador_tag = perfil["tag"]
    else:
        ctx_remitente = (
            "[NIVEL DE ACCESO: NO VINCULADO]\n"
            f"[Remitente en WhatsApp: {nombre_remitente or 'Usuario'} | Estado: Su teléfono NO figura en `directorio_miembros` (Civil sin rango verificado)]\n"
        )
        nivel_acceso = "NO_VINCULADO"
        jugador_tag = None

    memoria_chat = await _obtener_memoria_corto_plazo(sesion, chat_id)
    prompt_entrada = f"{memoria_chat}{ctx_remitente}Consulta actual del usuario: \"{pregunta}\""

    cola_e1 = _construir_cola_activa(1)
    cola_e2 = _construir_cola_activa(2)
    if not cola_e1 or not cola_e2:
        return {
            "respuesta": "⚠️ *Error de Configuración:* Define al menos una API Key (`ANTHROPIC_API_KEY`, `GROQ_API_KEY` o `NVIDIA_API_KEY`) en tu archivo `.env`.",
            "nivel_acceso": nivel_acceso,
            "jugador_tag": jugador_tag,
            "modelo_e1": "err",
            "modelo_e2": "err",
            "tools": [],
            "tokens": 0,
            "costo": 0.0,
            "latencia": 0.0,
        }

    ahora_ts = time.time()
    historial_saltos = []
    modelo_e1 = "skip"
    tools_usadas = []
    datos_recolectados = []
    tokens_totales = 0
    costo_total = 0.0

    async with httpx.AsyncClient(timeout=25.0) as http_ia:
        # =====================================================================
        # 🔹 ETAPA 1: ENRUTADOR Y SELECTOR DE HERRAMIENTAS
        # =====================================================================
        for prov1 in cola_e1:
            if _CIRCUIT_BREAKER_429.get(prov1["modelo"], 0) > ahora_ts:
                historial_saltos.append(f"E1:{prov1['modelo'].split('/')[-1]}[429]")
                continue

            res1 = await _llamar_enrutador_etapa1(http_ia, prov1, prompt_entrada)
            if res1["exito"]:
                modelo_e1 = prov1["modelo"].split("/")[-1]
                u1 = res1.get("usage") or {}
                tokens_totales += sum(int(u1.get(k) or 0) for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
                costo_total += _calcular_costo_usd(prov1["modelo"], u1)

                for tc in res1.get("tool_calls", []):
                    tools_usadas.append(tc["name"])
                    args_tool = dict(tc.get("args") or {})
                    if perfil and perfil.get("nombre_limpio"):
                        args_tool["_remitente_verificado"] = perfil["nombre_limpio"]
                    salida = await ejecutar_herramienta_stacy(tc["name"], args_tool, sesion, cliente)
                    datos_recolectados.append({
                        "herramienta": tc["name"],
                        "resultado_datos": salida,
                    })
                break

            err1 = str(res1.get("error") or "")
            if "429" in err1:
                _CIRCUIT_BREAKER_429[prov1["modelo"]] = ahora_ts + 60.0
            historial_saltos.append(f"E1:{prov1['modelo'].split('/')[-1]}")

        # =====================================================================
        # 🔹 ETAPA 2: CEREBRO REDACTOR DE S.T.A.C.Y.
        # =====================================================================
        prompt_e2 = prompt_entrada
        if datos_recolectados:
            prompt_e2 += (
                "\n\n[DATOS EN TIEMPO REAL EXTRAÍDOS DE POSTGRESQL]:\n"
                f"{json.dumps(datos_recolectados, ensure_ascii=False)}\n\n"
                "INSTRUCCIÓN: Redacta la respuesta final de S.T.A.C.Y. en ESPAÑOL basándote estrictamente en estos datos, "
                "aplicando tu personalidad nivel 2.5, el Nivel de Acceso del remitente y el formato móvil de WhatsApp."
            )
        else:
            prompt_e2 += (
                "\n\n[NOTA DEL ENRUTADOR: No se requirió consultar tablas para este mensaje. "
                "Responde directamente como S.T.A.C.Y. respetando el Nivel de Acceso del remitente y tu humor 2.5]."
            )

        ultimo_err_e2 = ""
        for prov2 in cola_e2:
            if _CIRCUIT_BREAKER_429.get(prov2["modelo"], 0) > ahora_ts:
                historial_saltos.append(f"E2:{prov2['modelo'].split('/')[-1]}[429]")
                continue

            res2 = await _llamar_redactor_etapa2(http_ia, prov2, prompt_e2)
            if res2["exito"] and res2.get("texto"):
                modelo_e2 = prov2["modelo"].split("/")[-1]
                u2 = res2.get("usage") or {}
                tokens_totales += sum(int(u2.get(k) or 0) for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
                costo_total += _calcular_costo_usd(prov2["modelo"], u2)

                latencia = round(time.monotonic() - t_inicio, 1)
                texto_final = _limpiar_formato_whatsapp(res2["texto"])

                if settings.mostrar_firma_modelo:
                    txt_costo = f" (${costo_total:.4f})" if costo_total > 0 else " ($0 Gratis)"
                    nota_salto = f"\n↪ _Saltó: {', '.join(historial_saltos)}_" if historial_saltos else ""
                    texto_final += (
                        f"\n━━━━━━━━━━━━\n🤖 _S.T.A.C.Y. [{modelo_e1} ➔ {modelo_e2}] • "
                        f"🛠️ {len(tools_usadas)}t • ⏱️ {latencia}s • 🪙 {tokens_totales:,} tok{txt_costo}_{nota_salto}"
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
            if "429" in ultimo_err_e2:
                _CIRCUIT_BREAKER_429[prov2["modelo"]] = ahora_ts + 60.0
            historial_saltos.append(f"E2:{prov2['modelo'].split('/')[-1]}")

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


async def _llamar_enrutador_etapa1(http: httpx.AsyncClient, prov: dict, prompt_entrada: str) -> dict:
    sys_prompt = construir_prompt_enrutador_etapa1()
    if prov["tipo"] == "ANTHROPIC":
        tools_cache = [dict(t) for t in HERRAMIENTAS_STACY]
        tools_cache[-1]["cache_control"] = {"type": "ephemeral"}
        payload: dict = {
            "model": prov["modelo"],
            "max_tokens": 450,
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
            )
            if r.status_code != 200:
                return {"exito": False, "error": f"HTTP {r.status_code}: {r.text[:140]}"}
            data = r.json()
            t_calls = [
                {"id": b["id"], "name": b["name"], "args": b.get("input") or {}}
                for b in data.get("content", [])
                if b.get("type") == "tool_use"
            ]
            return {"exito": True, "tool_calls": t_calls, "usage": data.get("usage")}
        except httpx.HTTPError as e:
            return {"exito": False, "error": str(e)}

    # OpenAI Compatible (Groq / NVIDIA)
    tools_oa = [
        {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
        for t in HERRAMIENTAS_STACY
    ]
    try:
        r = await http.post(
            prov["url"],
            headers={"Authorization": f"Bearer {prov['api_key']}"},
            json={
                "model": prov["modelo"],
                "messages": [{"role": "system", "content": sys_prompt}, {"role": "user", "content": prompt_entrada}],
                "tools": tools_oa,
                "tool_choice": "auto",
                "temperature": 0.1,
                "max_tokens": 450,
            },
        )
        if r.status_code != 200:
            return {"exito": False, "error": f"HTTP {r.status_code}: {r.text[:140]}"}
        data = r.json()
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        t_calls = []
        for tc in msg.get("tool_calls") or []:
            try:
                parsed = json.loads(tc["function"].get("arguments") or "{}")
            except ValueError:
                parsed = {}
            t_calls.append({"id": tc.get("id"), "name": tc["function"]["name"], "args": parsed})
        u = data.get("usage") or {}
        return {
            "exito": True,
            "tool_calls": t_calls,
            "usage": {"input_tokens": u.get("prompt_tokens", 0), "output_tokens": u.get("completion_tokens", 0)},
        }
    except httpx.HTTPError as e:
        return {"exito": False, "error": str(e)}


async def _llamar_redactor_etapa2(http: httpx.AsyncClient, prov: dict, prompt_datos: str) -> dict:
    sys_prompt = construir_prompt_redactor_etapa2()
    if prov["tipo"] == "ANTHROPIC":
        payload: dict = {
            "model": prov["modelo"],
            "max_tokens": 2048,
            "system": [{"type": "text", "text": sys_prompt, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": prompt_datos}],
        }
        if not re.search(r"-5(\b|-|\.)", prov["modelo"]):
            payload["temperature"] = 0.5

        try:
            r = await http.post(
                prov["url"],
                headers={"x-api-key": prov["api_key"], "anthropic-version": "2023-06-01"},
                json=payload,
            )
            if r.status_code != 200:
                return {"exito": False, "error": f"HTTP {r.status_code}: {r.text[:140]}"}
            data = r.json()
            texto = "\n".join(b["text"] for b in data.get("content", []) if b.get("type") == "text" and b.get("text")).strip()
            if not texto:
                return {"exito": False, "error": f"Sin texto ({data.get('stop_reason')})"}
            return {"exito": True, "texto": texto, "usage": data.get("usage")}
        except httpx.HTTPError as e:
            return {"exito": False, "error": str(e)}

    try:
        r = await http.post(
            prov["url"],
            headers={"Authorization": f"Bearer {prov['api_key']}"},
            json={
                "model": prov["modelo"],
                "messages": [{"role": "system", "content": sys_prompt}, {"role": "user", "content": prompt_datos}],
                "temperature": 0.5,
                "max_tokens": 2048,
            },
        )
        if r.status_code != 200:
            return {"exito": False, "error": f"HTTP {r.status_code}: {r.text[:140]}"}
        data = r.json()
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        texto = re.sub(r"<think>[\s\S]*?</think>", "", str(msg.get("content") or ""), flags=re.IGNORECASE).strip()
        if not texto:
            return {"exito": False, "error": "Respuesta vacía en OpenAI-Compat E2"}
        u = data.get("usage") or {}
        return {
            "exito": True,
            "texto": texto,
            "usage": {"input_tokens": u.get("prompt_tokens", 0), "output_tokens": u.get("completion_tokens", 0)},
        }
    except httpx.HTTPError as e:
        return {"exito": False, "error": str(e)}