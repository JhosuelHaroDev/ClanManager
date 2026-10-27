"""Servicio de consolidación inicial y migración histórica de los 8 PDFs (6 Guerras + 2 Asaltos)."""

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.asalto import (
    AsaltoAtaque,
    AsaltoCapital,
    AsaltoDistrito,
    AsaltoMiembro,
    AsaltoRegistro,
)
from app.models.captura import Captura
from app.models.guerra import Guerra, GuerraAtaque, GuerraMiembro
from app.models.stacy import DirectorioMiembro
from app.schemas.asalto import AsaltoOut
from app.services import asaltos as servicio_asaltos
from app.services import capturas as servicio_capturas
from app.services import guerras as servicio_guerras
from app.services.clash_client import ClashApiError, ClashClient, normalizar_tag

logger = logging.getLogger("clanmanager.migracion_pdfs")


def _tag_sintetico(prefijo: str, texto: str) -> str:
    h = hashlib.md5(texto.encode("utf-8")).hexdigest()[:8].upper()
    return f"#{prefijo}{h}"


# =============================================================================
# DATOS ESTRUCTURADOS EXTRAÍDOS DE LOS 6 PDFs DE GUERRAS CLÁSICAS
# Formato de cada miembro propio:
# (pos, nick, th, def_pct, def_stars, t1_pos, t1_pct, t1_stars, t2_pos, t2_pct, t2_stars, riv_nick, riv_th, riv_pct, riv_stars, inf_t1, inf_t2)
# =============================================================================
GUERRAS_PDF_HISTORICAS = [
    {
        "war_id": "WAR-20261014-1703",
        "inicio_iso": "2026-10-14T21:42:18Z",
        "tamano": 30,
        "clan_estrellas": 82,
        "clan_destruccion": 96.70,
        "clan_ataques": 48,
        "rival_nombre": "อเวจีสีชมพู™",
        "rival_estrellas": 87,
        "rival_destruccion": 98.33,
        "max_orden_5h": 50,
        "filas": [
            (1, "Castro", 18, 100, 3, 6, 100, 3, 2, 100, 3, "ขวด น้ำ", 18, 100, 3, False, False),
            (2, "leyenda negra", 18, 100, 3, 4, 82, 2, 5, 100, 3, "บริส บิ๊", 18, 100, 3, False, False),
            (3, "Johan 2025", 18, 100, 3, 3, 100, 3, 1, 100, 3, "superget", 18, 100, 3, False, False),
            (4, "⭐Void Gaster s⭐", 17, 100, 3, 7, 100, 3, 4, 93, 2, "are_tee28", 18, 93, 2, False, False),
            (5, "mofii", 17, 94, 2, 10, 100, 3, 5, 92, 1, "[pingpong::]", 17, 100, 3, False, False),
            (6, "alex", 17, 60, 2, 11, 100, 3, 4, 93, 2, "Boat2", 17, 100, 3, False, False),
            (7, "JR☆", 16, 100, 3, 15, 100, 3, 18, 100, 3, "เพื่อหนุ่ม", 17, 100, 3, False, False),
            (8, "alexitoo", 16, 100, 3, 8, 100, 3, 14, 100, 3, "yongsouvandy@gm", 16, 100, 3, False, False),
            (9, "ZELDRIS", 16, 100, 3, 9, 100, 3, 10, 89, 2, "P Tan 125", 16, 100, 3, False, False),
            (10, "albert", 15, 90, 2, 16, 100, 3, 10, 99, 2, "Auing", 15, 100, 3, False, False),
            (11, "electron3000", 15, 100, 3, None, 0, 0, None, 0, 0, "chocolate", 15, 100, 3, False, False),
            (12, "Manu", 15, 100, 3, 13, 97, 2, 12, 99, 2, "นาพ", 15, 100, 3, False, False),
            (13, "EdbEyond", 15, 100, 3, 12, 100, 3, 13, 97, 2, "ไดโนเสาร์ฟันหลอ", 16, 97, 2, False, False),
            (14, "chong", 15, 100, 3, None, 0, 0, None, 0, 0, "นักรบ", 16, 100, 3, False, False),
            (15, "kaweexz", 15, 100, 3, None, 0, 0, None, 0, 0, "หมูล้วน", 15, 100, 3, False, False),
            (16, "Jhadzel", 15, 100, 3, 23, 100, 3, 19, 100, 3, "Armza24", 15, 100, 3, False, False),
            (17, "xedrick", 15, 100, 3, 30, 100, 3, 25, 68, 1, "LiF.Noisily", 15, 92, 2, False, False),
            (18, "David", 15, 100, 3, None, 0, 0, None, 0, 0, "เทพ", 15, 100, 3, False, False),
            (19, "gregory03", 15, 100, 3, None, 0, 0, None, 0, 0, "Lego", 15, 100, 3, False, False),
            (20, "luisitoborr", 15, 100, 3, 24, 68, 2, 20, 88, 2, "Bam", 15, 88, 2, False, False),
            (21, "GÁRFIO", 15, 100, 3, 20, 62, 2, 21, 100, 3, "FAITH CL", 15, 100, 3, False, False),
            (22, "Ezequiel", 14, 100, 3, None, 0, 0, None, 0, 0, "Ton", 15, 100, 3, False, False),
            (23, "Arturo Diaz $$$", 14, 100, 3, 26, 88, 2, 23, 94, 2, "bena", 14, 94, 2, True, False),
            (24, "Eduardo", 15, 100, 3, 17, 91, 2, 22, 100, 3, "อป", 14, 68, 2, False, False),
            (25, "Aimar 342", 14, 100, 3, 25, 58, 1, 19, 48, 1, "เจ้าชาย ราตรี", 14, 100, 3, False, False),
            (26, "CALAMAR", 14, 100, 3, 29, 100, 3, 26, 63, 1, "SIN", 14, 88, 2, False, False),
            (27, "Canela", 13, 100, 3, 27, 100, 3, 28, 89, 1, "ນະ ເດມາ", 13, 100, 3, False, False),
            (28, "Jø$U", 13, 100, 3, 28, 74, 2, 29, 98, 2, "FREE DOM", 13, 89, 2, False, False),
            (29, "johan", 13, 100, 3, 29, 97, 2, 28, 82, 2, "tan", 13, 100, 3, False, False),
            (30, "NAT.GM", 12, 100, 3, 30, 69, 1, 28, 5, 0, "MaiNPK", 12, 100, 3, False, False),
        ],
    },
    {
        "war_id": "WAR-20261016-1726",
        "inicio_iso": "2026-10-16T22:26:11Z",
        "tamano": 25,
        "clan_estrellas": 75,
        "clan_destruccion": 100.00,
        "clan_ataques": 40,
        "rival_nombre": "زرقاء اليمامة ❤",
        "rival_estrellas": 51,
        "rival_destruccion": 76.44,
        "max_orden_5h": 50,
        "filas": [
            (1, "Castro", 18, 64, 2, 1, 100, 3, 14, 100, 3, "أبو محمد", 18, 100, 3, False, False),
            (2, "leyenda negra", 18, 57, 2, 1, 77, 2, 6, 100, 3, "mahmoud", 18, 100, 3, False, False),
            (3, "Johan 2025", 18, 0, 0, 1, 100, 3, 10, 100, 3, "Romeo", 17, 100, 3, False, False),
            (4, "⭐Void Gaster s⭐", 17, 0, 0, 3, 100, 3, 4, 100, 3, "محمود الشرف", 17, 100, 3, True, False),
            (5, "mofii", 17, 0, 0, 5, 100, 3, 2, 100, 3, "Rival #5", 17, 100, 3, False, False),
            (6, "alex", 17, 0, 0, None, 0, 0, None, 0, 0, "SHADOW", 16, 100, 3, False, False),
            (7, "Edith", 16, 95, 2, 7, 87, 2, None, 0, 0, "mir3cle", 16, 100, 3, False, False),
            (8, "alexitoo", 16, 76, 2, 8, 100, 3, 9, 100, 3, "مايسترو", 16, 100, 3, False, False),
            (9, "ZELDRIS", 16, 69, 2, 9, 100, 3, 7, 100, 3, "القبضة الحديدية", 16, 100, 3, False, False),
            (10, "Sekooo", 15, 85, 2, None, 0, 0, None, 0, 0, "شرارة", 16, 100, 3, False, False),
            (11, "Manu", 15, 93, 2, 11, 100, 3, 16, 88, 2, "أمير العذاب", 16, 100, 3, False, False),
            (12, "EdbEyond", 15, 80, 2, 12, 100, 3, 10, 94, 2, "hseen alhmeed", 16, 100, 3, False, False),
            (13, "Jhadzel", 15, 100, 3, 16, 100, 3, 13, 100, 3, "جبريل", 15, 100, 3, False, False),
            (14, "xedrick", 15, 97, 2, 25, 100, 3, 19, 77, 2, "The general 2", 15, 100, 3, True, False),
            (15, "AQUILES", 15, 100, 3, 14, 87, 2, 13, 100, 3, "قلوب عالمه", 15, 100, 3, False, False),
            (16, "GÁRFIO", 15, 100, 3, 16, 81, 2, 15, 59, 2, "زيد احمد", 15, 100, 3, False, False),
            (17, "luisitoborr", 15, 100, 3, None, 0, 0, None, 0, 0, "ملك كلاش و", 15, 100, 3, False, False),
            (18, "Arturo Diaz $$$", 14, 100, 3, 18, 100, 3, 15, 100, 3, "İTACHI", 14, 100, 3, False, False),
            (19, "Aimar 342", 14, 100, 3, None, 0, 0, None, 0, 0, "غمبر", 14, 100, 3, False, False),
            (20, "CALAMAR", 14, 99, 2, 19, 100, 3, 17, 100, 3, "Rival #20", 14, 100, 3, False, False),
            (21, "Canela", 13, 100, 3, 21, 100, 3, 20, 100, 3, "سوسو", 15, 100, 3, False, False),
            (22, "Jø$U", 13, 100, 3, 22, 100, 3, 21, 55, 2, "Layan", 14, 100, 3, False, False),
            (23, "johan", 13, 100, 3, 23, 100, 3, 20, 87, 1, "Rival #23", 13, 100, 3, False, False),
            (24, "NAT.GM", 12, 100, 3, 24, 100, 3, None, 0, 0, "الينا", 12, 100, 3, False, False),
            (25, "werex", 7, 100, 3, 25, 61, 2, 24, 2, 0, "جرة", 11, 100, 3, False, False),
        ],
    },
    {
        "war_id": "WAR-20261018-1720",
        "inicio_iso": "2026-10-18T22:20:49Z",
        "tamano": 35,
        "clan_estrellas": 93,
        "clan_destruccion": 92.40,
        "clan_ataques": 50,
        "rival_nombre": "مملكه الاصدقاء",
        "rival_estrellas": 99,
        "rival_destruccion": 95.83,
        "max_orden_5h": 50,
        "filas": [
            (1, "Castro", 18, 100, 3, 2, 82, 2, 5, 68, 2, "موسى الجبوري", 18, 78, 2, True, False),
            (2, "leyenda negra", 18, 100, 3, 1, 78, 2, 6, 100, 3, "اللاعب", 18, 82, 2, False, False),
            (3, "Johan 2025", 18, 100, 3, 3, 100, 3, 5, 100, 3, "RashaGyan", 18, 100, 3, False, False),
            (4, "⭐Void Gaster s⭐", 17, 47, 1, 7, 100, 3, 9, 100, 3, "Abo Ra'ad", 17, 100, 3, False, False),
            (5, "alex", 17, 54, 1, 5, 91, 2, 16, 100, 3, "محمد", 16, 100, 3, False, False),
            (6, "mofii", 17, 57, 1, 4, 100, 3, 14, 100, 3, "ابن العراق", 16, 100, 3, False, False),
            (7, "Edith", 16, 100, 3, 7, 77, 2, 15, 80, 2, "الراشد", 16, 100, 3, False, False),
            (8, "JR☆", 16, 29, 0, 21, 100, 3, 19, 87, 2, "مدير أمن الدولة", 16, 100, 3, False, False),
            (9, "alexitoo", 16, 100, 3, 9, 92, 2, 8, 100, 3, "OMAR & Alrasam", 16, 100, 3, False, False),
            (10, "AT€NEA", 16, 100, 3, 10, 63, 2, 21, 81, 2, "شيل الموصل", 16, 100, 3, False, False),
            (11, "ZELDRIS", 16, 100, 3, 11, 100, 3, 10, 100, 3, "Mustafa Ab Gad", 16, 100, 3, False, False),
            (12, "FullEwok", 15, 100, 3, 12, 100, 3, 16, 88, 2, "طف", 16, 100, 3, False, False),
            (13, "Choreguapo", 15, 100, 3, 22, 100, 3, 17, 81, 2, "تذكار", 16, 100, 3, True, True),
            (14, "Tony", 15, 100, 3, None, 0, 0, None, 0, 0, "ابو على", 16, 100, 3, False, False),
            (15, "DANIEL GM", 15, 100, 3, 23, 100, 3, 25, 100, 3, "السلطان", 16, 100, 3, False, False),
            (16, "kaiser", 15, 100, 3, 27, 100, 3, 29, 100, 3, "mohamed", 15, 100, 3, False, False),
            (17, "Sekooo", 15, 100, 3, None, 0, 0, None, 0, 0, "الساعة", 15, 81, 2, False, False),
            (18, "❤️RONNIE❤️", 15, 100, 3, 18, 86, 2, 20, 80, 2, "khalilo", 15, 86, 2, False, False),
            (19, "Manu", 16, 100, 3, 19, 92, 2, 35, 100, 3, "tawfeek", 15, 92, 2, False, False),
            (20, "『W』『A』『S』『O』『N』", 15, 100, 3, None, 0, 0, None, 0, 0, "BMW", 15, 80, 2, False, False),
            (21, "Joel", 15, 100, 3, 21, 46, 1, 28, 67, 2, "nabulsi", 15, 100, 3, False, False),
            (22, "Jhadzel", 15, 100, 3, 13, 100, 3, 15, 100, 3, "Mohamed", 15, 100, 3, False, False),
            (23, "bryanxD", 15, 100, 3, None, 0, 0, None, 0, 0, "saggadv♡♡", 15, 100, 3, False, False),
            (24, "GÁRFIO", 15, 97, 2, 24, 100, 3, 34, 100, 3, "نصرات", 15, 100, 3, False, False),
            (25, "aliens 17 》", 15, 100, 3, None, 0, 0, None, 0, 0, "mahmoud", 15, 100, 3, False, False),
            (26, "AQUILES", 15, 100, 3, 26, 85, 2, None, 0, 0, "GOGO", 15, 85, 2, False, False),
            (27, "el mejor", 15, 100, 3, None, 0, 0, None, 0, 0, "زينب", 15, 100, 3, False, False),
            (28, "Eduardo", 16, 100, 3, None, 0, 0, None, 0, 0, "على", 15, 67, 2, False, False),
            (29, "CALAMAR", 14, 100, 3, None, 0, 0, None, 0, 0, "momen", 15, 100, 3, False, False),
            (30, "Canela", 13, 100, 3, 30, 97, 2, 33, 70, 2, "IRAQ", 15, 97, 2, False, False),
            (31, "Jø$U", 13, 100, 3, 33, 51, 1, 31, 56, 2, "ليالي القمر", 15, 56, 2, False, False),
            (32, "RUSSO_HN", 15, 100, 3, None, 0, 0, None, 0, 0, "غرام @@", 15, 65, 2, False, False),
            (33, "johan", 13, 100, 3, 33, 68, 2, 32, 65, 2, "hussein alyasry", 14, 70, 2, False, False),
            (34, "NAT.GM", 12, 100, 3, 34, 66, 2, None, 0, 0, "Chrysalis", 14, 100, 3, False, False),
            (35, "werex", 7, 100, 3, 35, 18, 0, 34, 3, 0, "ماليه", 13, 100, 3, False, False),
        ],
    },
    {
        "war_id": "WAR-20261020-1722",
        "inicio_iso": "2026-10-20T22:22:24Z",
        "tamano": 25,
        "clan_estrellas": 74,
        "clan_destruccion": 99.76,
        "clan_ataques": 46,
        "rival_nombre": "Clash Addicts",
        "rival_estrellas": 48,
        "rival_destruccion": 77.04,
        "max_orden_5h": 50,
        "filas": [
            (1, "Castro", 18, 72, 2, 2, 81, 2, 7, 100, 3, "APEX KILLER", 18, 94, 2, False, False),
            (2, "leyenda negra", 18, 56, 2, 1, 74, 2, 9, 100, 3, "Sawnik", 18, 100, 3, False, False),
            (3, "Johan 2025", 18, 0, 0, 3, 100, 3, 2, 100, 3, "heypiggeh", 18, 100, 3, False, False),
            (4, "⭐Void Gaster s⭐", 17, 81, 2, 4, 100, 3, 11, 100, 3, "deiu", 17, 100, 3, False, False),
            (5, "mofii", 17, 72, 2, 5, 100, 3, 11, 69, 2, "cannonballer", 17, 100, 3, False, False),
            (6, "alex", 17, 64, 2, 6, 100, 3, 1, 94, 2, "DHURVESH", 17, 100, 3, False, False),
            (7, "Edith", 16, 94, 2, 7, 85, 2, None, 0, 0, "darus", 16, 100, 3, False, False),
            (8, "alexitoo", 16, 79, 2, 8, 100, 3, 7, 98, 2, "Rocky Bhai", 16, 100, 3, False, True),
            (9, "ZELDRIS", 16, 64, 2, 9, 85, 2, 8, 97, 2, "panku", 16, 100, 3, False, False),
            (10, "Manu", 16, 74, 2, 10, 100, 3, 12, 100, 3, "fyren olsef", 16, 100, 3, False, False),
            (11, "THE RICAX", 16, 87, 2, 16, 90, 2, 14, 68, 2, "Lomo", 16, 100, 3, False, False),
            (12, "mateo.coronel", 16, 69, 2, 12, 35, 0, 15, 67, 2, "rock on", 15, 100, 3, False, False),
            (13, "Choreguapo", 15, 90, 2, 13, 100, 3, None, 0, 0, "pat", 17, 100, 3, False, False),
            (14, "Alejandromm11", 15, 80, 2, 24, 100, 3, None, 0, 0, "BANSALJI", 15, 100, 3, False, False),
            (15, "DANIEL GM", 15, 49, 1, 15, 100, 3, 14, 100, 3, "MD Rashed", 15, 100, 3, False, False),
            (16, "A NefTwi A", 15, 32, 0, 1, 74, 1, 16, 100, 3, "you", 15, 100, 3, False, False),
            (17, "EdbEyond", 15, 77, 2, 17, 100, 3, 12, 91, 2, "Femjem", 15, 100, 3, False, False),
            (18, "Jhadzel", 15, 89, 2, 18, 100, 3, 16, 100, 3, "alojannat", 16, 100, 3, False, False),
            (19, "ZoroRoronoa", 15, 97, 2, 19, 100, 3, None, 0, 0, "mirza", 14, 100, 3, False, False),
            (20, "Arturo Diaz $$$", 14, 100, 3, 12, 77, 1, 14, 89, 2, "Shakil", 13, 100, 3, False, False),
            (21, "Canela", 13, 100, 3, 21, 100, 3, 20, 100, 3, "daddymckay1123", 13, 100, 3, False, False),
            (22, "Jø$U", 13, 100, 3, 22, 100, 3, 21, 100, 3, "priskilla", 12, 100, 3, False, False),
            (23, "johan", 13, 100, 3, 23, 100, 3, 25, 100, 3, "LOL", 12, 100, 3, False, True),
            (24, "NAT.GM", 12, 100, 3, 24, 74, 2, 25, 76, 2, "Basketboy", 12, 100, 3, False, True),
            (25, "werex", 7, 100, 3, 25, 27, 0, 24, 24, 0, "Prince", 11, 100, 3, False, False),
        ],
    },
    {
        "war_id": "WAR-20261022-1709",
        "inicio_iso": "2026-10-22T22:09:00Z",
        "tamano": 25,
        "clan_estrellas": 74,
        "clan_destruccion": 99.84,
        "clan_ataques": 44,
        "rival_nombre": "KING OF BAJPARA",
        "rival_estrellas": 57,
        "rival_destruccion": 85.24,
        "max_orden_5h": 50,
        "filas": [
            (1, "Castro", 18, 100, 3, 1, 100, 3, 3, 96, 2, "SHAHIN", 18, 100, 3, False, False),
            (2, "leyenda negra", 18, 54, 1, 3, 65, 2, 1, 60, 2, "Mustafa", 18, 100, 3, False, False),
            (3, "Johan 2025", 18, 100, 3, 3, 83, 1, 2, 100, 3, "Enzo", 18, 96, 2, False, False),
            (4, "⭐Void Gaster s⭐", 17, 100, 3, 4, 100, 3, 3, 83, 2, "Siyam", 18, 100, 3, False, False),
            (5, "mofii", 17, 100, 3, 5, 100, 3, 1, 100, 3, "joker", 18, 100, 3, False, False),
            (6, "Edith", 16, 95, 2, 6, 70, 2, None, 0, 0, "mugiwara", 16, 100, 3, False, False),
            (7, "alexitoo", 16, 100, 3, 7, 100, 3, 6, 94, 2, "786786", 17, 100, 3, False, False),
            (8, "Manu", 16, 79, 2, 8, 97, 2, 12, 100, 3, "king of", 17, 100, 3, False, False),
            (9, "ZELDRIS", 16, 66, 2, 9, 100, 3, 8, 100, 3, "Gaming Rush", 16, 100, 3, False, False),
            (10, "Choreguapo", 16, 74, 2, 13, 100, 3, 21, 100, 3, "Senpai Dany HCA", 15, 100, 3, False, False),
            (11, "THE RICAX", 16, 71, 2, 11, 71, 2, 10, 95, 2, "Pas Sang21", 15, 100, 3, False, False),
            (12, "Alejandromm11", 15, 61, 2, 16, 100, 3, 18, 100, 3, "itx. Raisani", 15, 100, 3, False, False),
            (13, "A NefTwi A", 15, 83, 2, 13, 74, 2, 14, 100, 3, "VVS FaNeloS", 15, 100, 3, False, False),
            (14, "DANIEL GM", 15, 84, 2, None, 0, 0, None, 0, 0, "sa", 16, 100, 3, False, False),
            (15, "Jhadzel", 15, 68, 2, 15, 100, 3, 11, 100, 3, "XDA ScorpioN", 15, 100, 3, False, False),
            (16, "EdbEyond", 15, 50, 1, 10, 100, 3, 6, 81, 2, "wassup", 15, 100, 3, False, False),
            (17, "ZoroRoronoa", 15, 67, 2, 17, 100, 3, None, 0, 0, "rob", 16, 100, 3, False, False),
            (18, "pvp-camilo", 15, 83, 2, 21, 95, 2, None, 0, 0, "solin", 16, 100, 3, False, False),
            (19, "60M3", 15, 100, 3, 19, 100, 3, 21, 84, 2, "Champion", 15, 100, 3, False, False),
            (20, "Iván007 X°O", 15, 96, 2, 20, 100, 3, 21, 77, 1, "lavi madahar", 15, 100, 3, False, False),
            (21, "Canela", 13, 100, 3, 21, 81, 2, 23, 100, 3, "MOHAMAD 2", 14, 100, 3, False, False),
            (22, "Jø$U", 13, 100, 3, 22, 100, 3, 21, 63, 1, "S.S.@.X.P.O.", 13, 100, 3, False, False),
            (23, "johan", 13, 100, 3, 23, 100, 3, 21, 65, 2, "Ali raj", 13, 100, 3, False, False),
            (24, "NAT.GM", 12, 100, 3, 24, 100, 3, None, 0, 0, "raju", 11, 100, 3, False, False),
            (25, "werex", 8, 100, 3, 25, 32, 1, 24, 36, 0, "Ahmod", 11, 100, 3, False, False),
        ],
    },
    {
        "war_id": "WAR-20261024-1637",
        "inicio_iso": "2026-10-24T21:37:25Z",
        "tamano": 25,
        "clan_estrellas": 65,
        "clan_destruccion": 94.52,
        "clan_ataques": 45,
        "rival_nombre": "psycopaths❌⚔️",
        "rival_estrellas": 75,
        "rival_destruccion": 100.00,
        "max_orden_5h": 50,
        "filas": [
            (1, "Castro", 18, 100, 3, 1, 70, 2, 5, 100, 3, "FastlaneShin", 18, 100, 3, False, False),
            (2, "leyenda negra", 18, 100, 3, 2, 55, 2, 3, 99, 2, "m34", 18, 55, 2, False, False),
            (3, "Johan 2025", 18, 100, 3, 3, 88, 2, 6, 100, 3, "MondRay@1968", 18, 99, 2, False, True),
            (4, "⭐Void Gaster s⭐", 17, 100, 3, 4, 100, 3, 1, 100, 3, "Jay", 17, 100, 3, False, False),
            (5, "mofii", 17, 100, 3, 5, 93, 2, 20, 100, 3, "Brod hay1968", 17, 100, 3, False, False),
            (6, "Edith", 16, 100, 3, 10, 60, 2, 9, 85, 2, "VncnT", 17, 100, 3, False, False),
            (7, "alexitoo", 16, 100, 3, 7, 95, 2, 12, 91, 2, "rhoseky", 17, 95, 2, False, True),
            (8, "AT€NEA", 16, 100, 3, 13, 69, 2, 12, 93, 2, "warcommander", 16, 82, 2, True, False),
            (9, "Manu", 16, 100, 3, 14, 99, 2, 10, 97, 2, "CFFA", 16, 100, 3, True, False),
            (10, "ZELDRIS", 16, 100, 3, 8, 82, 2, 9, 100, 3, "Clasher", 16, 97, 2, False, False),
            (11, "Choreguapo", 16, 100, 3, None, 0, 0, None, 0, 0, "Engr.maru", 16, 72, 2, False, False),
            (12, "THE RICAX", 16, 100, 3, 12, 100, 3, 15, 63, 1, "Dark Angel", 16, 100, 3, False, False),
            (13, "Äshürä", 15, 100, 3, 18, 100, 3, 19, 99, 2, "Honey", 16, 71, 2, False, False),
            (14, "Alejandromm11", 15, 100, 3, 15, 100, 3, 23, 100, 3, "lfaith", 15, 99, 2, False, False),
            (15, "A NefTwi A", 15, 100, 3, 15, 91, 2, 11, 72, 2, "maru", 15, 100, 3, False, False),
            (16, "Jhadzel", 15, 100, 3, 17, 100, 3, 16, 100, 3, "RAIZA'S FIANCE", 15, 100, 3, False, False),
            (17, "EdbEyond", 15, 100, 3, 23, 100, 3, 22, 100, 3, "Clouds", 15, 100, 3, False, False),
            (18, "ZoroRoronoa", 15, 100, 3, 21, 68, 1, 24, 100, 3, "Taurean", 15, 100, 3, False, False),
            (19, "60M3", 15, 100, 3, None, 0, 0, None, 0, 0, "huk", 15, 99, 2, False, False),
            (20, "Boomer", 14, 100, 3, 20, 85, 2, 23, 74, 1, "dhruvraj", 15, 100, 3, False, False),
            (21, "Canela", 13, 100, 3, 21, 94, 2, 13, 71, 2, "THANOS", 15, 94, 2, False, True),
            (22, "Jø$U", 13, 100, 3, 23, 48, 0, 24, 55, 1, "gone in the win", 15, 100, 3, False, False),
            (23, "johan", 13, 100, 3, 23, 76, 2, 24, 72, 2, "alexa", 14, 100, 3, False, True),
            (24, "NAT.GM", 12, 100, 3, 24, 64, 2, 25, 62, 2, "BRUT", 14, 100, 3, False, True),
            (25, "werex", 8, 100, 3, 25, 15, 0, None, 0, 0, "carño", 13, 100, 3, False, False),
        ],
    },
]


