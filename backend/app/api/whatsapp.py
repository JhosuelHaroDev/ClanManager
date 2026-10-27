"""Endpoints del Webhook de WhatsApp (Green-API), Simulador de S.T.A.C.Y. y Directorio."""

import asyncio
import logging

import httpx
from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.api.dependencias import ClienteClash, SesionBD
from app.config import settings
from app.db.sesion import FabricaSesion
from app.models.stacy import DirectorioMiembro, StacyMensajeWhatsapp
from app.services.clash_client import ClashClient, normalizar_tag
from app.services.stacy_ai import procesar_consulta_stacy
from app.services.migracion_pdfs import consolidar_y_migrar_todo

logger = logging.getLogger("clanmanager.whatsapp")

router = APIRouter(prefix="/whatsapp", tags=["whatsapp - S.T.A.C.Y."])

# Semáforo asíncrono global para evitar colisiones de llamadas simultáneas al LLM
_SEMAFORO_IA = asyncio.Lock()


class ConsultaSimuladorIn(BaseModel):
    mensaje: str = "¿Cómo vamos en la guerra actual?"
    telefono_remitente: str = "922809482"
    nombre_remitente: str = "Jhadzel"
    chat_id: str = "simulador_local@g.us"


class RegistroTelefonoIn(BaseModel):
    tag: str
    nombre: str
    whatsapp_telefono: str
    strikes_acumulados: int = 0


@router.get("/webhook")
async def verificar_webhook() -> dict:
    """Endpoint GET de verificación del Webhook de S.T.A.C.Y."""
    return {"status": "ok", "bot": "S.T.A.C.Y. v3.0 (FastAPI + PostgreSQL) activa"}


@router.post("/simular")
async def simular_consulta_stacy(
    datos: ConsultaSimuladorIn,
    sesion: SesionBD,
    cliente: ClienteClash,
) -> dict:
    """
    Simulador interactivo para probar a S.T.A.C.Y. desde Swagger UI (/docs)
    sin necesidad de enviar mensajes por WhatsApp.
    """
    resultado = await procesar_consulta_stacy(
        mensaje_usuario=datos.mensaje,
        nombre_remitente=datos.nombre_remitente,
        telefono_remitente=datos.telefono_remitente,
        chat_id=datos.chat_id,
        sesion=sesion,
        cliente=cliente,
    )
    return resultado


@router.post("/directorio")
async def vincular_telefono_miembro(
     registros: list[RegistroTelefonoIn],
    sesion: SesionBD,
) -> dict:
    """Registra o actualiza los números de WhatsApp vinculados al #TAG en PostgreSQL."""
    actualizados = 0
    for item in registros:
        tag_norm = normalizar_tag(item.tag)
        res = await sesion.execute(
            select(DirectorioMiembro).where(DirectorioMiembro.tag == tag_norm)
        )
        fila = res.scalar_one_or_none()
        if fila is None:
            fila = DirectorioMiembro(tag=tag_norm, nombre=item.nombre)
            sesion.add(fila)
        fila.nombre = item.nombre
        fila.whatsapp_telefono = item.whatsapp_telefono.strip()
        fila.strikes_acumulados = item.strikes_acumulados
        actualizados += 1

    await sesion.commit()
    return {"status": "ok", "miembros_vinculados": actualizados}

@router.get("/directorio")
async def exportar_directorio_miembros(sesion: SesionBD) -> list[RegistroTelefonoIn]:
    """Exporta la lista actual de teléfonos vinculados para respaldar o migrar a Railway."""
    res = await sesion.execute(
        select(DirectorioMiembro).order_by(DirectorioMiembro.nombre)
    )
    filas = res.scalars().all()
    return [
        RegistroTelefonoIn(
            tag=f.tag,
            nombre=f.nombre,
            whatsapp_telefono=f.whatsapp_telefono or "",
            strikes_acumulados=f.strikes_acumulados,
        )
        for f in filas
    ]

@router.post("/consolidar-historial")
async def ejecutar_consolidacion_y_migracion_pdfs(
    sesion: SesionBD,
    cliente: ClienteClash,
) -> dict:
    """
    Ejecuta el Primer Pase de Consolidación y migra a PostgreSQL las 6 Guerras
    Clásicas históricas y las 2 temporadas de Asaltos a la Capital de los PDFs.
    Es 100% idempotente (no duplica registros si se ejecuta más de una vez).
    """
    return await consolidar_y_migrar_todo(sesion, cliente)

