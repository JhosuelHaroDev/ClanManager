"""Herramientas de datos en PostgreSQL, Grafo de Memoria y Biblioteca Táctica de S.T.A.C.Y."""

import logging
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.asalto import AsaltoCapital, AsaltoDistrito, AsaltoRegistro
from app.models.captura import Captura, CapturaMiembro
from app.models.guerra import Guerra
from app.models.stacy import DirectorioMiembro, StacyAristaGrafo, StacyNodoMemoria
from app.services import asaltos as servicio_asaltos
from app.services import capturas as servicio_capturas
from app.services import guerras as servicio_guerras
from app.services import liga as servicio_liga
from app.services.clash_client import ClashApiError, ClashClient, normalizar_tag
from app.services.stacy_knowledge import (
    ORDEN_JERARQUIA_LIGAS,
    ROL_TRADUCCION,
    TOPES_HEROES_TH,
)

logger = logging.getLogger("clanmanager.stacy_tools")


def _limpiar_nick(nombre: str | None) -> str:
    if not nombre:
        return ""
    s = re.sub(r"\[TH\d+\]", "", str(nombre), flags=re.IGNORECASE)
    s = re.sub(r"\s*\([LCV]\)$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*\(Fuera\)$", "", s, flags=re.IGNORECASE)
    return s.strip()


def _calcular_puntaje_jerarquia(liga_nombre: str | None, trofeos: int = 0) -> int:
    liga_str = str(liga_nombre or "Unranked").replace("League", "").strip()
    peso_franja = 0
    for idx, nombre_franja in enumerate(ORDEN_JERARQUIA_LIGAS):
        if nombre_franja.lower() in liga_str.lower():
            peso_franja = idx + 1
            break
    match_div = re.search(r"\b(\d{1,2})\b", liga_str)
    division = int(match_div.group(1)) if match_div else 0
    return (peso_franja * 10_000_000) + (division * 100_000) + int(trofeos or 0)


async def identificar_miembro_por_telefono(
    sesion: AsyncSession, telefono_remitente: str | None
) -> dict | None:
    """
    Cruza los últimos 9 dígitos del teléfono de WhatsApp con `directorio_miembros`
    y enriquece su perfil con la última `Captura` y la `Guerra` activa en PostgreSQL.
    """
    if not telefono_remitente:
        return None
    solo_digitos = re.sub(r"\D", "", str(telefono_remitente))
    if len(solo_digitos) < 9:
        return None
    ultimos_9 = solo_digitos[-9:]

    res_dir = await sesion.execute(
        select(DirectorioMiembro).where(
            DirectorioMiembro.whatsapp_telefono.like(f"%{ultimos_9}")
        )
    )
    registro_dir = res_dir.scalar_one_or_none()
    if registro_dir is None:
        return None

    tag_jugador = normalizar_tag(registro_dir.tag)
    rol_es = "Miembro"
    th = 15
    escudo = "IN"
    estado_heroes = "N/D"
    nombre_limpio = _limpiar_nick(registro_dir.nombre)

    # Buscar sus datos más recientes en la última captura
    ultima_cap = await servicio_capturas.obtener_ultima_captura(sesion)
    if ultima_cap:
        cm = next((m for m in ultima_cap.miembros if m.tag == tag_jugador), None)
        if cm:
            nombre_limpio = cm.nombre
            rol_es = ROL_TRADUCCION.get(cm.rol, cm.rol)
            th = cm.nivel_ayuntamiento
            escudo = "IN" if (cm.preferencia_guerra or "in") == "in" else "OUT"
            pct, est_cod, _ = _evaluar_progreso_heroes(cm)
            estado_heroes = f"{pct}% ({est_cod})"

    es_alto_mando = rol_es.lower() in ("lider", "colider", "veterano")

    info = {
        "nombre_limpio": nombre_limpio,
        "tag": tag_jugador,
        "rango": rol_es,
        "nivel_acceso": "ALTO MANDO" if es_alto_mando else "MIEMBRO REGULAR",
        "th": th,
        "escudo_guerra": escudo,
        "estado_heroes": estado_heroes,
        "strikes": registro_dir.strikes_acumulados,
        "posicion_en_guerra_actual": None,
        "ataques_en_guerra_actual": None,
        "tiro_1_guerra_actual": None,
    }

    # Verificar si está en la guerra activa
    res_g = await sesion.execute(
        select(Guerra)
        .order_by(Guerra.preparacion_inicio.desc())
        .limit(1)
        .options(selectinload(Guerra.miembros), selectinload(Guerra.ataques))
    )
    guerra = res_g.scalar_one_or_none()
    if guerra and guerra.estado in ("preparation", "inWar"):
        gm = next(
            (m for m in guerra.miembros if m.es_propio and m.tag == tag_jugador),
            None,
        )
        if gm:
            mis_atks = sorted(
                [a for a in guerra.ataques if a.atacante_tag == tag_jugador],
                key=lambda x: x.orden,
            )
            perm = guerra.ataques_por_miembro or (1 if guerra.war_tag else 2)
            info["posicion_en_guerra_actual"] = f"#{gm.posicion_mapa}"
            info["ataques_en_guerra_actual"] = f"{len(mis_atks)}/{perm}"
            if mis_atks:
                a1 = mis_atks[0]
                info["tiro_1_guerra_actual"] = f"{a1.destruccion:.0f}%({a1.estrellas}*)"

    return info


def _evaluar_progreso_heroes(cm: CapturaMiembro) -> tuple[float, str, str]:
    th = cm.nivel_ayuntamiento or 1
    topes = TOPES_HEROES_TH.get(th, {"bk": 0, "aq": 0, "gw": 0, "rc": 0, "mp": 0, "dd": 0})
    rb = cm.nivel_rey_barbaro or 0
    ra = cm.nivel_reina_arquera or 0
    gc = cm.nivel_gran_centinela or 0
    lr = cm.nivel_luchadora_real or 0
    pe = cm.nivel_principe_esbirro or 0
    dd = cm.nivel_duque_dragon or 0

    suma_max = sum(topes.values())
    suma_act = rb + ra + gc + lr + pe + dd
    pct = round((suma_act / suma_max) * 100, 1) if suma_max > 0 else 100.0

    if pct >= 100:
        est = "MAX"
    elif pct >= 85:
        est = "SOLIDO"
    elif pct >= 65:
        est = "MEDIO"
    else:
        est = "RUSH"

    resumen_h = (
        f"RB:{rb}/{topes['bk']} RA:{ra}/{topes['aq']} GC:{gc}/{topes['gw']} "
        f"LR:{lr}/{topes['rc']} PE:{pe}/{topes['mp']} DD:{dd}/{topes['dd']}"
    )
    return pct, est, resumen_h