# =============================================================================
# DATOS DE RESPALDO DE LOS 2 PDFs DE ASALTOS A LA CAPITAL
# (Se usan en caso de que la API de Supercell ya no devuelva alguno)
# =============================================================================
ASALTOS_PDF_RESPALDO = [
    {
        "raid_id": "RAID-20261016",
        "inicio_iso": "2026-10-16T07:00:00Z",
        "fin_iso": "2026-10-19T07:00:00Z",
        "estado": "ended",
        "oro_total": 390576,
        "incursiones": 10,
        "ataques_totales": 191,
        "distritos_destruidos": 59,
        "miembros": [
            ("albert", 6, 5, 1, 17290),
            ("ZELDRIS", 6, 5, 1, 15969),
            ("Tony", 6, 5, 1, 15787),
            ("alexitoo", 6, 5, 1, 14536),
            ("Jhadzel", 6, 5, 1, 14139),
            ("FullEwok", 6, 5, 1, 13582),
            ("Castro", 6, 5, 1, 13554),
            ("GÁRFIO", 6, 5, 1, 13413),
            ("EdbEyond", 6, 5, 1, 13380),
            ("kaiser", 6, 5, 1, 13323),
            ("werex", 6, 5, 1, 13244),
            ("Astaroth", 6, 5, 1, 12681),
            ("xedrick", 6, 5, 1, 12434),
            ("Johan 2025", 6, 5, 1, 12390),
            ("NAT.GM", 6, 5, 1, 12382),
            ("JR☆", 6, 5, 1, 12000),
            ("Arturo Diaz $$$", 6, 5, 1, 11794),
            ("bryanxD", 5, 5, 0, 11705),
            ("johan", 6, 5, 1, 11685),
            ("mofii", 6, 5, 1, 11643),
            ("alex", 6, 5, 1, 11636),
            ("Canela", 6, 5, 1, 11456),
            ("leyenda negra", 6, 5, 1, 11233),
            ("Manu", 6, 5, 1, 11205),
            ("⭐Void Gaster s⭐", 6, 5, 1, 11181),
            ("AT€NEA", 6, 5, 1, 10310),
            ("luisitoborr", 6, 5, 1, 9974),
            ("aliens 17 》", 6, 5, 1, 9955),
            ("❤️RONNIE❤️", 6, 5, 1, 9440),
            ("Aimar 342", 4, 5, 1, 8640),
            ("CALAMAR", 3, 5, 1, 6780),
            ("Edith", 6, 5, 1, 6220),
            ("Jø$U", 5, 5, 0, 5615),
        ],
    },
    {
        "raid_id": "RAID-20261023",
        "inicio_iso": "2026-10-23T07:00:00Z",
        "fin_iso": "2026-10-26T07:00:00Z",
        "estado": "ended",
        "oro_total": 476411,
        "incursiones": 11,
        "ataques_totales": 235,
        "distritos_destruidos": 71,
        "miembros": [
            ("Tony", 6, 5, 1, 15012),
            ("Canela", 6, 5, 1, 14993),
            ("Boomer", 6, 5, 1, 14222),
            ("Jhadzel", 6, 5, 1, 14171),
            ("bryanxD", 6, 5, 1, 13918),
            ("JR☆", 6, 5, 1, 13673),
            ("johan", 6, 5, 1, 13663),
            ("EdbEyond", 6, 5, 1, 13634),
            ("עבדיאל", 6, 5, 1, 13426),
            ("werex", 6, 5, 1, 13391),
            ("Ivan", 6, 5, 1, 13359),
            ("FullEwok", 6, 5, 1, 13182),
            ("CARRASCO", 6, 5, 1, 13050),
            ("Johan 2025", 6, 5, 1, 12978),
            ("Äshürä", 6, 5, 1, 12917),
            ("AT€NEA", 6, 5, 1, 12891),
            ("leyenda negra", 6, 5, 1, 12750),
            ("GÁRFIO", 6, 5, 1, 12644),
            ("alexitoo", 6, 5, 1, 12465),
            ("ZoroRoronoa", 6, 5, 1, 12440),
            ("Xavi 23", 6, 5, 1, 12366),
            ("mateo.coronel", 6, 5, 1, 12298),
            ("ZELDRIS", 6, 5, 1, 12276),
            ("THE RICAX", 6, 5, 1, 12143),
            ("alex", 6, 5, 1, 12115),
            ("Arturo Diaz $$$", 6, 5, 1, 12082),
            ("Manu", 6, 5, 1, 11716),
            ("Alejandromm11", 6, 5, 1, 11061),
            ("Iván007 X°O", 6, 5, 1, 10826),
            ("AQUILES", 6, 5, 1, 10573),
            ("Castro", 6, 5, 1, 10485),
            ("mofii", 6, 5, 1, 10420),
            ("Jø$U", 6, 5, 1, 10372),
            ("⭐Void Gaster s⭐", 6, 5, 1, 10294),
            ("Chuck 443", 6, 5, 1, 10134),
            ("Edith", 6, 5, 1, 9715),
            ("A NefTwi A", 6, 5, 1, 9701),
            ("NAT.GM", 6, 5, 1, 9178),
            ("FleexSonic", 6, 5, 1, 8017),
            ("kaiser", 1, 5, 0, 1860),
        ],
    },
]