@router.post("/vincular-webhook")
async def configurar_webhook_green_api(url_publica_base: str) -> dict:
    """
    Vincula automáticamente el Webhook de Green-API con el dominio de Railway.
    Ejemplo de url_publica_base: https://clanmanager-production.up.railway.app
    """
    if not settings.green_api_token:
        return {"error": "Falta configurar GREEN_API_TOKEN en las variables de entorno."}

    base = url_publica_base.rstrip("/")
    webhook_url = base if base.endswith("/api/whatsapp/webhook") else f"{base}/api/whatsapp/webhook"

    url = f"{settings.green_api_url}/waInstance{settings.green_id_instance}/setSettings/{settings.green_api_token}"
    payload = {
        "webhookUrl": webhook_url,
        "webhookUrlToken": "",
        "delaySendMessagesMilliseconds": 500,
        "markIncomingMessagesReaded": "yes",
        "incomingWebhook": "yes",
        "outgoingWebhook": "no",
        "outgoingMessageWebhook": "no",
        "outgoingAPIMessageWebhook": "no",
        "stateWebhook": "no",
        "deviceWebhook": "no",
    }

    async with httpx.AsyncClient(timeout=15.0) as http:
        res = await http.post(url, json=payload)
        return {
            "status_code": res.status_code,
            "webhook_configurado": webhook_url,
            "respuesta_green_api": res.json() if res.status_code == 200 else res.text,
        }


@router.post("/webhook")
async def recibir_webhook_green_api(
    request: Request,
    background_tasks: BackgroundTasks,
    sesion: SesionBD,
) -> dict:
    """
    Endpoint POST principal para Green-API.
    Verifica idempotencia en PostgreSQL en <15ms y delega el procesamiento a segundo plano.
    """
    try:
        body = await request.json()
    except Exception:
        return {"status": "ok", "detail": "Invalid JSON"}

    if body.get("typeWebhook") != "incomingMessageReceived":
        return {"status": "ok", "detail": "Ignored webhook type"}

    id_message = str(body.get("idMessage") or "").strip()
    if not id_message:
        return {"status": "ok", "detail": "Missing idMessage"}

    sender_data = body.get("senderData") or {}
    message_data = body.get("messageData") or {}

    chat_id = str(sender_data.get("chatId") or "")
    sender = str(sender_data.get("sender") or "")
    sender_name = str(sender_data.get("senderName") or sender_data.get("senderContactName") or "Miembro")

    if settings.bot_phone_number in sender:
        return {"status": "ok", "detail": "Ignored self message"}

    if not chat_id.endswith("@g.us"):
        return {"status": "ok", "detail": "Ignored private chat"}

    if settings.allowed_group_id:
        permitidos = [g.strip() for g in settings.allowed_group_id.split(",") if g.strip()]
        if permitidos and chat_id not in permitidos:
            return {"status": "ok", "detail": "Ignored unauthorized group"}

    texto, mencionados = _extraer_texto_y_menciones(message_data)
    if not texto or not _fue_mencionada_stacy(texto, mencionados):
        return {"status": "ok", "detail": "Bot not mentioned"}

    # Escudo de idempotencia en PostgreSQL
    existente = await sesion.get(StacyMensajeWhatsapp, id_message)
    if existente is not None:
        return {"status": "ok", "detail": f"Duplicate ignored: {id_message}"}

    nuevo_msg = StacyMensajeWhatsapp(
        id_message_wa=id_message,
        chat_id=chat_id,
        telefono_remitente=sender,
        nombre_whatsapp=sender_name,
        nivel_acceso_aplicado="PROCESANDO",
        mensaje_usuario=texto,
    )
    sesion.add(nuevo_msg)
    await sesion.commit()

    cliente_clash: ClashClient = request.app.state.clash
    background_tasks.add_task(
        _procesar_y_responder_whatsapp,
        id_message=id_message,
        chat_id=chat_id,
        sender=sender,
        sender_name=sender_name,
        texto=texto,
        cliente_clash=cliente_clash,
    )

    return {"status": "ok", "detail": "Queued for processing"}