async def ejecutar_herramienta_stacy(
    nombre_funcion: str,
    args: dict,
    sesion: AsyncSession,
    cliente: ClashClient,
) -> dict:
    """Enrutador principal de herramientas de S.T.A.C.Y. sobre PostgreSQL."""
    try:
        if nombre_funcion == "consultar_guerra_actual":
            return await _tool_consultar_guerra_actual(args, sesion, cliente)
        if nombre_funcion == "consultar_bases_rivales":
            return await _tool_consultar_bases_rivales(args, sesion, cliente)
        if nombre_funcion == "consultar_cwl_liga":
            return await _tool_consultar_cwl_liga(args, sesion, cliente)
        if nombre_funcion == "consultar_miembros_heroes":
            return await _tool_consultar_miembros_heroes(args, sesion, cliente)
        if nombre_funcion == "consultar_jugador_en_vivo":
            return await _tool_consultar_jugador_en_vivo(args, cliente)
        if nombre_funcion == "consultar_asaltos_capital":
            return await _tool_consultar_asaltos_capital(args, sesion, cliente)
        if nombre_funcion == "consultar_historial_ligas":
            return await _tool_consultar_historial_ligas(args, sesion, cliente)
        if nombre_funcion == "gestionar_memoria_grafo":
            return await _tool_gestionar_memoria_grafo(args, sesion)
        if nombre_funcion == "consultar_guia_estrategica_coc":
            return _tool_consultar_guia_estrategica_coc(args)
        if nombre_funcion == "buscar_en_internet":
            return await _tool_buscar_en_internet(args)
        return {"error": f"Herramienta no reconocida: {nombre_funcion}"}
    except Exception as exc:
        logger.exception("Error ejecutando herramienta %s: %s", nombre_funcion, exc)
        return {"error": f"Error al consultar PostgreSQL/API: {exc}"}


# =========================================================================
# TOOL 1: GUERRA ACTUAL / PASADA (DESDE POSTGRESQL + GRAFO DE ACUERDOS)
# =========================================================================
async def _obtener_guerra_objetivo(
    sesion: AsyncSession,
    cliente: ClashClient,
    periodo: str,
    forzar: bool,
    rival_buscado: str | None = None,
) -> tuple[Guerra | None, str | None]:
    ahora = datetime.now(timezone.utc)

    res = await sesion.execute(
        select(Guerra)
        .order_by(Guerra.preparacion_inicio.desc())
        .limit(15)
        .options(selectinload(Guerra.miembros), selectinload(Guerra.ataques))
    )
    ultimas = list(res.scalars().all())

    necesita_sondeo = forzar or not ultimas
    if ultimas and not necesita_sondeo:
        g_top = ultimas[0]
        edad_min = (ahora - g_top.ultima_actualizacion_en).total_seconds() / 60.0
        if g_top.estado in ("preparation", "inWar") and edad_min > 8:
            necesita_sondeo = True

    if necesita_sondeo:
        try:
            await servicio_guerras.guardar_guerra_actual(sesion, cliente)
            res = await sesion.execute(
                select(Guerra)
                .order_by(Guerra.preparacion_inicio.desc())
                .limit(15)
                .options(selectinload(Guerra.miembros), selectinload(Guerra.ataques))
            )
            ultimas = list(res.scalars().all())
        except ClashApiError:
            pass

    if not ultimas:
        return None, None

    if rival_buscado:
        r_low = rival_buscado.strip().lower()
        for g in ultimas:
            if r_low in g.rival_nombre.lower():
                return g, None

    if periodo in ("pasada", "anterior"):
        terminadas = [g for g in ultimas if g.estado == "warEnded"]
        if terminadas:
            return terminadas[0], None
        return ultimas[-1], "Mostrando la única guerra registrada en base de datos."

    g_reciente = ultimas[0]
    if g_reciente.estado == "warEnded":
        return (
            g_reciente,
            "ATENCIÓN: El clan NO tiene guerra en curso ahora mismo. Se adjuntan los datos de la última guerra finalizada.",
        )
    return g_reciente, None