def _construir_resolvedor_tags(
    captura: Captura | None, directorio: list[DirectorioMiembro]
) -> callable:
    mapa_exacto: dict[str, str] = {}
    mapa_lower: dict[str, str] = {}

    for d in directorio:
        t = normalizar_tag(d.tag)
        mapa_exacto[d.nombre.strip()] = t
        mapa_lower[d.nombre.strip().lower()] = t

    if captura:
        for m in captura.miembros:
            t = normalizar_tag(m.tag)
            mapa_exacto[m.nombre.strip()] = t
            mapa_lower[m.nombre.strip().lower()] = t

    def resolver(nick: str, usados_en_esta_tabla: set[str]) -> str:
        limpio = nick.strip()
        cand = mapa_exacto.get(limpio) or mapa_lower.get(limpio.lower())
        if not cand:
            # Búsqueda parcial por caracteres alfanuméricos (para nicks con símbolos)
            alfa = re.sub(r"[^a-zA-Z0-9]", "", limpio).lower()
            if len(alfa) >= 4:
                for k_low, v_tag in mapa_lower.items():
                    if alfa in re.sub(r"[^a-zA-Z0-9]", "", k_low).lower():
                        cand = v_tag
                        break
        if cand and cand not in usados_en_esta_tabla:
            usados_en_esta_tabla.add(cand)
            return cand

        tag_hist = _tag_sintetico("HST", limpio)
        while tag_hist in usados_en_esta_tabla:
            tag_hist = _tag_sintetico("HST", limpio + str(len(usados_en_esta_tabla)))
        usados_en_esta_tabla.add(tag_hist)
        return tag_hist

    return resolver