async def _procesar_y_responder_whatsapp(
    id_message: str,
    chat_id: str,
    sender: str,
    sender_name: str,
    texto: str,
    cliente_clash: ClashClient,
) -> None:
    """Tarea en segundo plano que ejecuta la IA, responde por Green-API y guarda la telemetría."""
    async with _SEMAFORO_IA:
        await _enviar_estado_escribiendo(chat_id, 4000)

        async with FabricaSesion() as sesion:
            resultado = await procesar_consulta_stacy(
                mensaje_usuario=texto,
                nombre_remitente=sender_name,
                telefono_remitente=sender,
                chat_id=chat_id,
                sesion=sesion,
                cliente=cliente_clash,
            )

            registro = await sesion.get(StacyMensajeWhatsapp, id_message)
            if registro:
                registro.respuesta_stacy = resultado["respuesta"]
                registro.nivel_acceso_aplicado = resultado["nivel_acceso"]
                registro.jugador_tag_vinculado = resultado["jugador_tag"]
                registro.modelo_etapa_1 = resultado["modelo_e1"]
                registro.modelo_etapa_2 = resultado["modelo_e2"]
                registro.herramientas_usadas = resultado["tools"]
                registro.tokens_totales = resultado["tokens"]
                registro.costo_total_usd = resultado["costo"]
                registro.latencia_segundos = resultado["latencia"]
                await sesion.commit()

        if resultado.get("respuesta"):
            await _enviar_mensaje_whatsapp(chat_id, resultado["respuesta"], id_message)


def _extraer_texto_y_menciones(message_data: dict) -> tuple[str, list[str]]:
    tipo = message_data.get("typeMessage")
    texto = ""
    mencionados: list[str] = []

    if tipo == "textMessage" and message_data.get("textMessageData"):
        texto = message_data["textMessageData"].get("textMessage") or ""
    elif tipo in ("extendedTextMessage", "quotedMessage") and message_data.get("extendedTextMessageData"):
        ext = message_data["extendedTextMessageData"]
        texto = ext.get("text") or ""
        mencionados = ext.get("mentionedJid") or []
    elif message_data.get("fileMessageData"):
        f_data = message_data["fileMessageData"]
        texto = f_data.get("caption") or ""
        mencionados = f_data.get("mentionedJid") or []

    return str(texto).strip(), (mencionados if isinstance(mencionados, list) else [])


def _fue_mencionada_stacy(texto: str, mencionados: list[str]) -> bool:
    t_low = texto.lower()
    bot_jid = f"{settings.bot_phone_number}@c.us"
    num_corto = settings.bot_phone_number.lstrip("51")

    # 1. Si seleccionaron a Stacy de la lista desplegable con "@" en WhatsApp
    if bot_jid in mencionados:
        return True
    # 2. Si escribieron manualmente @Stacy o @S.T.A.C.Y.
    if any(alias in t_low for alias in ("@stacy", "@s.t.a.c.y")):
        return True
    # 3. Respaldo cuando WhatsApp convierte la mención de contacto en @51922982880
    if f"@{settings.bot_phone_number}" in t_low or f"@{num_corto}" in t_low:
        return True
    return False


async def _enviar_mensaje_whatsapp(chat_id: str, texto: str, quoted_id: str | None = None) -> bool:
    if not settings.green_api_token:
        logger.warning("GREEN_API_TOKEN no configurado; se omite envío a WhatsApp.")
        return False

    url = f"{settings.green_api_url}/waInstance{settings.green_id_instance}/sendMessage/{settings.green_api_token}"
    payload = {"chatId": chat_id, "message": texto}
    if quoted_id:
        payload["quotedMessageId"] = quoted_id

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            res = await http.post(url, json=payload)
            return res.status_code == 200
    except httpx.HTTPError as e:
        logger.error("Error enviando mensaje a Green-API: %s", e)
        return False


async def _enviar_estado_escribiendo(chat_id: str, duracion_ms: int = 4000) -> None:
    if not settings.green_api_token or not chat_id:
        return
    url = f"{settings.green_api_url}/waInstance{settings.green_id_instance}/sendTyping/{settings.green_api_token}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            await http.post(url, json={"chatId": chat_id, "typingTime": duracion_ms})
    except httpx.HTTPError:
        pass