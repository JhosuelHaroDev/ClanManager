# 🛡️ ClanManager API & S.T.A.C.Y. v3.0

**Plataforma Asíncrona de Inteligencia Táctica, Auditoría Forense y Gestión Automatizada para Clash of Clans**  
*Desarrollado para el clan **Melanie Stacy (`#89YVP0RG`)***

---

## 📑 Tabla de Contenidos

1. [Visión General del Proyecto](#-1-visión-general-del-proyecto)
2. [Stack Tecnológico](#-2-stack-tecnológico)
3. [Arquitectura General del Sistema](#-3-arquitectura-general-del-sistema)
4. [Estructura del Repositorio](#-4-estructura-del-repositorio)
5. [Modelo de Base de Datos en PostgreSQL (15 Tablas)](#-5-modelo-de-base-de-datos-en-postgresql-15-tablas)
6. [Historial de Migraciones de Alembic](#-6-historial-de-migraciones-de-alembic)
7. [El Cerebro de S.T.A.C.Y. v3.0 (Arquitectura Híbrida ReAct)](#-7-el-cerebro-de-stacy-v30-arquitectura-híbrida-react)
8. [Catálogo de las 10 Herramientas de S.T.A.C.Y.](#-8-catálogo-de-las-10-herramientas-de-stacy)
9. [Motores de Auditoría Táctica y Forense](#-9-motores-de-auditoría-táctica-y-forense)
   - [9.1. Auditoría de Guerra Clásica (Regla de las 5 Horas)](#91-auditoría-de-guerra-clásica-regla-de-las-5-horas)
   - [9.2. Motor de Liga de Guerras de Clanes (CWL)](#92-motor-de-liga-de-guerras-de-clanes-cwl)
   - [9.3. Sondeo en 2 Etapas y Auditoría Forense de la Capital del Clan](#93-sondeo-en-2-etapas-y-auditoría-forense-de-la-capital-del-clan)
   - [9.4. Descarga Concurrente de los 6 Héroes y Jerarquía de Ligas](#94-descarga-concurrente-de-los-6-héroes-y-jerarquía-de-ligas)
10. [Programador Autónomo (`APScheduler`) y Alertas Proactivas en WhatsApp](#-10-programador-autónomo-apscheduler-y-alertas-proactivas-en-whatsapp)
11. [Referencia Completa de la API REST (Endpoints)](#-11-referencia-completa-de-la-api-rest-endpoints)
12. [Configuración y Variables de Entorno (`.env`)](#-12-configuración-y-variables-de-entorno-env)
13. [Despliegue en Producción (Docker & Railway)](#-13-despliegue-en-producción-docker--railway)
14. [Operación, Consultas SQL Útiles y Mantenimiento](#-14-operación-consultas-sql-útiles-y-mantenimiento)

---

## 🎯 1. Visión General del Proyecto

**ClanManager & S.T.A.C.Y. v3.0** (*Sistema Táctico de Asistencia y Control Yuxtapuesto*) es un ecosistema backend en tiempo real construido en **Python 3.11** con **FastAPI** y **PostgreSQL**. Su propósito es automatizar la supervisión competitiva del clan **Melanie Stacy (`#89YVP0RG`)** en *Clash of Clans*, recolectando telemetría continua desde la API oficial de Supercell y exponiendo una analista táctica con Inteligencia Artificial directamente en los grupos de **WhatsApp** del clan a través de **Green-API**.

### Capacidades Principales
* **Persistencia Histórica Relacional:** Almacena capturas periódicas de los 50 miembros (incluyendo los niveles de los **6 héroes de la aldea principal hasta Ayuntamiento 18**), guerras clásicas, temporadas completas de la Liga de Guerras de Clanes (**CWL**) y fines de semana de **Asaltos a la Capital**.
* **Cerebro Agéntico Híbrido en 2 Etapas (Bucle ReAct):** Separa el razonamiento y selección multi-herramienta (**Etapa 1**, con hasta $3$ iteraciones de verificación de suficiencia) de la redacción ejecutiva (**Etapa 2**), operando con una cola de modelos en cascada (**Groq $\rightarrow$ NVIDIA $\rightarrow$ Anthropic Claude**) y un *Circuit Breaker* automático ante errores `HTTP 429`.
* **Auditoría Forense Determinista:** Calcula en Python (sin depender de alucinaciones del LLM) quién rompió la **Regla de Espejo de las 5 Horas** en guerra clásica, quién violó el espejo de **24 horas en CWL**, y quién abandonó distritos sin rematar teniendo ataques disponibles en la **Capital del Clan**.
* **Grafo de Memoria Persistente:** Permite registrar y consultar acuerdos tácticos (como cambios de espejo autorizados entre dos jugadores), permisos de ausencia y cuentas secundarias, integrándolos automáticamente en las auditorías de guerra.
* **Anuncios Proactivos Automáticos:** Publica reportes automáticos en el grupo oficial de WhatsApp en el inicio de batalla, a las 5 horas (apertura de Mapa Libre), a falta de 3 horas para el cierre, al finalizar la guerra y en tiempo real cuando se detecta una infracción en los Asaltos a la Capital.

---

## 🧰 2. Stack Tecnológico

| Capa | Tecnología / Librería | Versión | Rol en el Proyecto |
| :--- | :--- | :--- | :--- |
| **Lenguaje** | Python | `3.11` | Tipado moderno (`Mapped`, `str \| None`), `asyncio` nativo. |
| **Framework Web** | FastAPI + Starlette | `0.141.1` | API REST asíncrona, inyección de dependencias, `BackgroundTasks` y documentación OpenAPI (`/docs`). |
| **Servidor ASGI** | Uvicorn + `httptools` | `0.54.0` | Servidor de producción de alto rendimiento. |
| **ORM y Base de Datos** | SQLAlchemy (Async) + `asyncpg` | `2.1.1` / `0.31.0` | Motor relacional 100% asíncrono sobre **PostgreSQL**. |
| **Migraciones** | Alembic | `1.20.0` | Control de versiones del esquema de base de datos (ejecutado al arranque del contenedor). |
| **Validación y Config** | Pydantic + `pydantic-settings` | `2.13.5` / `2.15.0` | Validación de esquemas de Supercell y carga tipada de variables `.env`. |
| **Cliente HTTP** | HTTPX | `0.28.1` | Conexiones persistentes hacia Supercell (`cocproxy.royaleapi.dev`), LLMs, Tavily y Green-API. |
| **Programador (Cron)** | APScheduler | `3.11.3` | `AsyncIOScheduler` con disparadores por intervalo (`IntervalTrigger`) y fecha exacta (`DateTrigger`). |
| **Proveedores LLM** | Groq / NVIDIA / Anthropic | API REST | Inferencia híbrida con soporte para *Prompt Caching* efímero y *Parallel Tool Calling*. |
| **Mensajería** | Green-API (WhatsApp) | Webhook REST | Recepción de menciones `@Stacy` y despacho de reportes con formato de **Tarjetas Móviles**. |
| **Infraestructura** | Docker + Railway | `python:3.11-slim` | Despliegue continuo desde GitHub con contenedor PostgreSQL dedicado. |

---

## 🏗️ 3. Arquitectura General del Sistema

```
                    ┌──────────────────────────────────────────┐
                    │      API Oficial de Supercell (CoC)      │
                    │     (vía cocproxy.royaleapi.dev/v1)      │
                    └────────────────────┬─────────────────────┘
                                         │
              ┌──────────────────────────┴──────────────────────────┐
              ▼ (Sondeos programados)                               ▼ (Refresco en vivo <0.3s)
┌───────────────────────────────────┐                 ┌───────────────────────────────────┐
│     APScheduler (scheduler.py)    │                 │   Herramientas de S.T.A.C.Y.      │
│ • Capturas Clan: cada 60 min      │                 │        (stacy_tools.py)           │
│ • Guerra Clásica: cada 10 min     │                 │ • 10 Tools conectadas a BD + API  │
│ • CWL Liga: cada 10 min           │                 │ • Concurrencia Semaphore(6)       │
│ • Capital (2 Etapas): cada 1 min  │                 │ • Grafo de Memoria + Web Search   │
│ • DateTriggers: Inicio, 5h, 3h, F │                 └─────────────────┬─────────────────┘
└─────────────────┬─────────────────┘                                   ▲
                  │                                                     │
                  ▼                                                     ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                         PostgreSQL (15 Tablas — asyncpg / SQLAlchemy)                   │
│  [Roster/Héroes]   [Guerras/CWL]   [Capital/Forense]   [Directorio/Grafo/Telemetría WA] │
└─────────────────┬─────────────────────────────────────────────────────┬─────────────────┘
                  │                                                     ▲
                  ▼                                                     │
┌───────────────────────────────────┐                 ┌─────────────────┴─────────────────┐
│   Motor Proactivo (stacy_proactiva)│                │   Orquestador IA (stacy_ai.py)    │
│ • Alertas de Guerra (4 hitos)     │                 │ • Etapa 1: Bucle ReAct (1..3 it)  │
│ • Denuncia Forense Capital en vivo│                 │ • Etapa 2: Redactora S.T.A.C.Y.   │
└─────────────────┬─────────────────┘                 │ • Cola: Groq -> NVIDIA -> Claude  │
                  │                                   └─────────────────┬─────────────────┘
                  │                                                     ▲
                  └──────────────────────────┬──────────────────────────┘
                                             ▼
                    ┌──────────────────────────────────────────┐
                    │   Router WhatsApp (app/api/whatsapp.py)  │
                    │ • Escudo de Idempotencia (<15ms)         │
                    │ • BackgroundTasks + Semáforo IA          │
                    │ • Formateador Tarjetas Móviles (<=38 c.) │
                    └────────────────────┬─────────────────────┘
                                         │
                                         ▼
                    ┌──────────────────────────────────────────┐
                    │    Green-API  ◄───►  Grupos de WhatsApp  │
                    │    (Grupo Oficial + Grupo de Testeo)     │
                    └──────────────────────────────────────────┘
```

---

## 📂 4. Estructura del Repositorio

```text
ClanManager/
├── generar_contexto.py                  # Script local (ignorado en Git) para exportar el código a /contexto
├── contexto/                            # Carpeta local (ignorada en Git) con archivos .txt limpios
└── backend/                             # Root Directory del despliegue en Railway
    ├── Dockerfile                       # Imagen python:3.11-slim (ejecuta alembic upgrade head + uvicorn)
    ├── .dockerignore                    # Excluye .venv, __pycache__, .env y .git
    ├── alembic.ini                      # Configuración base de Alembic
    ├── requirements.txt                 # Dependencias fijadas del backend
    ├── probar_cliente.py                # Script CLI para pruebas rápidas de conexión con Supercell
    ├── alembic/
    │   ├── env.py                       # Entorno asíncrono de migraciones conectado a settings.database_url
    │   └── versions/                    # 9 migraciones secuenciales del esquema PostgreSQL
    │       ├── 2028717654be_crear_tablas_de_capturas.py
    │       ├── 9edac4aad473_agregar_rango_y_aldea_de_constructor_a_.py
    │       ├── ccc88d67134c_agregar_tablas_de_guerras.py
    │       ├── 8a59caa4d467_agregar_columnas_de_liga_de_guerras_a_.py
    │       ├── 4b9336b32128_agregar_tablas_de_asaltos_a_la_capital_.py
    │       ├── a6f9d5abb349_agregar_niveles_de_heroe_a_miembros_.py
    │       ├── dd4e69da0e33_agregar_enfrentamientos_del_grupo_de_la_.py
    │       ├── e8f1a2b3c4d5_integrar_stacy_y_auditoria.py
    │       └── f9a2b3c4d5e6_auditoria_forense_capital.py
    └── app/
        ├── main.py                      # Punto de entrada FastAPI, ciclo de vida HTTP/Scheduler y routers
        ├── config.py                    # Configuración centralizada con Pydantic Settings
        ├── scheduler.py                 # Programador autónomo APScheduler y DateTriggers dinámicos
        ├── db/
        │   ├── base.py                  # Clase DeclarativeBase de SQLAlchemy
        │   └── sesion.py                # Motor create_async_engine y fábrica de sesiones AsyncSession
        ├── models/                      # Modelos ORM de SQLAlchemy 2.1
        │   ├── __init__.py              # Registro centralizado en Base.metadata
        │   ├── captura.py               # Captura y CapturaMiembro
        │   ├── guerra.py                # Guerra, GuerraMiembro y GuerraAtaque
        │   ├── liga.py                  # LigaEnfrentamiento
        │   ├── asalto.py                # AsaltoCapital, AsaltoMiembro, AsaltoRegistro, AsaltoDistrito, AsaltoAtaque
        │   └── stacy.py                 # DirectorioMiembro, StacyNodoMemoria, StacyAristaGrafo, StacyMensajeWhatsapp
        ├── schemas/                     # Esquemas Pydantic v2 (entrada desde Supercell y salida de nuestra API)
        │   ├── clan.py                  # ClanOut
        │   ├── miembro.py               # MiembroOut (mapeo de los 6 héroes) y PuntoHistorialOut
        │   ├── captura.py               # CapturaOut y CapturaDetalleOut
        │   ├── evolucion.py             # EvolucionMiembroOut y EvolucionOut
        │   ├── guerra.py                # GuerraActualOut, BandoGuerraOut, MiembroGuerraOut, AtaqueGuerraOut
        │   ├── guerra_guardada.py       # GuerraResumenOut y GuerraDetalleOut
        │   ├── liga.py                  # ResumenLigaOut, ClanClasificacionOut, MiembroLigaOut
        │   ├── asalto.py                # AsaltoOut, RegistroCapitalOut, DistritoOut, AtaqueDistritoOut
        │   └── asalto_guardado.py       # AsaltoResumenOut y AsaltoDetalleOut
        ├── services/                    # Lógica de negocio, motores forenses e inteligencia artificial
        │   ├── clash_client.py          # Cliente HTTP asíncrono centralizado para la API de Clash of Clans
        │   ├── capturas.py              # Creación de capturas con asyncio.Semaphore(6) y cálculo de evolución
        │   ├── guerras.py               # Persistencia de guerras clásicas, CWL y corte de las 5 horas
        │   ├── liga.py                  # Clasificación de los 8 clanes de CWL y rendimiento por ronda
        │   ├── asaltos.py               # Sondeo de Capital en 2 etapas y motor forense de remates
        │   ├── migracion_pdfs.py        # Consolidación inicial y migración histórica de 6 guerras + 2 asaltos
        │   ├── stacy_knowledge.py       # Topes de héroes TH7-TH18, jerarquía de ligas y System Prompts E1/E2
        │   ├── stacy_tools.py           # Las 10 herramientas de datos en tiempo real de S.T.A.C.Y.
        │   ├── stacy_ai.py              # Orquestador híbrido ReAct en 2 etapas, Circuit Breaker y formateador móvil
        │   └── stacy_proactiva.py       # Despachador de anuncios automáticos de Guerra, CWL y Capital a WhatsApp
        └── api/                         # Routers de FastAPI (/api/...)
            ├── dependencias.py          # Alias de inyección: ClienteClash y SesionBD
            ├── clan.py                  # /api/clan
            ├── miembros.py              # /api/miembros
            ├── capturas.py              # /api/capturas
            ├── guerras.py               # /api/guerras
            ├── liga.py                  # /api/liga
            ├── asaltos.py               # /api/asaltos
            └── whatsapp.py              # /api/whatsapp (Webhook Green-API, Simulador, Directorio y Consolidación)
```

---

## 🗄️ 5. Modelo de Base de Datos en PostgreSQL (15 Tablas)

El esquema relacional consta de **14 tablas de dominio** más la tabla de control `alembic_version`. Todas las columnas de fecha y hora utilizan `DateTime(timezone=True)` estandarizadas en UTC.

### 5.1. Módulo de Capturas e Historial de Miembros (`app/models/captura.py`)

| Tabla | Clave Primaria / Restricciones | Columnas Principales | Propósito |
| :--- | :--- | :--- | :--- |
| **`capturas`** | `id` (PK) | `capturado_en`, `tag_clan`, `nombre_clan`, `nivel_clan`, `total_miembros` | Cabecera de cada instantánea horaria del clan. |
| **`capturas_miembros`** | `id` (PK)<br>`UNIQUE(captura_id, tag)` | `captura_id` (FK), `tag`, `nombre`, `rol`, `nivel_experiencia`, `nivel_ayuntamiento`, `trofeos`, `donaciones`, `donaciones_recibidas`, `liga`, `rango_clan`, `rango_clan_anterior`, `trofeos_base`, `liga_base`, `preferencia_guerra` (`in`/`out`), `estrellas_guerra`, `nivel_rey_barbaro`, `nivel_reina_arquera`, `nivel_gran_centinela`, `nivel_principe_esbirro`, `nivel_luchadora_real`, `nivel_duque_dragon` | Estado completo de cada miembro en el instante de la captura, incluyendo los **6 héroes de la aldea principal**. |

### 5.2. Módulo de Guerras Clásicas y CWL (`app/models/guerra.py` y `liga.py`)

| Tabla | Clave Primaria / Restricciones | Columnas Principales | Propósito |
| :--- | :--- | :--- | :--- |
| **`guerras`** | `id` (PK)<br>`UNIQUE(preparacion_inicio)`<br>`UNIQUE(war_tag)` | `estado`, `tamano_equipo`, `ataques_por_miembro`, `modificador_batalla`, `preparacion_inicio`, `inicio`, `fin`, `war_tag` (solo CWL), `liga_temporada`, `liga_ronda`, **`max_orden_5h`**, datos de `clan_*` y `rival_*`, `primera_captura_en`, `ultima_actualizacion_en` | Almacena tanto las guerras clásicas (`war_tag IS NULL`) como las guerras propias de cada ronda de CWL (`war_tag IS NOT NULL`). |
| **`guerra_miembros`** | `id` (PK)<br>`UNIQUE(guerra_id, tag)` | `guerra_id` (FK), `tag`, `nombre`, `nivel_ayuntamiento`, `posicion_mapa`, `es_propio` (`bool`), `ataques_recibidos` | Alineación completa de ambos bandos (`es_propio = True` para Melanie Stacy, `False` para el clan rival). |
| **`guerra_ataques`** | `id` (PK)<br>`UNIQUE(guerra_id, atacante_tag, orden)` | `guerra_id` (FK), `orden`, `atacante_tag`, `atacante_nombre`, `defensor_tag`, `defensor_nombre`, `estrellas`, `destruccion`, `duracion_segundos` | Registro individual de cada ataque realizado o recibido durante la guerra, ordenado globalmente por `orden`. |
| **`liga_enfrentamientos`** | `id` (PK)<br>`UNIQUE(war_tag)` | `temporada`, `ronda`, `war_tag`, `estado`, `tamano_equipo`, `inicio`, `fin`, datos de `clan_a_*` y `clan_b_*`, `actualizado_en` | Guarda los 28 enfrentamientos de los **8 clanes del grupo de CWL** a lo largo de las 7 rondas para calcular la tabla de posiciones. |

### 5.3. Módulo de Asaltos a la Capital del Clan (`app/models/asalto.py`)

| Tabla | Clave Primaria / Restricciones | Columnas Principales | Propósito |
| :--- | :--- | :--- | :--- |
| **`asaltos_capital`** | `id` (PK)<br>`UNIQUE(inicio)` | `estado`, `inicio`, `fin`, `oro_capital_total`, `asaltos_completados`, `ataques_totales`, `distritos_rivales_destruidos`, `recompensa_ofensiva`, `recompensa_defensiva` | Cabecera del fin de semana de asaltos (viernes 07:00 UTC a lunes 07:00 UTC). |
| **`asalto_miembros`** | `id` (PK)<br>`UNIQUE(asalto_id, tag)` | `asalto_id` (FK), `tag`, `nombre`, `ataques_usados`, `limite_ataques` ($5$), `ataques_bono` ($0$ o $1$), `oro_capital_saqueado` | Resumen oficial de participación y botín de cada jugador en el fin de semana. |
| **`asalto_registros`** | `id` (PK) | `asalto_id` (FK), `sentido` (`ofensivo`/`defensivo`), `clan_tag`, `clan_nombre`, `clan_nivel`, `ataques_usados`, `distritos_totales`, `distritos_destruidos` | Cada incursión ofensiva contra un clan enemigo (`attackLog`) o defensiva sufrida (`defenseLog`). |
| **`asalto_distritos`** | `id` (PK) | `registro_id` (FK), `distrito_id_juego`, `nombre`, `nivel`, `destruccion`, `estrellas`, `ataques_usados`, `saqueado` | Estado de cada distrito dentro de una incursión (`Capital Peak`, `Dragon Cliffs`, etc.). |
| **`asalto_ataques`** | `id` (PK) | `distrito_id` (FK), `atacante_tag`, `atacante_nombre`, `estrellas`, `destruccion`, **`detectado_en`**, **`orden_aparicion`** | Golpe individual con marca de tiempo exacta y orden de detección para la auditoría forense de remates. |

### 5.4. Módulo del Cerebro de S.T.A.C.Y. (`app/models/stacy.py`)

| Tabla | Clave Primaria / Restricciones | Columnas Principales | Propósito |
| :--- | :--- | :--- | :--- |
| **`directorio_miembros`** | `tag` (PK)<br>`UNIQUE(whatsapp_telefono)` | `tag`, `nombre`, `whatsapp_telefono`, `strikes_acumulados`, `notas_liderazgo`, `actualizado_en` | Vínculo permanente entre el `#TAG` de Supercell y el número de WhatsApp del miembro para reconocimiento de identidad y nivel de acceso. |
| **`stacy_nodos_memoria`** | `id` (PK) | `tipo_nodo` (`JUGADOR`, `ENTIDAD`, etc.), `referencia_tag`, `nombre_entidad`, `propiedades` (`JSONB`), `creado_en` | Vértices del Grafo de Memoria de S.T.A.C.Y. |
| **`stacy_aristas_grafo`** | `id` (PK) | `nodo_origen_id` (FK), `tipo_relacion` (`CAMBIO_ESPEJO_CON`, `TIENE_AUSENCIA_JUSTIFICADA`, `ES_CUENTA_SECUNDARIA_DE`, `NOTA_TACTICA`), `nodo_destino_id` (FK), `guerra_id` (FK), `registrado_por`, `nota_explicativa`, `es_activa`, `creado_en`, `expira_en` | Relaciones dirigidas ($\text{Sujeto} \xrightarrow{\text{Relación}} \text{Objeto}$) que S.T.A.C.Y. consulta en tiempo real durante sus auditorías. |
| **`stacy_mensajes_whatsapp`** | `id_message_wa` (PK) | `chat_id`, `telefono_remitente`, `nombre_whatsapp`, `jugador_tag_vinculado`, `nivel_acceso_aplicado`, `mensaje_usuario`, `respuesta_stacy`, `modelo_etapa_1`, `modelo_etapa_2`, `herramientas_usadas` (`JSONB`), `tokens_totales`, `costo_total_usd`, `latencia_segundos`, `creado_en` | Cumple 3 funciones simultáneas: **1)** Escudo de idempotencia ante reintentos de Green-API, **2)** Memoria conversacional de corto plazo por grupo, y **3)** Auditoría de costos y latencia. |

---

## 🔄 6. Historial de Migraciones de Alembic

El esquema se construye automáticamente mediante 9 revisiones encadenadas en `backend/alembic/versions/`:

1. **`2028717654be`** — Creación de las tablas iniciales `capturas` y `capturas_miembros`.
2. **`9edac4aad473`** — Adición de `rango_clan`, `rango_clan_anterior`, `trofeos_base` y `liga_base` a `capturas_miembros`.
3. **`ccc88d67134c`** — Creación de las tablas `guerras`, `guerra_miembros` y `guerra_ataques`.
4. **`8a59caa4d467`** — Soporte para CWL en `guerras` (`war_tag`, `liga_temporada`, `liga_ronda`).
5. **`4b9336b32128`** — Creación de las 5 tablas jerárquicas de la Capital del Clan (`asaltos_capital`, `asalto_miembros`, `asalto_registros`, `asalto_distritos`, `asalto_ataques`).
6. **`a6f9d5abb349`** — Adición de los 6 héroes de la aldea principal a `capturas_miembros` (`nivel_rey_barbaro`, `nivel_reina_arquera`, `nivel_gran_centinela`, `nivel_principe_esbirro`, `nivel_luchadora_real`, `nivel_duque_dragon`).
7. **`dd4e69da0e33`** — Creación de la tabla `liga_enfrentamientos` para el seguimiento completo del grupo de 8 clanes en CWL.
8. **`e8f1a2b3c4d5`** — Integración de S.T.A.C.Y. v3.0 (`directorio_miembros`, `stacy_nodos_memoria`, `stacy_aristas_grafo`, `stacy_mensajes_whatsapp`), `max_orden_5h` en `guerras`, y `preferencia_guerra`/`estrellas_guerra` en `capturas_miembros`.
9. **`f9a2b3c4d5e6`** — Adición de `detectado_en` y `orden_aparicion` en `asalto_ataques` para la auditoría forense de la Capital del Clan.

---

## 🧠 7. El Cerebro de S.T.A.C.Y. v3.0 (Arquitectura Híbrida ReAct)

El motor de Inteligencia Artificial (`app/services/stacy_ai.py` y `stacy_knowledge.py`) procesa cada mensaje etiquetado con `@Stacy` a través de un pipeline desacoplado en **2 Etapas con verificación iterativa ReAct**:

### 7.1. Identificación del Remitente y Protocolo Social
Antes de invocar al modelo, `identificar_miembro_por_telefono` cruza los últimos $9$ dígitos del número de WhatsApp del remitente contra `directorio_miembros` y la última `Captura`:
* **`ALTO MANDO` (`Líder`, `Colíder`, `Veterano`):** S.T.A.C.Y. le habla de tú a tú como colega de mando, entregando diagnósticos listos para la toma de decisiones.
* **`MIEMBRO REGULAR` (`Miembro`):** Trato de compañera de clan con exigencia táctica.
* **`NO_VINCULADO`:** Usuario cuyo teléfono aún no figura en `directorio_miembros`. S.T.A.C.Y. responde consultas generales del clan, pero si el usuario pregunta en primera persona (*"¿Cuál es mi espejo?"*, *"¿Cómo van mis héroes?"*) sin dar su nick, aplica un cortocircuito (`PASS_STAGE_2`) y le recuerda con ironía que primero debe vincular su número con un colíder.

### 7.2. Etapa 1: Bucle Agéntico ReAct (`MAX_ITERACIONES_ETAPA_1 = 3`)
* En la **Ronda 1**, el modelo analiza el mensaje, la identidad del remitente y las últimas $4$ interacciones del chat (`_obtener_memoria_corto_plazo`), pudiendo invocar **una o múltiples herramientas en paralelo** (*Parallel Tool Calling*).
* Si el mensaje es charla casual o broma, emite `PASS_STAGE_2` y salta sin ejecutar consultas SQL.
* En las **Rondas 2 y 3**, el motor recibe los datos recolectados en la iteración previa y realiza una **Verificación de Suficiencia**:
  * Si necesita cruzar datos adicionales (por ejemplo, vio quiénes no han atacado en guerra y ahora necesita consultar sus héroes o acuerdos en el grafo), invoca la herramienta faltante.
  * Un filtro de firmas (`firmas_ejecutadas`) impide que se ejecute dos veces la misma herramienta con los mismos argumentos.
  * Cuando la información cubre el $100\%$ de la consulta, emite `DATOS_COMPLETOS` y avanza a la Etapa 2.

### 7.3. Etapa 2: Redacción Táctica y Estándar de "Tarjetas Móviles"
* Recibe todos los datos verificados en formato de tablas compactas separadas por `|` (ahorrando $\sim 75\%$ de tokens).
* Redacta siguiendo reglas lingüísticas estrictas en español (sin repetir datos personales del remitente si no preguntó por sí mismo y sin mostrar códigos internos de programación).
* **Diseño para Pantalla Móvil ($\le 38$ caracteres por línea):** Tanto el System Prompt como el post-procesador automático `_limpiar_formato_whatsapp` dividen cualquier viñeta densa en una **Tarjeta Móvil de 2 líneas** (`• Encabezado` arriba y `  └ Detalle` abajo) para evitar saltos de línea rotos en celulares.

### 7.4. Colas en Cascada y *Circuit Breaker* (`HTTP 429`)
Ambas etapas recorren una lista priorizada de proveedores (`GROQ` $\rightarrow$ `NVIDIA` $\rightarrow$ `ANTHROPIC`). Si un modelo responde `HTTP 429 (Rate Limit)`, el diccionario `_CIRCUIT_BREAKER_429` lo pone en enfriamiento durante $60\text{ segundos}$ para que las siguientes consultas salten directamente al siguiente modelo disponible sin perder tiempo.

| Orden | Etapa 1 (Razonamiento ReAct y Tools) | Etapa 2 (Redactora Táctica S.T.A.C.Y.) |
| :---: | :--- | :--- |
| **1°** | `GROQ` — `openai/gpt-oss-120b` | `GROQ` — `openai/gpt-oss-120b` |
| **2°** | `GROQ` — `qwen/qwen3-32b` | `GROQ` — `qwen/qwen3-32b` |
| **3°** | `NVIDIA` — `meta/llama-4-maverick-17b-128e-instruct` | `NVIDIA` — `meta/llama-4-maverick-17b-128e-instruct` |
| **4°** | `GROQ` — `openai/gpt-oss-20b` | `GROQ` — `meta-llama/llama-4-scout-17b-16e-instruct` |
| **5°** | `ANTHROPIC` — `claude-sonnet-5-5` *(Prompt Caching)* | `ANTHROPIC` — `claude-sonnet-5-5` *(Prompt Caching)* |
| **6°** | `ANTHROPIC` — `claude-haiku-5-5` *(Prompt Caching)* | `ANTHROPIC` — `claude-haiku-5-5` *(Prompt Caching)* |

---

## 🛠️ 8. Catálogo de las 10 Herramientas de S.T.A.C.Y.

Definidas en `app/services/stacy_ai.py` e implementadas en `app/services/stacy_tools.py`:

| # | Nombre de la Herramienta | Parámetros de Entrada | Estrategia de Refresco en Tiempo Real y Salida |
| :-: | :--- | :--- | :--- |
| **1** | `consultar_guerra_actual` | `periodo` (`actual`, `pasada`, `historial`), `filtro` (`todos`, `pendientes`, `infractores`, `plenos`, `resumen`), `nombre_jugador`, `rival` | En `periodo='actual'`, sincroniza en vivo con Supercell ($\sim 0.2\text{ s}$) antes de leer PostgreSQL. Si el clan está en CWL, sincroniza la ronda activa. En `periodo='historial'`, calcula el acumulado histórico de todas las guerras finalizadas. |
| **2** | `consultar_bases_rivales` | `periodo` (`actual`, `pasada`), `estado` (`abiertas`, `intactas`, `cerradas`, `todas`), `th` | Sincroniza en vivo y devuelve la lista de aldeas enemigas filtrada por estado de destrucción y nivel de Ayuntamiento, indicando quién es nuestro espejo asignado. |
| **3** | `consultar_cwl_liga` | `temporada` (opcional, ej. `2026-11`) | Ejecuta `guardar_liga_actual` en vivo y devuelve la tabla de posiciones de los 8 clanes (estrellas de combate $+$ bono de $+10$ por victoria) y el rendimiento acumulado de nuestros miembros. |
| **4** | `consultar_miembros_heroes` | `nombre_jugador`, `th`, `estado_guerra` (`todos`, `activos`, `rojo`), `rango`, `ordenar_por` (`orden_clan`, `mas_rusheados`, `mejores_heroes`, `mas_donaciones`, `mas_estrellas`), `limite` | Si la última captura tiene $>180\text{ s}$, descarga una nueva en $\sim 1.5\text{ s}$ usando `asyncio.Semaphore(6)`. Calcula el porcentaje de progreso de los 6 héroes frente al tope de su TH. |
| **5** | `consultar_jugador_en_vivo` | `nombre_o_tag` *(obligatorio)* | Consulta directamente `/players/{tag}` en Supercell para extraer datos que solo existen en vivo: **equipamiento activo de héroes y sus niveles**, puntos históricos en Juegos del Clan (`Games Champion`), oro contribuido a la Capital y ataques ganados en la temporada. |
| **6** | `consultar_asaltos_capital` | `tipo_consulta` (`ranking`, `bitacora`), `filtro` (`todos`, `sin_atacar`, `incompletos`, `turistas`, `top_oro`), `nombre_jugador` | Sincroniza en vivo la temporada actual de Capital y ejecuta el **Motor Forense (`construir_auditoria_capital`)**, entregando expedientes individuales, infractores de remate, detección de *Turistas* y bitácora golpe a golpe. |
| **7** | `consultar_historial_ligas` | `nombre_jugador` (opcional) | Compara la captura más reciente contra la captura histórica anterior ($\ge 1\text{ h}$) utilizando la fórmula matemática de jerarquía de las 13 Ligas de Tropas (`SUBIO`, `BAJO`, `IGUAL`). |
| **8** | `gestionar_memoria_grafo` | `accion` (`consultar`, `guardar_relaciones`), `sujeto`, `tipo_relacion`, `objeto`, `nota_explicativa` | Permite crear o leer nodos y aristas en `stacy_nodos_memoria` y `stacy_aristas_grafo` (`CAMBIO_ESPEJO_CON`, `TIENE_AUSENCIA_JUSTIFICADA`, `ES_CUENTA_SECUNDARIA_DE`, `NOTA_TACTICA`). |
| **9** | `consultar_guia_estrategica_coc` | `categoria` (`heroes_y_equipamiento_meta`, `estrategias_ataque_por_th`, `economia_y_eventos_2026`, `capital_y_modos_clan`, `normativa_y_rangos_stacy`) | Biblioteca táctica modular con las combinaciones meta de equipamiento, ejércitos por TH, guía de *Hammer Jam* y reglamento oficial del clan. |
| **10** | `buscar_en_internet` | `consulta` *(obligatorio)* | Búsqueda web asíncrona en cascada (**1° Tavily AI Search** $\rightarrow$ **2° Google Custom Search JSON API**) para parches recientes, notas de versión o fechas de eventos. |

---

## ⚖️ 9. Motores de Auditoría Táctica y Forense

### 9.1. Auditoría de Guerra Clásica (Regla de las 5 Horas)
En las guerras clásicas ($2$ ataques por miembro), el reglamento de **Melanie Stacy** exige que durante las **primeras 5 horas del Día de Batalla** el primer ataque sea exclusivamente contra el espejo directo ($\text{Posición } \#X \text{ vs } \#X$).

1. **Sellado Automático de `max_orden_5h` (`app/services/guerras.py`):**
   Cada vez que se actualiza la guerra mientras la hora actual cumple:
   $$\text{ahora\_utc} \le \text{guerra.inicio} + 5\text{ horas}$$
   el sistema calcula el mayor número de orden global (`atk.orden`) registrado hasta ese instante y actualiza `guerra.max_orden_5h`:
   $$\text{max\_orden\_5h} = \max\left(\text{max\_orden\_5h\_previo}, \max_{a \in \text{ataques}}(a.\text{orden})\right)$$
2. **Evaluación de Infracciones y Exenciones del Grafo (`_reconstruir_estado_guerra`):**
   Para cada ataque propio con $\text{orden} \le \text{max\_orden\_5h}$:
   * Si es el **1.er tiro** y $\text{pos\_defensor} \ne \text{pos\_atacante}$, verifica primero si existe una arista activa `CAMBIO_ESPEJO_CON` en `stacy_aristas_grafo` entre el atacante y el dueño de ese espejo. Si no existe autorización, registra: `Infraccion(<5h): Ataco #Y ignorando espejo #X`.
   * Si es el **2.º tiro** realizado dentro del corte de las $5\text{ horas}$ ($\text{orden} \le \text{max\_orden\_5h}$) fuera de su espejo, registra: `Infraccion(<5h): 2do tiro a #Y antes de las 5h`.

---

### 9.2. Motor de Liga de Guerras de Clanes (CWL)
Durante la semana de CWL (`app/services/guerras.py`, `liga.py` y `stacy_tools.py`):

1. **Orientación Automática de Bando (`_orientar_hacia_nuestro_clan`):** En el endpoint `/clanwarleagues/wars/{warTag}`, Supercell puede entregar a nuestro clan dentro del objeto `"opponent"`. El servicio invierte automáticamente `"clan"` y `"opponent"` cuando detecta nuestro tag `#89YVP0RG` del lado rival.
2. **Normalización de Posiciones de Mapa ($1 \dots 15$):** Como Supercell envía en `mapPosition` el índice del jugador dentro de la lista maestra de $48$ inscritos en la liga (ej. $1, 3, 4, 8 \dots$), `_reconstruir_estado_guerra` re-indexa a los convocados de cada ronda del `#1` al `#15` (o `#30`) para coincidir exactamente con el mapa del juego.
3. **Prioridad de Ronda en Batalla (`inWar` sobre `preparation`):** Dado que en CWL el Día de Batalla de la Ronda $N$ ocurre simultáneamente con el Día de Preparación de la Ronda $N+1$, `_obtener_guerra_objetivo` prioriza siempre la guerra en estado `inWar`.
4. **Cálculo de la Clasificación de los 8 Clanes (`calcular_clasificacion`):**
   Para cada uno de los 8 clanes del grupo:
   $$\text{Estrellas Totales} = \sum \text{Estrellas en Combate} + 10 \times \text{Victorias Finalizadas}$$
   $$\text{Destrucción Total} = \sum_{r \in \text{rondas}} \text{round}\left(\text{Destrucción Promedio}_r \times \text{Tamaño Equipo}_r\right)$$

---

### 9.3. Sondeo en 2 Etapas y Auditoría Forense de la Capital del Clan
Para detectar en tiempo real quién incumple la prohibición de dejar distritos sin rematar teniendo ataques disponibles (`app/services/asaltos.py`), el sistema opera con una arquitectura de **2 Etapas cada 1 minuto** durante el fin de semana:

#### Etapa 1 (Centinela en Memoria RAM — Cero escrituras en BD)
Cada $60\text{ segundos}$, `sondear_asalto_dos_etapas` consulta el último asalto en Supercell y compara la tupla $(\text{totalAttacks}, \text{state})$ contra el diccionario en memoria `_CACHE_ETAPA1_CAPITAL`:
* Si $\text{totalAttacks}$ no ha cambiado respecto al minuto anterior, **termina en $<1\text{ ms}$ sin ejecutar ninguna consulta ni escritura en PostgreSQL**.
* Si $\text{totalAttacks}$ aumentó, activa la **Etapa 2**.

#### Etapa 2 (Persistencia de Timestamps y Motor Forense)
1. **Inmunidad de Timestamps (`_guardar_desde_raw_preservando_timestamps`):** Antes de actualizar los registros del asalto, guarda en memoria las marcas `(detectado_en, orden_aparicion)` de todos los golpes previos usando la clave inmutable:
   $$(\text{sentido}, \text{clan\_tag}, \text{clan\_nombre}, \text{distrito\_id\_juego}, \text{atacante\_tag}, \text{destruccion})$$
   De esta forma, los golpes antiguos conservan su hora original y únicamente los golpes nuevos reciben `detectado_en = now()` y un número correlativo `orden_aparicion` creciente.
2. **Reconstrucción Cronológica de Tiros (`1/6` a `6/6`):**
   * Ordena las incursiones ofensivas desde la primera hasta la actual en curso (`_ordenar_incursiones_cronologicamente`).
   * Ordena los golpes de cada jugador priorizando `incursion_num`, luego `orden_aparicion > 0` (capturados minuto a minuto) y, en caso de empate en golpes históricos (`orden_aparicion == 0`) dentro de una misma incursión, coloca los distritos cerrados al $100\%$ antes que el distrito inconcluso final para nunca confundir una apertura+remate con el último tiro donde se quedó sin ataques.
   * Calcula después de cada golpe los **tiros restantes disponibles** del jugador:
     $$\text{Restantes}_i = \max\left(0, (\text{Límite Base} + \text{Bono Desbloqueado}) - i\right)$$
3. **Las 3 Reglas Disciplinarias de Capital (`construir_auditoria_capital`):**
   Un distrito se considera en **franja de remate** cuando el jugador lo deja en $\ge 70\%$ (o $\ge 65\%$ tras $\ge 2$ golpes propios y el siguiente compañero lo cierra de un solo tiro al $100\%$):
   * **Regla 1 — `Abandono de distrito con ataques disponibles`:** El jugador deja un distrito en franja de remate ($\ge 70\%$), le quedan $\text{tiros\_restantes} > 0$, y en su siguiente tiro aparece atacando un distrito distinto.
   * **Regla 2 — `Doble distrito sin rematar (máximo permitido: 1 al quedarte sin tiros)`:** El jugador acumula $2$ o más distritos inconclusos en la misma jornada (al menos uno en franja de remate $\ge 70\%$ y otro $\ge 50\%$ habiendo tenido tiros libres).
   * **Regla 3 — `Distrito dejado a medias con ataques sin usar`:** El jugador deja un distrito en $\ge 80\%$ quedándole tiros disponibles sin gastar, y otro compañero se ve obligado a cerrarlo o transcurren $\ge 15\text{ minutos}$ de desconexión.

---

### 9.4. Descarga Concurrente de los 6 Héroes y Jerarquía de Ligas

#### A. Semáforo Asíncrono para Perfiles (`app/services/capturas.py`)
Para enriquecer a los 50 miembros con sus 6 héroes sin disparar un bloqueo `HTTP 429` de Supercell, `crear_captura` utiliza `asyncio.Semaphore(6)` con una micro-pausa de $50\text{ ms}$. Esto procesa el clan completo en **$\sim 1.5\text{ segundos}$** ($6$ veces más rápido que en serie y $100\%$ seguro).

#### B. Cálculo de Progreso de los 6 Héroes (`app/services/stacy_tools.py`)
Para cada miembro con nivel de Ayuntamiento $TH \in [7, 18]$, se compara la suma de sus 6 héroes actuales (`RB`, `RA`, `GC`, `LR`, `PE`, `DD`) contra la suma de los topes máximos de su TH (`TOPES_HEROES_TH`):

$$\text{Progreso Héroes (\%)} = \text{round}\left( \frac{\text{RB} + \text{RA} + \text{GC} + \text{LR} + \text{PE} + \text{DD}}{\sum_{h \in \text{TOPES}_{TH}} h} \times 100,\ 1 \right)$$

* **Clasificación automática:** `MAX` ($100\%$), `SOLIDO` ($85\% - 99.9\%$), `MEDIO` ($65\% - 84.9\%$), `RUSH` ($< 65\%$).

#### C. Fórmula de Jerarquía de las 13 Ligas de Tropas (`_calcular_puntaje_jerarquia`)
Para ordenar y comparar el progreso competitivo semanal entre capturas, cada miembro recibe un puntaje entero determinista:

$$\text{Score} = (\text{Peso Franja} \times 10,000,000) + (\text{División Numérica} \times 100,000) + \text{Trofeos}$$

Donde $\text{Peso Franja} \in [1, 13]$ sigue el orden oficial: `Unranked` ($1$) $\rightarrow$ `Skeleton` ($2$) $\rightarrow \dots \rightarrow$ `Electro` ($12$) $\rightarrow$ `Legend` ($13$).

---

## ⏰ 10. Programador Autónomo (`APScheduler`) y Alertas Proactivas en WhatsApp

Al arrancar FastAPI (`app/main.py` $\rightarrow$ `ciclo_de_vida`), se inicia `AsyncIOScheduler` (`app/scheduler.py`) con **4 trabajos base de intervalo** y **4 disparadores dinámicos por fecha (`DateTrigger`)**:

### 10.1. Trabajos Periódicos Base (`IntervalTrigger`)

| ID del Job | Función Ejecutada | Intervalo por Defecto | Comportamiento Inteligente |
| :--- | :--- | :---: | :--- |
| `captura_periodica` | `capturar_periodicamente` | Cada **60 min** | Descarga el estado del clan y los 6 héroes de todos los miembros y guarda una nueva fila en `capturas`. |
| `captura_guerra_periodica` | `capturar_guerra_periodicamente` | Cada **10 min** | Si la guerra está en `preparation`, agenda los `DateTrigger` futuros y ahorra llamadas a la API hasta que empiece `inWar`. En batalla, actualiza `guerras` y el corte `max_orden_5h`. |
| `captura_liga_periodica` | `capturar_liga_una_vez` | Cada **10 min** | Sondea el grupo de CWL, actualiza `liga_enfrentamientos` y las guerras propias, omitiendo las rondas ya terminadas (`_ya_es_definitiva`), y agenda las alertas de cada ronda. |
| `captura_asalto_periodica` | `capturar_asalto_periodicamente` | Cada **1 min** | Solo se activa dentro de la ventana de fin de semana (viernes 07:00 UTC a lunes 07:15 UTC). Ejecuta la **Etapa 1 en RAM** cada minuto y, si hay nuevos ataques, corre la **Etapa 2 + Auditoría Proactiva de WhatsApp**. |

### 10.2. Hitos Proactivos de Guerra y CWL (`DateTrigger` en `stacy_proactiva.py`)

Cada vez que el programador detecta una guerra clásica o una ronda de CWL, agenda automáticamente en `APScheduler`:

1. **`INICIO` ($\text{inicio} + 1\text{ min}$):** Anuncia el arranque del Día de Batalla y recuerda la regla de espejo (primeras $5\text{ h}$ en guerra clásica o $24\text{ h}$ en CWL).
2. **`CORTE_5H` ($\text{inicio} + 5\text{ h } 1\text{ min}$, solo Guerra Clásica):** Sondea la guerra para sellar `max_orden_5h`, anuncia la apertura oficial del **Mapa Libre**, felicita a quienes ya lograron pleno y exhibe si hubo infractores en las primeras $5\text{ h}$.
3. **`ULTIMAS_3H` ($\text{fin} - 3\text{ horas}$):** Alerta roja de recta final pasando lista nominal de los miembros que siguen con ataques pendientes (`0/2`, `1/2` o `0/1` en CWL).
4. **`FINAL` ($\text{fin} + 2\text{ min}$):** Ejecuta la captura definitiva al terminar la guerra y publica el informe ejecutivo de cierre (veredicto final, cuadro de honor de plenos, infractores de espejo y tiros colgados).

> **Idempotencia Proactiva:** Todos los anuncios automáticos se registran en `stacy_mensajes_whatsapp` con clave primaria `PROACTIVO_WAR_{guerra_id}_{EVENTO}` o `PROACTIVO_CAP_{asalto_id}_{TAG}_C{CARGOS}` para garantizar que nunca se envíe dos veces el mismo aviso aunque el servidor se reinicie.

---

## 🌐 11. Referencia Completa de la API REST (Endpoints)

La documentación interactiva Swagger UI está disponible en `/docs` y la comprobación de salud en `GET /salud`.

### 11.1. Router de WhatsApp y S.T.A.C.Y. (`/api/whatsapp`)
| Método | Ruta | Descripción |
| :---: | :--- | :--- |
| `GET` | `/api/whatsapp/webhook` | Verificación de estado activo del Webhook de S.T.A.C.Y. v3.0. |
| `POST` | `/api/whatsapp/webhook` | **Webhook Principal para Green-API.** Filtra menciones a `@Stacy`, valida idempotencia en $<15\text{ ms}$ y encola la respuesta en `BackgroundTasks`. |
| `POST` | `/api/whatsapp/simular` | Simulador interactivo para probar consultas a S.T.A.C.Y. desde `/docs` sin enviar mensajes por WhatsApp. |
| `GET` | `/api/whatsapp/directorio` | Exporta en JSON la lista completa de miembros con sus teléfonos vinculados y strikes desde `directorio_miembros`. |
| `POST` | `/api/whatsapp/directorio` | Registra o actualiza masivamente el vínculo `#TAG <-> Teléfono de WhatsApp` en PostgreSQL. |
| `POST` | `/api/whatsapp/vincular-webhook` | Configura automáticamente en Green-API (`setSettings`) la URL pública de Railway como destino de los webhooks entrantes. |
| `POST` | `/api/whatsapp/consolidar-historial` | Ejecuta el Primer Pase de Consolidación (captura actual, guerra actual, últimas 10 temporadas de Capital) y migra las 6 guerras históricas + 2 asaltos de respaldo. 100% idempotente. |
| `POST` | `/api/whatsapp/probar-alerta-proactiva` | Dispara manualmente hacia el grupo de WhatsApp cualquiera de los 4 anuncios de guerra (`INICIO`, `CORTE_5H`, `ULTIMAS_3H`, `FINAL`). |
| `POST` | `/api/whatsapp/auditar-capital` | Ejecuta en vivo la Etapa 2 y el Motor Forense de Capital, devolviendo el JSON de `infractores_confirmados` y enviando opcionalmente la alerta a WhatsApp (`enviar_a_whatsapp=True`). |

### 11.2. Routers de Datos del Clan (`/api/clan`, `/api/miembros`, `/api/capturas`)
| Método | Ruta | Descripción |
| :---: | :--- | :--- |
| `GET` | `/api/clan` | Resumen general del clan en vivo desde Supercell (`ClanOut`). |
| `GET` | `/api/miembros` | Lista actual de miembros en vivo desde Supercell (`list[MiembroOut]`). |
| `GET` | `/api/miembros/{tag}/historial` | Historial de un jugador a través de todas las capturas guardadas. |
| `GET` | `/api/miembros/evolucion` | Compara el delta de donaciones, trofeos y rango entre dos fechas (`desde`, `hasta`). |
| `POST` | `/api/capturas` | Fuerza la creación inmediata de una captura completa del clan con los 6 héroes. |
| `GET` | `/api/capturas` | Lista las cabeceras de las capturas históricas guardadas. |
| `GET` | `/api/capturas/ultima` | Devuelve la captura más reciente con el detalle completo de sus miembros. |
| `GET` | `/api/capturas/{captura_id}` | Devuelve una captura específica con todos sus miembros. |

### 11.3. Routers de Guerras, CWL y Capital (`/api/guerras`, `/api/liga`, `/api/asaltos`)
| Método | Ruta | Descripción |
| :---: | :--- | :--- |
| `GET` | `/api/guerras/actual` | Consulta la guerra clásica actual en vivo desde Supercell. |
| `POST` | `/api/guerras/actual` | Fuerza un sondeo de la guerra clásica actual y la guarda/actualiza en PostgreSQL. |
| `GET` | `/api/guerras/registro` | Devuelve el `/warlog` público de Supercell. |
| `GET` | `/api/guerras/historial` | Lista las guerras clásicas guardadas en PostgreSQL (`war_tag IS NULL`). |
| `GET` | `/api/guerras/historial/{guerra_id}` | Devuelve el detalle completo de una guerra guardada (con miembros y ataques). |
| `GET` | `/api/liga/resumen` | Devuelve la temporada de CWL completa: clasificación de los 8 clanes, enfrentamientos y rendimiento por miembro. |
| `POST` | `/api/liga/sondeo` | Fuerza un sondeo en vivo del grupo de CWL actual en Supercell. |
| `GET` | `/api/asaltos/actual` | Devuelve el fin de semana de asaltos actual en vivo desde Supercell. |
| `GET` | `/api/asaltos` | Lista las últimas temporadas de asaltos disponibles en la API de Supercell. |
| `GET` | `/api/asaltos/historial` | Lista los fines de semana de asaltos guardados en PostgreSQL. |
| `GET` | `/api/asaltos/historial/{asalto_id}` | Devuelve el detalle completo de un asalto guardado (miembros, incursiones, distritos y ataques). |

---

## ⚙️ 12. Configuración y Variables de Entorno (`.env`)

El archivo `backend/app/config.py` gestiona todas las variables mediante `pydantic-settings`. Incluye el validador `asegurar_driver_asyncpg` que transforma automáticamente cualquier URL `postgres://` o `postgresql://` inyectada por Railway al formato asíncrono `postgresql+asyncpg://`.

Plantilla de archivo `backend/.env`:

```env
# --- SUPERCELL / CLASH OF CLANS ---
COC_TOKEN=tu_jwt_token_de_royaleapi_o_supercell
CLAN_TAG=89YVP0RG
COC_BASE_URL=https://cocproxy.royaleapi.dev/v1
COC_TIMEOUT=10.0

# --- BASE DE DATOS POSTGRESQL ---
# En local (Docker): postgresql+asyncpg://clanmanager:clanmanager@localhost:5432/clanmanager
# En Railway: ${{Postgres.DATABASE_URL}}
DATABASE_URL=postgresql+asyncpg://clanmanager:clanmanager@localhost:5432/clanmanager

# --- MOTORES DE IA (S.T.A.C.Y. v3.0) ---
GROQ_API_KEY=gsk_...
NVIDIA_API_KEY=nvapi-...
ANTHROPIC_API_KEY=sk-ant-...
MOSTRAR_FIRMA_MODELO=true

# --- BÚSQUEDA WEB EN CASCADA (TAVILY -> GOOGLE) ---
TAVILY_API_KEY=tvly-...
GOOGLE_SEARCH_API_KEY=AIza...
GOOGLE_SEARCH_CX=tu_search_engine_id

# --- WHATSAPP (GREEN-API) ---
BOT_PHONE_NUMBER=51922982880
GREEN_API_URL=https://7107.api.greenapi.com
GREEN_ID_INSTANCE=710722767009
GREEN_API_TOKEN=tu_green_api_token
# Lista separada por comas: [0] Grupo de Testeo, [1] Grupo Oficial del Clan
ALLOWED_GROUP_ID=120363431111208861@g.us,120363425443122313@g.us
```

---

## 🚀 13. Despliegue en Producción (Docker & Railway)

### 13.1. Flujo de Construcción (`backend/Dockerfile`)
El contenedor de producción utiliza `python:3.11-slim`, instala las dependencias de `requirements.txt` en caché de capas y define como comando de arranque:

```dockerfile
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```
Gracias a este diseño, **cada vez que se hace `git push origin main`**, Railway construye la nueva imagen, aplica cualquier migración pendiente de Alembic sobre PostgreSQL de forma transaccional y levanta Uvicorn + APScheduler sin intervención manual.

### 13.2. Configuración en Railway
1. **Servicio `Postgres`:** Contenedor oficial de PostgreSQL con volumen persistente.
2. **Servicio `ClanManager` (GitHub Repo):**
   * **Root Directory:** `/backend`
   * **Branch vinculada:** `main` (Despliegue continuo activado).
   * **Variable `DATABASE_URL`:** Referencia directa a `${{Postgres.DATABASE_URL}}`.
   * **Networking:** Dominio público HTTPS conectado al puerto dinámico `${PORT}`.

---

## 🔧 14. Operación, Consultas SQL Útiles y Mantenimiento

### 14.1. Cómo usar el Grafo de Memoria desde WhatsApp
Cualquier miembro del **Alto Mando** puede pedirle a `@Stacy` en lenguaje natural que guarde o consulte acuerdos:
* **Guardar un cambio de espejo:** *"@Stacy anota en tu memoria que Jhadzel cambió espejo con Alejandromm11 para esta guerra."*
* **Guardar una ausencia justificada:** *"@Stacy guarda en memoria que Castro tiene ausencia justificada este fin de semana por viaje."*
* **Consultar recuerdos vigentes:** *"@Stacy ¿qué acuerdos o notas tácticas tienes guardados en tu grafo de memoria?"*

### 14.2. Script Local de Exportación de Contexto (`generar_contexto.py`)
Para generar volcados `.txt` limpios del código fuente (excluyendo `.venv`, `__pycache__` y `.env`) dentro de la carpeta local `contexto/` (ignorada por Git):

```powershell
python generar_contexto.py
```
Genera 4 archivos en `/contexto`:
* `backend_limpio.txt` (Todo el backend consolidado).
* `01_modelos_y_migraciones.txt` (Alembic, modelos SQLAlchemy y esquemas Pydantic).
* `02_servicios_y_stacy.txt` (Servicios del clan, motores forenses y cerebro de S.T.A.C.Y.).
* `03_api_scheduler_y_config.txt` (Routers FastAPI, `scheduler.py`, `config.py` y `Dockerfile`).

### 14.3. Consultas SQL de Diagnóstico Rápido en Railway

* **Ver las últimas 20 interacciones y costos de S.T.A.C.Y. en WhatsApp:**
  ```sql
  SELECT creado_en, nombre_whatsapp, nivel_acceso_aplicado, modelo_etapa_1, modelo_etapa_2,
         herramientas_usadas, tokens_totales, ROUND(costo_total_usd::numeric, 4) AS usd,
         latencia_segundos AS seg
  FROM stacy_mensajes_whatsapp
  ORDER BY creado_en DESC
  LIMIT 20;
  ```

* **Ver el directorio de miembros vinculados y sus strikes:**
  ```sql
  SELECT tag, nombre, whatsapp_telefono, strikes_acumulados, actualizado_en
  FROM directorio_miembros
  ORDER BY nombre ASC;
  ```

* **Consultar los acuerdos activos en el Grafo de Memoria:**
  ```sql
  SELECT a.id, n1.nombre_entidad AS origen, a.tipo_relacion, n2.nombre_entidad AS destino,
         a.registrado_por, a.nota_explicativa, a.creado_en
  FROM stacy_aristas_grafo a
  JOIN stacy_nodos_memoria n1 ON n1.id = a.nodo_origen_id
  JOIN stacy_nodos_memoria n2 ON n2.id = a.nodo_destino_id
  WHERE a.es_activa = TRUE
  ORDER BY a.creado_en DESC;
  ```