async def consolidar_y_migrar_todo(
    sesion: AsyncSession, cliente: ClashClient
) -> dict:
    """
    1. Sincroniza Captura actual de miembros, Guerra actual y últimas 10 temporadas de Capital desde Supercell.
    2. Migra las 6 Guerras Clásicas históricas de los PDFs y verifica las 2 temporadas de Capital.
    """
    resumen = {
        "captura_sincronizada": False,
        "guerra_actual_sincronizada": False,
        "asaltos_sincronizados_api": 0,
        "asaltos_migrados_pdf": 0,
        "guerras_historicas_migradas_pdf": 0,
        "guerras_historicas_ids": [],
    }

    # 1. Asegurar al menos una captura reciente para tener los #TAGs de los 48 miembros
    ultima_cap = await servicio_capturas.obtener_ultima_captura(sesion)
    if ultima_cap is None:
        try:
            ultima_cap = await servicio_capturas.crear_captura(sesion, cliente)
            resumen["captura_sincronizada"] = True
        except ClashApiError as e:
            logger.warning("Aviso al crear captura inicial: %s", e)
    else:
        resumen["captura_sincronizada"] = True

    # 2. Sincronizar guerra actual en curso / preparación
    try:
        g_act = await servicio_guerras.guardar_guerra_actual(sesion, cliente)
        resumen["guerra_actual_sincronizada"] = g_act is not None
    except ClashApiError:
        pass

    # 3. Sincronizar últimas 10 temporadas de Asaltos a la Capital directo desde Supercell API
    try:
        items_cap = await cliente.obtener_asaltos_capital(limite=10)
        for item_raw in items_cap:
            asalto_api = AsaltoOut.desde_api(item_raw)
            if asalto_api.inicio is None:
                continue
            res_ex = await sesion.execute(
                select(AsaltoCapital).where(AsaltoCapital.inicio == asalto_api.inicio)
            )
            if res_ex.scalar_one_or_none() is None:
                nuevo_as = AsaltoCapital(
                    estado=asalto_api.estado,
                    inicio=asalto_api.inicio,
                    fin=asalto_api.fin,
                    oro_capital_total=asalto_api.oro_capital_total,
                    asaltos_completados=asalto_api.asaltos_completados,
                    ataques_totales=asalto_api.ataques_totales,
                    distritos_rivales_destruidos=asalto_api.distritos_rivales_destruidos,
                    recompensa_ofensiva=asalto_api.recompensa_ofensiva,
                    recompensa_defensiva=asalto_api.recompensa_defensiva,
                )
                for m in asalto_api.miembros:
                    nuevo_as.miembros.append(
                        AsaltoMiembro(
                            tag=m.tag,
                            nombre=m.nombre,
                            ataques_usados=m.ataques_usados,
                            limite_ataques=m.limite_ataques,
                            ataques_bono=m.ataques_bono,
                            oro_capital_saqueado=m.oro_capital_saqueado,
                        )
                    )
                for sentido, lista_r in (
                    ("ofensivo", asalto_api.ataques_realizados),
                    ("defensivo", asalto_api.ataques_recibidos),
                ):
                    for reg_d in lista_r:
                        nuevo_as.registros.append(
                            servicio_asaltos._construir_registro(reg_d, sentido)
                        )
                sesion.add(nuevo_as)
                resumen["asaltos_sincronizados_api"] += 1
        await sesion.commit()
    except ClashApiError as e:
        logger.warning("Aviso al sincronizar historial de asaltos desde API: %s", e)

    # 4. Construir resolvedor de #TAGs para los PDFs
    res_dir = await sesion.execute(select(DirectorioMiembro))
    directorio_lista = list(res_dir.scalars().all())
    resolver_tag = _construir_resolvedor_tags(ultima_cap, directorio_lista)

    # 5. Verificar si alguno de los 2 Asaltos en PDF falta en PostgreSQL y agregarlo como respaldo
    for as_pdf in ASALTOS_PDF_RESPALDO:
        dt_ini = datetime.fromisoformat(as_pdf["inicio_iso"].replace("Z", "+00:00"))
        dt_fin = datetime.fromisoformat(as_pdf["fin_iso"].replace("Z", "+00:00"))
        res_check = await sesion.execute(
            select(AsaltoCapital).where(
                AsaltoCapital.inicio >= dt_ini - timedelta(hours=12),
                AsaltoCapital.inicio <= dt_ini + timedelta(hours=12),
            )
        )
        if res_check.scalar_one_or_none() is None:
            usados_as: set[str] = set()
            fila_as = AsaltoCapital(
                estado=as_pdf["estado"],
                inicio=dt_ini,
                fin=dt_fin,
                oro_capital_total=as_pdf["oro_total"],
                asaltos_completados=as_pdf["incursiones"],
                ataques_totales=as_pdf["ataques_totales"],
                distritos_rivales_destruidos=as_pdf["distritos_destruidos"],
                recompensa_ofensiva=0,
                recompensa_defensiva=0,
            )
            for nick_m, usados_m, lim_m, bono_m, oro_m in as_pdf["miembros"]:
                fila_as.miembros.append(
                    AsaltoMiembro(
                        tag=resolver_tag(nick_m, usados_as),
                        nombre=nick_m,
                        ataques_usados=usados_m,
                        limite_ataques=lim_m,
                        ataques_bono=bono_m,
                        oro_capital_saqueado=oro_m,
                    )
                )
            sesion.add(fila_as)
            resumen["asaltos_migrados_pdf"] += 1
    await sesion.commit()

    # 6. Consultar /warlog de Supercell (si está disponible) para enriquecer rival_tag y nivel
    warlog_map: dict[str, dict] = {}
    try:
        items_wl = await cliente.obtener_registro_guerras(limite=20)
        for w in items_wl:
            op_name = (w.get("opponent") or {}).get("name", "").strip().lower()
            if op_name:
                warlog_map[op_name] = w
    except ClashApiError:
        pass

    # 7. Migrar las 6 Guerras Clásicas Históricas de los PDFs
    nuestro_tag = normalizar_tag(settings.clan_tag)
    for g_pdf in GUERRAS_PDF_HISTORICAS:
        dt_inicio = datetime.fromisoformat(g_pdf["inicio_iso"].replace("Z", "+00:00"))
        dt_prep = dt_inicio - timedelta(hours=23)
        dt_fin = dt_inicio + timedelta(hours=24)

        res_g = await sesion.execute(
            select(Guerra)
            .where(
                Guerra.preparacion_inicio >= dt_prep - timedelta(hours=6),
                Guerra.preparacion_inicio <= dt_prep + timedelta(hours=6),
            )
            .options(selectinload(Guerra.miembros), selectinload(Guerra.ataques))
        )
        guerra_db = res_g.scalar_one_or_none()
        if guerra_db is not None and len(guerra_db.ataques) > 0:
            # Ya estaba migrada con todos sus ataques
            continue

        wl_match = warlog_map.get(g_pdf["rival_nombre"].strip().lower(), {})
        op_wl = wl_match.get("opponent") or {}
        cl_wl = wl_match.get("clan") or {}

        rival_tag = op_wl.get("tag") or _tag_sintetico("RIVCLAN", g_pdf["rival_nombre"])
        rival_nivel = op_wl.get("clanLevel") or 15
        clan_nivel = cl_wl.get("clanLevel") or 18
        clan_exp = cl_wl.get("expEarned") or 200

        if guerra_db is None:
            guerra_db = Guerra(
                preparacion_inicio=dt_prep,
                miembros=[],
                ataques=[],
            )
            sesion.add(guerra_db)
        else:
            guerra_db.miembros.clear()
            guerra_db.ataques.clear()
            await sesion.flush()

        guerra_db.estado = "warEnded"
        guerra_db.tamano_equipo = g_pdf["tamano"]
        guerra_db.ataques_por_miembro = 2
        guerra_db.modificador_batalla = "none"
        guerra_db.inicio = dt_inicio
        guerra_db.fin = dt_fin
        guerra_db.max_orden_5h = g_pdf["max_orden_5h"]

        guerra_db.clan_tag = nuestro_tag
        guerra_db.clan_nombre = "Melanie Stacy"
        guerra_db.clan_nivel = clan_nivel
        guerra_db.clan_estrellas = g_pdf["clan_estrellas"]
        guerra_db.clan_destruccion = g_pdf["clan_destruccion"]
        guerra_db.clan_ataques_usados = g_pdf["clan_ataques"]
        guerra_db.clan_experiencia_ganada = clan_exp

        guerra_db.rival_tag = rival_tag
        guerra_db.rival_nombre = g_pdf["rival_nombre"]
        guerra_db.rival_nivel = rival_nivel
        guerra_db.rival_estrellas = g_pdf["rival_estrellas"]
        guerra_db.rival_destruccion = g_pdf["rival_destruccion"]

        usados_propios: set[str] = set()
        mapa_propios_pos: dict[int, tuple[str, str]] = {}
        mapa_rivales_pos: dict[int, tuple[str, str]] = {}

        # A) Crear todos los miembros propios y rivales en guerra_miembros
        for fila in g_pdf["filas"]:
            pos, nick, th, def_pct, def_stars, t1_pos, t1_pct, t1_stars, t2_pos, t2_pct, t2_stars, riv_nick, riv_th, riv_pct, riv_stars, inf_t1, inf_t2 = fila

            tag_prop = resolver_tag(nick, usados_propios)
            tag_riv = f"#RIV_{g_pdf['war_id'][-9:].replace('-', '')}_{pos:02d}"

            mapa_propios_pos[pos] = (tag_prop, nick)
            mapa_rivales_pos[pos] = (tag_riv, riv_nick)

            guerra_db.miembros.append(
                GuerraMiembro(
                    tag=tag_prop,
                    nombre=nick,
                    nivel_ayuntamiento=th,
                    posicion_mapa=pos,
                    es_propio=True,
                    ataques_recibidos=1 if def_pct > 0 else 0,
                )
            )
            guerra_db.miembros.append(
                GuerraMiembro(
                    tag=tag_riv,
                    nombre=riv_nick,
                    nivel_ayuntamiento=riv_th,
                    posicion_mapa=pos,
                    es_propio=False,
                    ataques_recibidos=1 if riv_pct > 0 else 0,
                )
            )

        # B) Crear nuestros ataques (respetando orden <= 50 para <5h y > 50 para Mapa Libre)
        orden_temprano = 1
        orden_tardio = 51
        orden_rival = 201

        for fila in g_pdf["filas"]:
            pos, nick, th, def_pct, def_stars, t1_pos, t1_pct, t1_stars, t2_pos, t2_pct, t2_stars, riv_nick, riv_th, riv_pct, riv_stars, inf_t1, inf_t2 = fila
            tag_prop, nombre_prop = mapa_propios_pos[pos]

            # Tiro 1
            if t1_pos is not None:
                tag_def1, nom_def1 = mapa_rivales_pos.get(t1_pos, (f"#RIV_UNK_{t1_pos}", f"Rival #{t1_pos}"))
                es_5h_t1 = (t1_pos == pos) or inf_t1
                if es_5h_t1:
                    ord_1 = orden_temprano
                    orden_temprano += 1
                else:
                    ord_1 = orden_tardio
                    orden_tardio += 1

                guerra_db.ataques.append(
                    GuerraAtaque(
                        orden=ord_1,
                        atacante_tag=tag_prop,
                        atacante_nombre=nombre_prop,
                        defensor_tag=tag_def1,
                        defensor_nombre=nom_def1,
                        estrellas=t1_stars,
                        destruccion=float(t1_pct),
                    )
                )

            # Tiro 2
            if t2_pos is not None:
                tag_def2, nom_def2 = mapa_rivales_pos.get(t2_pos, (f"#RIV_UNK_{t2_pos}", f"Rival #{t2_pos}"))
                if inf_t2:
                    ord_2 = orden_temprano
                    orden_temprano += 1
                else:
                    ord_2 = orden_tardio
                    orden_tardio += 1

                guerra_db.ataques.append(
                    GuerraAtaque(
                        orden=ord_2,
                        atacante_tag=tag_prop,
                        atacante_nombre=nombre_prop,
                        defensor_tag=tag_def2,
                        defensor_nombre=nom_def2,
                        estrellas=t2_stars,
                        destruccion=float(t2_pct),
                    )
                )

            # Defensa recibida (ataque del rival contra nuestra base)
            if def_pct > 0:
                tag_riv_esp, nom_riv_esp = mapa_rivales_pos[pos]
                guerra_db.ataques.append(
                    GuerraAtaque(
                        orden=orden_rival,
                        atacante_tag=tag_riv_esp,
                        atacante_nombre=nom_riv_esp,
                        defensor_tag=tag_prop,
                        defensor_nombre=nombre_prop,
                        estrellas=def_stars,
                        destruccion=float(def_pct),
                    )
                )
                orden_rival += 1

        resumen["guerras_historicas_migradas_pdf"] += 1
        resumen["guerras_historicas_ids"].append(f"{g_pdf['war_id']} vs {g_pdf['rival_nombre']}")

    await sesion.commit()
    return resumen