def _reconstruir_estado_guerra(guerra: Guerra, cambios_autorizados: set[tuple[str, str]]) -> dict:
    """Cruza miembros propios, rivales y ataques de la tabla `guerras` en PostgreSQL."""
    ahora = datetime.now(timezone.utc)
    es_cwl = bool(guerra.war_tag)
    perm = guerra.ataques_por_miembro or (1 if es_cwl else 2)
    tamano = guerra.tamano_equipo or 15

    propios = sorted([m for m in guerra.miembros if m.es_propio], key=lambda x: x.posicion_mapa)
    rivales = sorted([m for m in guerra.miembros if not m.es_propio], key=lambda x: x.posicion_mapa)
    riv_por_tag = {r.tag: r for r in rivales}
    riv_por_pos = {r.posicion_mapa: r for r in rivales}
    prop_por_tag = {p.tag: p for p in propios}

    nuestros_ataques = sorted(
        [a for a in guerra.ataques if a.atacante_tag in prop_por_tag],
        key=lambda x: x.orden,
    )
    ataques_rivales = [a for a in guerra.ataques if a.atacante_tag in riv_por_tag]

    # Corte de las 5 horas
    max_order_5h = guerra.max_orden_5h or 0
    if not es_cwl and guerra.inicio and max_order_5h == 0:
        if ahora <= guerra.inicio + timedelta(hours=5):
            max_order_5h = max((a.orden for a in guerra.ataques), default=0)

    # Mejor ataque recibido por cada rival y por cada miembro propio
    mejor_contra_rival: dict[str, tuple[int, float]] = {}
    for a in nuestros_ataques:
        prev = mejor_contra_rival.get(a.defensor_tag, (-1, -1.0))
        if (a.estrellas, a.destruccion) > prev:
            mejor_contra_rival[a.defensor_tag] = (a.estrellas, a.destruccion)

    mejor_contra_propio: dict[str, tuple[int, float]] = {}
    for a in ataques_rivales:
        prev = mejor_contra_propio.get(a.defensor_tag, (-1, -1.0))
        if (a.estrellas, a.destruccion) > prev:
            mejor_contra_propio[a.defensor_tag] = (a.estrellas, a.destruccion)

    # Detectar invasiones de espejo <5h
    espejo_invadido_por: dict[int, str] = {}
    for a in nuestros_ataques:
        atacante = prop_por_tag.get(a.atacante_tag)
        defensor = riv_por_tag.get(a.defensor_tag)
        if atacante and defensor and a.orden <= max_order_5h:
            if atacante.posicion_mapa != defensor.posicion_mapa:
                espejo_invadido_por.setdefault(
                    defensor.posicion_mapa, f"#{atacante.posicion_mapa} {atacante.nombre}"
                )

    filas = []
    for p in propios:
        pos = p.posicion_mapa
        mis_tiros = [a for a in nuestros_ataques if a.atacante_tag == p.tag]
        usados = len(mis_tiros)

        def fmt_tiro(atk) -> str:
            def_riv = riv_por_tag.get(atk.defensor_tag)
            pos_d = f"#{def_riv.posicion_mapa}" if def_riv else "?"
            return f"({pos_d}){atk.destruccion:.0f}% {atk.estrellas}*"

        t1_txt = fmt_tiro(mis_tiros[0]) if usados >= 1 else "-"
        t2_txt = "N/A(CWL)" if es_cwl else (fmt_tiro(mis_tiros[1]) if usados >= 2 else "-")

        def_prop = mejor_contra_propio.get(p.tag)
        def_txt = f"{def_prop[1]:.0f}% {def_prop[0]}*" if def_prop else "Intacta"

        riv_esp = riv_por_pos.get(pos)
        best_riv = mejor_contra_rival.get(riv_esp.tag) if riv_esp else None
        if not best_riv:
            est_riv_txt = "INTACTA"
        elif best_riv[0] == 3:
            est_riv_txt = "100% 3*"
        else:
            est_riv_txt = f"{best_riv[1]:.0f}% {best_riv[0]}* (Abierta)"

        # Evaluar infracciones y observaciones
        infracciones = []
        if not es_cwl:
            for idx_t, atk in enumerate(mis_tiros):
                def_riv = riv_por_tag.get(atk.defensor_tag)
                def_pos = def_riv.posicion_mapa if def_riv else 0
                par_nombres = (p.nombre.lower(), (riv_por_pos.get(def_pos).nombre.lower() if riv_por_pos.get(def_pos) else ""))
                if atk.orden <= max_order_5h and def_pos != pos and par_nombres not in cambios_autorizados:
                    if idx_t == 0:
                        infracciones.append(f"Infraccion(<5h): Ataco #{def_pos} ignorando espejo #{pos}")
                    else:
                        infracciones.append(f"Infraccion(<5h): 2do tiro a #{def_pos} antes de las 5h")

        if infracciones:
            obs = " | ".join(infracciones)
        elif usados == 0:
            obs = f"No ataco (0/{perm})" if guerra.estado == "warEnded" else f"Pendiente (0/{perm})"
        elif usados < perm:
            obs = f"Dejo 1 tiro colgado (1/{perm})" if guerra.estado == "warEnded" else f"Falta 2do tiro (1/{perm})"
        else:
            stars_tot = sum(a.estrellas for a in mis_tiros)
            obs = f"Doble Pleno (6*)" if stars_tot == perm * 3 else f"Cumplio ({stars_tot}*)"

        filas.append({
            "pos": pos,
            "nick": p.nombre,
            "th": p.nivel_ayuntamiento,
            "usados": usados,
            "perm": perm,
            "tiros": f"{usados}/{perm}",
            "t1": t1_txt,
            "t2": t2_txt,
            "def": def_txt,
            "rival_nick": riv_esp.nombre if riv_esp else f"Rival #{pos}",
            "rival_th": riv_esp.nivel_ayuntamiento if riv_esp else 0,
            "estado_rival": est_riv_txt,
            "obs": obs,
        })

    # Fase de tiempo y marcador
    if guerra.estado == "warEnded":
        fase_txt = "Guerra Finalizada"
    elif guerra.estado == "preparation" and guerra.inicio:
        rest_m = max(0, int((guerra.inicio - ahora).total_seconds() // 60))
        fase_txt = f"Dia Preparacion (Inicia en {rest_m // 60}h {rest_m % 60}m)"
    elif guerra.fin:
        rest_m = max(0, int((guerra.fin - ahora).total_seconds() // 60))
        if not es_cwl and guerra.inicio and ahora <= guerra.inicio + timedelta(hours=5):
            esp_m = max(0, int(((guerra.inicio + timedelta(hours=5)) - ahora).total_seconds() // 60))
            fase_txt = f"Regla Solo Espejo ({esp_m // 60}h {esp_m % 60}m rest)"
        else:
            fase_txt = f"Mapa Libre ({rest_m // 60}h {rest_m % 60}m rest)"
    else:
        fase_txt = guerra.estado

    if guerra.clan_estrellas > guerra.rival_estrellas or (
        guerra.clan_estrellas == guerra.rival_estrellas and guerra.clan_destruccion > guerra.rival_destruccion
    ):
        res_global = "VICTORIA"
    elif guerra.clan_estrellas < guerra.rival_estrellas or (
        guerra.clan_estrellas == guerra.rival_estrellas and guerra.clan_destruccion < guerra.rival_destruccion
    ):
        res_global = "DERROTA"
    else:
        res_global = "EMPATE"

    nuestros_plenos = sum(1 for a in nuestros_ataques if a.estrellas == 3)
    rivales_plenos = sum(1 for a in ataques_rivales if a.estrellas == 3)
    max_tiros = tamano * perm

    resumen_marcador = (
        f"{guerra.clan_nombre} [{guerra.clan_estrellas}/{tamano*3}* ({guerra.clan_destruccion:.2f}%) | "
        f"Tiros: {len(nuestros_ataques)}/{max_tiros} | Plenos: {nuestros_plenos}] vs "
        f"{guerra.rival_nombre} [{guerra.rival_estrellas}/{tamano*3}* ({guerra.rival_destruccion:.2f}%) | "
        f"Tiros: {len(ataques_rivales)}/{max_tiros} | Plenos: {rivales_plenos}] | "
        f"Resultado: {res_global} ({guerra.estado}) | {tamano}v{tamano} {'CWL' if es_cwl else 'Clasica'} | {fase_txt}"
    )

    return {"marcador": resumen_marcador, "fase": fase_txt, "filas": filas}


async def _tool_consultar_guerra_actual(
    args: dict, sesion: AsyncSession, cliente: ClashClient
) -> dict:
    periodo = str(args.get("periodo") or "actual").lower()
    rival_buscado = args.get("rival")
    buscar_jug = _limpiar_nick(args.get("nombre_jugador")).lower()

    # Si piden el historial global de guerras (sin especificar un rival puntual)
    if periodo == "historial" and not rival_buscado:
        res_h = await sesion.execute(
            select(Guerra)
            .where(Guerra.estado == "warEnded")
            .order_by(Guerra.preparacion_inicio.desc())
            .limit(15)
            .options(selectinload(Guerra.miembros), selectinload(Guerra.ataques))
        )
        guerras_hist = list(res_h.scalars().all())
        if not guerras_hist:
            return {"estado": "Aún no hay guerras finalizadas en el historial de PostgreSQL."}

        tabla_guerras = []
        acum_jugadores: dict[str, dict] = {}

        for g in guerras_hist:
            paq = _reconstruir_estado_guerra(g, set())
            fecha_g = g.inicio.strftime("%d/%m/%Y") if g.inicio else "N/D"
            res_txt = "VICTORIA" if g.clan_estrellas > g.rival_estrellas else ("DERROTA" if g.clan_estrellas < g.rival_estrellas else "EMPATE")
            tabla_guerras.append(
                f"{fecha_g}|vs {g.rival_nombre}|{g.tamano_equipo}v{g.tamano_equipo}|"
                f"{g.clan_estrellas}*({g.clan_destruccion:.1f}%) a {g.rival_estrellas}*({g.rival_destruccion:.1f}%)|{res_txt}"
            )
            for f in paq["filas"]:
                k = f["nick"].lower()
                st = acum_jugadores.setdefault(
                    k,
                    {"nick": f["nick"], "th": f["th"], "guerras": 0, "usados": 0, "perm": 0, "plenos": 0, "ceros": 0, "infracciones": 0},
                )
                st["guerras"] += 1
                st["usados"] += f["usados"]
                st["perm"] += f["perm"]
                if "3*" in f["t1"]:
                    st["plenos"] += 1
                if "3*" in f["t2"]:
                    st["plenos"] += 1
                if f["usados"] == 0:
                    st["ceros"] += 1
                if "infraccion" in f["obs"].lower():
                    st["infracciones"] += 1

        lista_j = list(acum_jugadores.values())
        if buscar_jug:
            lista_j = [j for j in lista_j if buscar_jug in j["nick"].lower()]
        lista_j.sort(key=lambda x: (-x["plenos"], -x["usados"], x["ceros"]))

        return {
            "total_guerras_historicas": len(guerras_hist),
            "guerras_cols": "Fecha|Rival|Formato|Marcador|Resultado",
            "guerras_filas": tabla_guerras,
            "rendimiento_acumulado_cols": "Nick|TH|GuerrasConvocado|TirosUsados/Perm|Plenos3*|Veces0/2|Infracciones<5h",
            "rendimiento_acumulado_filas": [
                f"{j['nick']}|TH{j['th']}|{j['guerras']}G|{j['usados']}/{j['perm']}|{j['plenos']} plenos|{j['ceros']} en 0/2|{j['infracciones']} inf"
                for j in lista_j[:35]
            ],
        }

    forzar = bool(args.get("forzar_actualizacion", False))
    guerra, aviso = await _obtener_guerra_objetivo(sesion, cliente, periodo, forzar, rival_buscado)

    if guerra is None:
        return {"estado": "No hay guerras registradas todavía en PostgreSQL."}

    # Consultar si hay acuerdos de cambio de espejo en el Grafo de Memoria
    res_grafo = await sesion.execute(
        select(StacyAristaGrafo)
        .where(
            StacyAristaGrafo.es_activa.is_(True),
            StacyAristaGrafo.tipo_relacion == "CAMBIO_ESPEJO_CON",
        )
        .options(
            selectinload(StacyAristaGrafo.nodo_origen),
            selectinload(StacyAristaGrafo.nodo_destino),
        )
    )
    acuerdos_aristas = list(res_grafo.scalars().all())
    cambios_set: set[tuple[str, str]] = set()
    notas_acuerdos = []
    for ar in acuerdos_aristas:
        n1 = ar.nodo_origen.nombre_entidad.lower()
        n2 = ar.nodo_destino.nombre_entidad.lower()
        cambios_set.add((n1, n2))
        cambios_set.add((n2, n1))
        notas_acuerdos.append(f"{ar.nodo_origen.nombre_entidad} <-> {ar.nodo_destino.nombre_entidad} ({ar.nota_explicativa or 'Cambio espejo'})")

    paquete = _reconstruir_estado_guerra(guerra, cambios_set)
    filtro = str(args.get("filtro") or "todos").lower()
    buscar_jug = _limpiar_nick(args.get("nombre_jugador")).lower()
    remitente_verif = _limpiar_nick(args.get("_remitente_verificado")).lower()

    linea_remitente = "No convocado en esta guerra o no vinculado."
    if remitente_verif:
        f_rem = next((x for x in paquete["filas"] if x["nick"].lower() == remitente_verif), None)
        if f_rem:
            linea_remitente = (
                f"#{f_rem['pos']}|{f_rem['nick']}[TH{f_rem['th']}]|Tiros:{f_rem['tiros']}|"
                f"T1:{f_rem['t1']}|T2:{f_rem['t2']}|Def:{f_rem['def']}|"
                f"EspejoRival(#{f_rem['pos']}):{f_rem['estado_rival']}|Obs:{f_rem['obs']}"
            )

    if buscar_jug:
        exactos = [x for x in paquete["filas"] if x["nick"].lower() == buscar_jug]
        lista = exactos or [x for x in paquete["filas"] if buscar_jug in x["nick"].lower()]
        return {
            "aviso": aviso,
            "marcador": paquete["marcador"],
            "columnas": "Pos|Nick|TH|Tiros|Tiro1|Tiro2|Defensa|EspejoRival|Observacion",
            "filas": [
                f"#{x['pos']}|{x['nick']}|TH{x['th']}|{x['tiros']}|{x['t1']}|{x['t2']}|{x['def']}|{x['estado_rival']}|{x['obs']}"
                for x in lista
            ],
        }

    if filtro in ("todos", "resumen"):
        infractores = []
        cracks = []
        sin_atacar_0 = []
        falta_1 = []
        bases_abiertas = []

        for x in paquete["filas"]:
            if "infraccion" in x["obs"].lower() or "no ataco" in x["obs"].lower():
                infractores.append(f"#{x['pos']}|{x['nick']}[TH{x['th']}]|{x['obs']}|T1:{x['t1']}|T2:{x['t2']}")
            if "Doble Pleno" in x["obs"] or ("3*" in x["t1"] and x["perm"] == 1):
                cracks.append(f"#{x['pos']}|{x['nick']}[TH{x['th']}]|T1:{x['t1']}{(' + T2:' + x['t2']) if x['t2'] not in ('-', 'N/A(CWL)') else ''}")
            if x["usados"] == 0:
                sin_atacar_0.append(f"#{x['pos']} {x['nick']}[TH{x['th']}] ({x['tiros']})")
            elif x["usados"] < x["perm"]:
                falta_1.append(f"#{x['pos']} {x['nick']}[TH{x['th']}] ({x['tiros']}, T1:{x['t1']})")
            if "100%" not in x["estado_rival"]:
                bases_abiertas.append(f"#{x['pos']}[TH{x['rival_th']}]: {x['estado_rival']}")

        return {
            "aviso": aviso,
            "marcador": paquete["marcador"],
            "tu_desempeno_personal": linea_remitente,
            "acuerdos_memoria_grafo": notas_acuerdos or None,
            "infractores_reglamento": infractores or ["Ninguno"],
            "cracks_plenos": cracks[:10],
            "sin_atacar_0_tiros_total": len(sin_atacar_0),
            "sin_atacar_0_tiros_lista": sin_atacar_0,
            "falta_1_tiro_total": len(falta_1),
            "falta_1_tiro_lista": falta_1,
            "bases_rivales_abiertas_total": len(bases_abiertas),
            "bases_rivales_abiertas_muestra": bases_abiertas[:12],
        }

    filtrados = []
    for x in paquete["filas"]:
        if filtro == "pendientes" and x["usados"] < x["perm"]:
            filtrados.append(x)
        elif filtro == "infractores" and ("infraccion" in x["obs"].lower() or "no ataco" in x["obs"].lower()):
            filtrados.append(x)
        elif filtro == "plenos" and ("3*" in x["t1"] or "3*" in x["t2"]):
            filtrados.append(x)

    return {
        "aviso": aviso,
        "marcador": paquete["marcador"],
        "tu_desempeno_personal": linea_remitente,
        "filtro": filtro,
        "total": len(filtrados),
        "columnas": "Pos|Nick|TH|Tiros|Tiro1|Tiro2|Observacion",
        "filas": [
            f"#{x['pos']}|{x['nick']}|TH{x['th']}|{x['tiros']}|{x['t1']}|{x['t2']}|{x['obs']}"
            for x in filtrados
        ],
    }


# =========================================================================
# TOOL 2: BASES RIVALES (DESDE POSTGRESQL)
# =========================================================================
async def _tool_consultar_bases_rivales(
    args: dict, sesion: AsyncSession, cliente: ClashClient
) -> dict:
    periodo = str(args.get("periodo") or "actual").lower()
    guerra, aviso = await _obtener_guerra_objetivo(sesion, cliente, periodo, False)
    if guerra is None:
        return {"estado": "No hay datos de guerra en PostgreSQL."}

    paquete = _reconstruir_estado_guerra(guerra, set())
    estado_f = str(args.get("estado") or "abiertas").lower()
    th_f = int(args["th"]) if args.get("th") else None

    bases = []
    for x in paquete["filas"]:
        if th_f and x["rival_th"] != th_f:
            continue
        cerrada = "100%" in x["estado_rival"]
        intacta = "INTACTA" in x["estado_rival"] or "0*" in x["estado_rival"]
        if estado_f == "abiertas" and cerrada:
            continue
        if estado_f == "intactas" and not intacta:
            continue
        if estado_f == "cerradas" and not cerrada:
            continue
        bases.append(f"#{x['pos']}|TH{x['rival_th']}|{x['rival_nick']}|{x['estado_rival']}|Espejo:{x['nick']}({x['tiros']})")

    return {
        "aviso": aviso,
        "fase": paquete["fase"],
        "total_bases": len(bases),
        "columnas": "Pos|Rival_TH|NickRival|EstadoBase|NuestroEspejo(Tiros)",
        "filas": bases,
    }


# =========================================================================
# TOOL 2B: RESUMEN DE LIGA DE GUERRAS DE CLANES (CWL EN POSTGRESQL)
# =========================================================================
async def _tool_consultar_cwl_liga(
    args: dict, sesion: AsyncSession, cliente: ClashClient
) -> dict:
    temporada = args.get("temporada") or await servicio_liga.temporada_mas_reciente(sesion)
    if temporada is None:
        try:
            await servicio_guerras.guardar_liga_actual(sesion, cliente)
            temporada = await servicio_liga.temporada_mas_reciente(sesion)
        except ClashApiError:
            pass

    if temporada is None:
        return {"estado": "No hay ninguna temporada de CWL registrada actualmente."}

    rondas = await servicio_liga.listar_rondas(sesion, temporada)
    enfrentamientos = await servicio_liga.listar_enfrentamientos(sesion, temporada)
    nuestro_tag = normalizar_tag(settings.clan_tag)

    clasificacion = servicio_liga.calcular_clasificacion(enfrentamientos, nuestro_tag)
    rendimiento = servicio_liga.calcular_rendimiento(rondas)

    return {
        "temporada_cwl": temporada,
        "ronda_actual": servicio_liga.ronda_actual(enfrentamientos),
        "clasificacion_cols": "Pos|Clan|EstrellasTotales(Combate+Bono)|Destruccion|V-D-E",
        "clasificacion_filas": [
            f"#{c.posicion}|{'[NOSOTROS] ' if c.es_propio else ''}{c.nombre}|{c.estrellas}*({c.estrellas_en_combate}+{c.estrellas_bono})|{c.destruccion}%|{c.victorias}V-{c.derrotas}D-{c.empates}E"
            for c in clasificacion
        ],
        "rendimiento_miembros_cols": "Nick|TH|RondasAlineado|Atacados|Perdidos|EstrellasTotales|PromDestruccion",
        "rendimiento_miembros_filas": [
            f"{m.nombre}|TH{m.nivel_ayuntamiento}|{m.rondas_alineado}|{m.ataques_realizados}|{m.ataques_perdidos}|{m.estrellas_total}*|{(m.destruccion_promedio or 0):.1f}%"
            for m in rendimiento[:30]
        ],
    }


# =========================================================================
# TOOL 3: ROSTER DE MIEMBROS, 6 HÉROES Y DONACIONES (DESDE POSTGRESQL)
# =========================================================================
async def _tool_consultar_miembros_heroes(
    args: dict, sesion: AsyncSession, cliente: ClashClient
) -> dict:
    captura = await servicio_capturas.obtener_ultima_captura(sesion)
    if captura is None:
        captura = await servicio_capturas.crear_captura(sesion, cliente)

    res_dir = await sesion.execute(select(DirectorioMiembro))
    mapa_dir = {normalizar_tag(d.tag): d for d in res_dir.scalars().all()}

    buscar_nombre = _limpiar_nick(args.get("nombre_jugador")).lower()
    filtro_th = int(args["th"]) if args.get("th") else None
    filtro_guerra = str(args.get("estado_guerra") or "todos").lower()
    filtro_rango = str(args.get("rango") or "todos").lower()
    criterio = str(args.get("ordenar_por") or "orden_clan").lower()

    items = []
    suma_pct = 0.0
    tot_in = 0
    tot_don = 0

    for idx, cm in enumerate(captura.miembros, start=1):
        pct, est_cod, resumen_h = _evaluar_progreso_heroes(cm)
        suma_pct += pct
        war_cod = "IN" if (cm.preferencia_guerra or "in") == "in" else "OUT"
        if war_cod == "IN":
            tot_in += 1
        tot_don += cm.donaciones or 0

        rol_es = ROL_TRADUCCION.get(cm.rol, cm.rol)
        info_d = mapa_dir.get(normalizar_tag(cm.tag))
        tiene_wa = bool(info_d and info_d.whatsapp_telefono)

        if filtro_th and cm.nivel_ayuntamiento != filtro_th:
            continue
        if filtro_guerra == "activos" and war_cod != "IN":
            continue
        if filtro_guerra == "rojo" and war_cod != "OUT":
            continue
        if filtro_rango != "todos" and filtro_rango not in rol_es.lower():
            continue

        items.append({
            "pos": cm.rango_clan or idx,
            "nick": cm.nombre,
            "rol": rol_es,
            "th": cm.nivel_ayuntamiento,
            "war": war_cod,
            "don": cm.donaciones or 0,
            "rec": cm.donaciones_recibidas or 0,
            "stars": cm.estrellas_guerra or 0,
            "pctH": pct,
            "estH": est_cod,
            "heroes": resumen_h,
            "wa": "SI" if tiene_wa else "NO",
        })

    if buscar_nombre:
        exactos = [m for m in items if m["nick"].lower() == buscar_nombre]
        lista = exactos or [m for m in items if buscar_nombre in m["nick"].lower()]
    else:
        lista = items

    if criterio == "mas_rusheados":
        lista.sort(key=lambda x: (x["pctH"], -x["th"]))
    elif criterio == "mejores_heroes":
        lista.sort(key=lambda x: (-x["pctH"], -x["th"]))
    elif criterio == "mas_donaciones":
        lista.sort(key=lambda x: -x["don"])
    elif criterio == "mas_estrellas":
        lista.sort(key=lambda x: -x["stars"])
    else:
        lista.sort(key=lambda x: x["pos"])

    limite = int(args.get("limite") or 20)
    corte = lista[:limite]
    total_m = len(captura.miembros) or 1
    kpis = (
        f"Miembros: {len(captura.miembros)}/50 | Guerra: {tot_in} IN / {len(captura.miembros)-tot_in} OUT | "
        f"PromHeroesClan: {suma_pct/total_m:.1f}% | DonacionesTotales: {tot_don}"
    )

    return {
        "kpis_clan": kpis,
        "coincidencias": len(lista),
        "mostrando": len(corte),
        "columnas": "Pos|Nick|Rol|TH|War|Don/Rec|Stars|%Heroes|EstadoH|NivelesHeroes(RB RA GC LR PE DD)|WA",
        "filas": [
            f"#{m['pos']}|{m['nick']}|{m['rol']}|TH{m['th']}|{m['war']}|{m['don']}/{m['rec']}|"
            f"{m['stars']}|{m['pctH']}%|{m['estH']}|{m['heroes']}|{m['wa']}"
            for m in corte
        ],
    }


# =========================================================================
# TOOL 3B: CONSULTA INDIVIDUAL EN VIVO (EQUIPAMIENTO Y JUEGOS DEL CLAN)
# =========================================================================
async def _tool_consultar_jugador_en_vivo(args: dict, cliente: ClashClient) -> dict:
    buscar = str(args.get("nombre_o_tag") or "").strip()
    if not buscar:
        return {"error": "Debes proporcionar el nombre o el #TAG del jugador."}

    tags = []
    if buscar.startswith("#"):
        tags.append(normalizar_tag(buscar))
    else:
        clan = await cliente.obtener_clan()
        buscar_l = _limpiar_nick(buscar).lower()
        for m in clan.get("memberList", []):
            if m["name"].lower() == buscar_l:
                tags.insert(0, m["tag"])
            elif buscar_l in m["name"].lower():
                tags.append(m["tag"])

    if not tags:
        return {"error": f"No se encontró ningún miembro en el clan que coincida con '{buscar}'."}

    perfiles = []
    for t in tags[:2]:
        p = await cliente.obtener_jugador(t)
        th = p.get("townHallLevel", 1)
        topes = TOPES_HEROES_TH.get(th, {"bk": 0, "aq": 0, "gw": 0, "rc": 0, "mp": 0, "dd": 0})
        heroes_home = {h["name"]: h["level"] for h in p.get("heroes", []) if h.get("village") == "home"}

        rb = heroes_home.get("Barbarian King", 0)
        ra = heroes_home.get("Archer Queen", 0)
        gc = heroes_home.get("Grand Warden", 0)
        lr = heroes_home.get("Royal Champion", 0)
        pe = heroes_home.get("Minion Prince", 0)
        dd = heroes_home.get("Dragon Duke", 0)

        equipamiento = []
        for h in p.get("heroes", []):
            if h.get("village") == "home" and h.get("equipment"):
                eqs = ", ".join(f"{e['name']}(Nv.{e['level']})" for e in h["equipment"])
                equipamiento.append(f"{h['name']}: {eqs}")

        pts_juegos = next(
            (a["value"] for a in p.get("achievements", []) if a.get("name") == "Games Champion"),
            0,
        )

        perfiles.append({
            "nick": p.get("name"),
            "tag": p.get("tag"),
            "rol": ROL_TRADUCCION.get(p.get("role", "member"), "Miembro"),
            "th": th,
            "liga": (p.get("leagueTier") or {}).get("name", "Unranked"),
            "copas": p.get("trophies", 0),
            "guerra": "IN" if p.get("warPreference") == "in" else "OUT",
            "estrellas_guerra": p.get("warStars", 0),
            "don_rec": f"{p.get('donations', 0)}/{p.get('donationsReceived', 0)}",
            "ataques_ganados_temp": p.get("attackWins", 0),
            "pts_historicos_juegos_clan": pts_juegos,
            "oro_contribuido_capital": p.get("clanCapitalContributions", 0),
            "heroes": f"RB:{rb}/{topes['bk']} RA:{ra}/{topes['aq']} GC:{gc}/{topes['gw']} LR:{lr}/{topes['rc']} PE:{pe}/{topes['mp']} DD:{dd}/{topes['dd']}",
            "equipamiento_activo": equipamiento,
        })

    return {"consulta_en_vivo": True, "perfiles": perfiles}


# =========================================================================
# TOOL 4: ASALTOS A LA CAPITAL (RANKING Y BITÁCORA DESDE POSTGRESQL)
# =========================================================================
async def _tool_consultar_asaltos_capital(
    args: dict, sesion: AsyncSession, cliente: ClashClient
) -> dict:
    res = await sesion.execute(
        select(AsaltoCapital)
        .order_by(AsaltoCapital.inicio.desc())
        .limit(1)
        .options(
            selectinload(AsaltoCapital.miembros),
            selectinload(AsaltoCapital.registros)
            .selectinload(AsaltoRegistro.distritos)
            .selectinload(AsaltoDistrito.ataques),
        )
    )
    asalto = res.scalar_one_or_none()
    if asalto is None:
        asalto = await servicio_asaltos.guardar_asalto_actual(sesion, cliente)

    if asalto is None:
        return {"error": "No hay temporadas de Asaltos a la Capital registradas."}

    tipo = str(args.get("tipo_consulta") or "ranking").lower()
    buscar_jug = _limpiar_nick(args.get("nombre_jugador")).lower()

    if tipo == "bitacora":
        golpes = []
        correlativo = 1
        registros_ofensivos = [r for r in asalto.registros if r.sentido == "ofensivo"]
        for reg in reversed(registros_ofensivos):
            for dist in reversed(reg.distritos):
                # Reconstruir cronológicamente (0% -> 100%)
                atks_cron = list(reversed(dist.ataques))
                acum = 0
                golpes_dist = []
                for atk in atks_cron:
                    antes = acum
                    despues = atk.destruccion
                    aporte = max(0, despues - antes)
                    oro_est = round((aporte / dist.destruccion) * dist.saqueado) if dist.destruccion > 0 else 0
                    if antes == 0 and despues == 100:
                        hito = "ONE_SHOT(100%)"
                    elif despues == 100:
                        hito = "REMATE_BONUS(100%)"
                    elif 90 <= despues < 100:
                        hito = f"DEJADO_AL_{despues}%"
                    elif antes == 0:
                        hito = "APERTURA"
                    else:
                        hito = "PROGRESO"

                    golpes_dist.append({
                        "nick": atk.atacante_nombre,
                        "dist": f"{dist.nombre}({reg.clan_nombre})",
                        "prog": f"{antes}%->{despues}%(+{aporte}%)",
                        "oro": oro_est,
                        "hito": hito,
                    })
                    acum = despues

                for g in reversed(golpes_dist):
                    g["num"] = correlativo
                    correlativo += 1
                    if not buscar_jug or buscar_jug in g["nick"].lower():
                        golpes.append(g)

        corte = golpes[: (25 if buscar_jug else 20)]
        return {
            "pestana": "Bitacora Asaltos (PostgreSQL)",
            "coincidencias": len(golpes),
            "columnas": "#Golpe|Jugador|Distrito(ClanRival)|Antes->Despues(Aporte)|OroEst|Hito",
            "filas": [
                f"#{g['num']}|{g['nick']}|{g['dist']}|{g['prog']}|{g['oro']}|{g['hito']}"
                for g in corte
            ],
        }

    # Ranking general cruzado con la última captura de miembros del clan
    ultima_cap = await servicio_capturas.obtener_ultima_captura(sesion)
    miembros_clan = {m.tag: m.nombre for m in ultima_cap.miembros} if ultima_cap else {}
    mapa_asaltantes = {m.tag: m for m in asalto.miembros}

    ranking = []
    for tag_c, nombre_c in miembros_clan.items():
        am = mapa_asaltantes.get(tag_c)
        if am:
            perm = am.limite_ataques + am.ataques_bono
            prom = round(am.oro_capital_saqueado / am.ataques_usados) if am.ataques_usados > 0 else 0
            obs = "Completo+Bonus" if (am.ataques_usados == perm and am.ataques_bono > 0) else ("Completo" if am.ataques_usados == perm else "Incompleto")
            ranking.append({
                "nick": nombre_c,
                "usados": am.ataques_usados,
                "tiros": f"{am.ataques_usados}/{perm}",
                "bonus": "SI" if am.ataques_bono > 0 else "NO",
                "oro": am.oro_capital_saqueado,
                "prom": prom,
                "obs": obs,
            })
        else:
            ranking.append({
                "nick": nombre_c,
                "usados": 0,
                "tiros": "0/5",
                "bonus": "NO",
                "oro": 0,
                "prom": 0,
                "obs": "Sin Ataques",
            })

    # Detectar turistas
    for am in asalto.miembros:
        if miembros_clan and am.tag not in miembros_clan:
            perm = am.limite_ataques + am.ataques_bono
            prom = round(am.oro_capital_saqueado / am.ataques_usados) if am.ataques_usados > 0 else 0
            ranking.append({
                "nick": am.nombre,
                "usados": am.ataques_usados,
                "tiros": f"{am.ataques_usados}/{perm}",
                "bonus": "SI" if am.ataques_bono > 0 else "NO",
                "oro": am.oro_capital_saqueado,
                "prom": prom,
                "obs": "Turista(Salio)",
            })

    ranking.sort(key=lambda x: (-x["oro"], -x["usados"]))
    filtro = str(args.get("filtro") or "todos").lower()

    filtrados = []
    for idx, r in enumerate(ranking, start=1):
        r["pos"] = idx
        if buscar_jug and buscar_jug not in r["nick"].lower():
            continue
        if filtro == "sin_atacar" and r["obs"] != "Sin Ataques":
            continue
        if filtro == "incompletos" and r["obs"] != "Incompleto":
            continue
        if filtro == "turistas" and "Turista" not in r["obs"]:
            continue
        filtrados.append(r)

    if filtro == "top_oro":
        filtrados = filtrados[:12]

    kpis = (
        f"Estado: {asalto.estado} | OroTotal: {asalto.oro_capital_total:,} | "
        f"Ataques: {asalto.ataques_totales} | Incursiones: {asalto.asaltos_completados} | "
        f"DistritosDestruidos: {asalto.distritos_rivales_destruidos}"
    )

    return {
        "kpis": kpis,
        "total": len(filtrados),
        "columnas": "Pos|Jugador|Tiros|Bonus6to|OroTotal|PromPorTiro|Estado",
        "filas": [
            f"#{r['pos']}|{r['nick']}|{r['tiros']}|{r['bonus']}|{r['oro']}|{r['prom']}|{r['obs']}"
            for r in filtrados
        ],
    }


# =========================================================================
# TOOL 5: HISTORIAL DE LIGAS Y EVOLUCIÓN (DESDE CAPTURAS EN POSTGRESQL)
# =========================================================================
async def _tool_consultar_historial_ligas(
    args: dict, sesion: AsyncSession, cliente: ClashClient
) -> dict:
    res = await sesion.execute(
        select(Captura)
        .order_by(Captura.capturado_en.desc())
        .limit(2)
        .options(selectinload(Captura.miembros))
    )
    capturas = list(res.scalars().all())
    if not capturas:
        nueva = await servicio_capturas.crear_captura(sesion, cliente)
        capturas = [nueva]

    cap_actual = capturas[0]
    cap_anterior = capturas[1] if len(capturas) > 1 else None
    mapa_ant = {m.tag: m for m in cap_anterior.miembros} if cap_anterior else {}

    buscar_jug = _limpiar_nick(args.get("nombre_jugador")).lower()
    jugadores = []

    for m in cap_actual.miembros:
        liga_act = (m.liga or "Unranked").replace("League", "").strip()
        score_order = _calcular_puntaje_jerarquia(liga_act, m.trofeos)
        score_liga_pura = _calcular_puntaje_jerarquia(liga_act, 0)

        m_ant = mapa_ant.get(m.tag)
        if m_ant:
            liga_ant = (m_ant.liga or "Unranked").replace("League", "").strip()
            score_ant_pura = _calcular_puntaje_jerarquia(liga_ant, 0)
            if score_liga_pura > score_ant_pura:
                evo = "SUBIO"
            elif score_liga_pura < score_ant_pura:
                evo = "BAJO"
            else:
                evo = "IGUAL"
            ant_txt = f"{liga_ant} ({m_ant.trofeos})"
        else:
            evo = "NUEVO"
            ant_txt = "-"

        jugadores.append({
            "nick": m.nombre,
            "score": score_order,
            "evo": evo,
            "actual": f"{liga_act} ({m.trofeos})",
            "anterior": ant_txt,
        })

    jugadores.sort(key=lambda x: -x["score"])
    filtrados = []
    for idx, j in enumerate(jugadores, start=1):
        if buscar_jug and buscar_jug not in j["nick"].lower():
            continue
        filtrados.append(f"#{idx}|{j['nick']}|{j['evo']}|{j['actual']}|{j['anterior']}")

    return {
        "captura_actual": cap_actual.capturado_en.strftime("%Y-%m-%d %H:%M"),
        "captura_comparada": cap_anterior.capturado_en.strftime("%Y-%m-%d %H:%M") if cap_anterior else "Sin captura previa",
        "columnas": "Pos|Jugador|EvolucionLiga|LigaActual(Copas)|LigaAnterior(Copas)",
        "filas": filtrados[:35],
    }


# =========================================================================
# TOOL 6 (NUEVA v3.0): GESTIÓN DEL GRAFO DE MEMORIA Y DIRECTORIO DE S.T.A.C.Y.
# =========================================================================
async def _tool_gestionar_memoria_grafo(args: dict, sesion: AsyncSession) -> dict:
    accion = str(args.get("accion") or "consultar").lower()

    if accion == "guardar_relaciones":
        sujeto = str(args.get("sujeto") or "").strip()
        relacion = str(args.get("tipo_relacion") or "NOTA_TACTICA").upper().strip()
        objeto = str(args.get("objeto") or "").strip()
        nota = str(args.get("nota_explicativa") or "").strip()
        autor = str(args.get("_remitente_verificado") or "Alto Mando")

        if not sujeto or not objeto:
            return {"error": "Debes indicar 'sujeto' y 'objeto' para crear el recuerdo en el grafo."}

        async def obtener_o_crear_nodo(nombre: str, tipo: str) -> StacyNodoMemoria:
            res_n = await sesion.execute(
                select(StacyNodoMemoria).where(StacyNodoMemoria.nombre_entidad.ilike(nombre))
            )
            nodo = res_n.scalar_one_or_none()
            if nodo is None:
                nodo = StacyNodoMemoria(tipo_nodo=tipo, nombre_entidad=nombre)
                sesion.add(nodo)
                await sesion.flush()
            return nodo

        n_origen = await obtener_o_crear_nodo(sujeto, "JUGADOR")
        n_destino = await obtener_o_crear_nodo(objeto, "ENTIDAD")

        arista = StacyAristaGrafo(
            nodo_origen_id=n_origen.id,
            tipo_relacion=relacion,
            nodo_destino_id=n_destino.id,
            registrado_por=autor,
            nota_explicativa=nota,
            es_activa=True,
        )
        sesion.add(arista)
        await sesion.commit()
        return {
            "guardado_en_grafo": True,
            "arista": f"({n_origen.nombre_entidad}) -[{relacion}]-> ({n_destino.nombre_entidad})",
            "nota": nota,
            "registrado_por": autor,
        }

    # Acción por defecto: consultar recuerdos activos en el grafo
    buscar = str(args.get("sujeto") or "").strip().lower()
    res_a = await sesion.execute(
        select(StacyAristaGrafo)
        .where(StacyAristaGrafo.es_activa.is_(True))
        .order_by(StacyAristaGrafo.creado_en.desc())
        .limit(30)
        .options(
            selectinload(StacyAristaGrafo.nodo_origen),
            selectinload(StacyAristaGrafo.nodo_destino),
        )
    )
    aristas = list(res_a.scalars().all())
    resultados = []
    for a in aristas:
        orig = a.nodo_origen.nombre_entidad
        dest = a.nodo_destino.nombre_entidad
        if buscar and (buscar not in orig.lower() and buscar not in dest.lower()):
            continue
        fecha_s = a.creado_en.strftime("%d/%m/%Y")
        resultados.append(f"{orig} | {a.tipo_relacion} | {dest} | Nota: {a.nota_explicativa or '-'} ({fecha_s})")

    return {
        "total_recuerdos_activos": len(resultados),
        "columnas": "Sujeto|Relacion|Objeto|Detalle",
        "recuerdos": resultados or ["No hay recuerdos ni acuerdos activos registrados en el grafo."],
    }


# =========================================================================
# TOOL 7: BIBLIOTECA TÁCTICA MODULAR (CAPA 3 - 5 CATEGORÍAS)
# =========================================================================
def _tool_consultar_guia_estrategica_coc(args: dict) -> dict:
    cat = str(args.get("categoria") or "normativa_y_rangos_stacy").lower()

    if cat == "heroes_y_equipamiento_meta":
        topes_tabla = [
            f"TH{th}|RB:{t['bk']}|RA:{t['aq']}|GC:{t['gw']}|LR:{t['rc']}|PE:{t['mp']}|DD:{t['dd']}"
            for th, t in sorted(TOPES_HEROES_TH.items(), reverse=True)
            if th >= 9
        ]
        return {
            "categoria": "heroes_y_equipamiento_meta",
            "regla_salon_heroes": "6 heroes en Aldea Principal; se eligen hasta 4 activos por batalla.",
            "sexto_heroe": "Duque Dragon (DD) para ataques terrestres Smash / hibridos; Principe Esbirro (PE) para aereos puros.",
            "combos_meta_oct2026": [
                "RB|Bola con Pinchos + Botas Terremoto (Alt: Guantelete Gigante + Vial Furia)",
                "RA|Espejo Magico + Vial Invisibilidad/Sanadoras (Alt: Flecha Gigante + Sanadoras)",
                "GC|Tomo Eterno + Gema Curacion (Alt: Bola de Fuego + Gema Furia)",
                "LR|Lanza Cohete + Escudo Buscador/Botas Electro (Alt: Vial Celeridad + Montapuercos)",
                "PE|Orbe Oscuro + Marioneta Esbirros",
                "DD|Aliento Igneo + Escamas de Magma",
            ],
            "topes_por_th": topes_tabla,
            "angulo_sarcasmo_stacy": "De nada sirve equipamiento Epico al maximo si llevan al heroe con 30 niveles de retraso; es como ponerle aleron de Formula 1 a una carreta.",
        }

    if cat == "estrategias_ataque_por_th":
        return {
            "categoria": "estrategias_ataque_por_th",
            "meta_TH16_a_TH18": [
                "Root Riders + Valkyrias + Overgrowth|Jinetes de Raices + Valkyrias + Druidas + DD/RB + 2 Hechizos Crecimiento",
                "Warden Fireball + Super Witches|Centinela con Bola de Fuego + Invisibilidades + Terremotos al nucleo",
                "Dragon Duke Hybrid / Mass Dragons|Dragones + Globos + PE/DD + Clonacion/Furia al centro + Flecha Gigante de RA",
            ],
            "meta_TH13_a_TH15": [
                "Super Archer Blimp + Hydra|Dirigible Superarqueras (2 Clon + 1 Furia + 5 Invis) + Dragones y Jinetes de Dragon",
                "Queen Charge Hybrid|Reina con 5 Sanadoras elimina CC/TH + Mineros y Montapuercos con Centinela",
            ],
            "angulo_sarcasmo_stacy": "Soltar todos los Dragones en una esquina y rezarle a Supercell no cuenta como estrategia tactica.",
        }

    if cat == "economia_y_eventos_2026":
        return {
            "categoria": "economia_y_eventos_2026",
            "hammer_jam": "Martillomania (previo a TH19): 50% descuento en costos y tiempos. Ahorrar Medallas CWL, Pocimas de Constructor, Libros y Runas.",
            "minerales": "Mantenerse en ligas Dragon, Electro o Legend por Bono Estelar diario de Glowy/Shiny Ore y jugar guerra continua por Starry Ore.",
            "angulo_sarcasmo_stacy": "Gastar Medallas de CWL en recursos para muros fuera de Martillomania deberia ser delito financiero en el clan.",
        }

    if cat == "capital_y_modos_clan":
        return {
            "categoria": "capital_y_modos_clan",
            "capital": "Obligatorio 6/6 tiros. Quedar 5/5 = 1 Strike. Ley Anti-Egoismo: prohibido dejar distritos en 90%-99% si te quedan ataques.",
            "ligas_tropas": "Evalua cambio de Franja/Division (SUBIO, BAJO, IGUAL) ignorando variaciones menores de copas.",
            "angulo_sarcasmo_stacy": "Dejar un distrito al 98% esperando que otro gaste su tiro por 200 de oro es como dejar un milimetro de leche en la jarra para no lavarla.",
        }

    return {
        "categoria": "normativa_y_rangos_stacy",
        "guerra_clasica": "Primeras 5h solo ataque a espejo (# contra #) con 1er tiro. Si invaden tu espejo, NO robes otro; espera a las 5h (Mapa Libre). Obligatorio 2/2 tiros.",
        "cwl": "24h ataque exclusivo a espejo (1/1), salvo cambio acordado o autorizado por el Lider.",
        "cuotas": "Capital 6/6 obligatorio | Juegos del Clan 2,000 pts minimo | Inactividad max 3 dias sin aviso.",
        "angulo_sarcasmo_stacy": "Las reglas son mas faciles que la tabla del 2, pero siempre hay quien cree que el reloj de las 5 horas esta de adorno.",
    }


# =========================================================================
# TOOL 8: BÚSQUEDA WEB EN CASCADA ASÍNCRONA (TAVILY -> GOOGLE SEARCH)
# =========================================================================
async def _tool_buscar_en_internet(args: dict) -> dict:
    query = str(args.get("consulta") or "").strip()
    if not query:
        return {"error": "Debes proporcionar una consulta de búsqueda."}

    async with httpx.AsyncClient(timeout=12.0) as http:
        if settings.tavily_api_key:
            try:
                res = await http.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": settings.tavily_api_key,
                        "query": query,
                        "search_depth": "basic",
                        "include_answer": True,
                        "max_results": 3,
                    },
                )
                if res.status_code == 200:
                    data = res.json()
                    return {
                        "motor": "Tavily AI",
                        "resumen": data.get("answer", ""),
                        "resultados": [
                            f"{r.get('title')}: {r.get('content')} ({r.get('url')})"
                            for r in data.get("results", [])
                        ],
                    }
            except httpx.HTTPError:
                pass

        if settings.google_search_api_key and settings.google_search_cx:
            try:
                res = await http.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params={
                        "key": settings.google_search_api_key,
                        "cx": settings.google_search_cx,
                        "q": query,
                        "num": 3,
                    },
                )
                if res.status_code == 200:
                    data = res.json()
                    return {
                        "motor": "Google Search",
                        "resultados": [
                            f"{i.get('title')}: {i.get('snippet')} ({i.get('link')})"
                            for i in data.get("items", [])
                        ],
                    }
            except httpx.HTTPError:
                pass

    return {"error": "Servicios de búsqueda web no disponibles en este momento."}