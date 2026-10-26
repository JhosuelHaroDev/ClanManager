"""
Configuración central de la aplicación.
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Ajustes de la aplicación, cargados desde variables de entorno o .env."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Supercell / Clash of Clans ---
    coc_token: str
    clan_tag: str = "89YVP0RG"
    coc_base_url: str = "https://cocproxy.royaleapi.dev/v1"
    coc_timeout: float = 10.0

    # --- PostgreSQL ---
    database_url: str

    @field_validator("database_url", mode="before")
    @classmethod
    def asegurar_driver_asyncpg(cls, valor: str) -> str:
        """Convierte automáticamente la URL de Railway al driver asyncpg."""
        if not isinstance(valor, str):
            return valor
        if valor.startswith("postgres://"):
            return valor.replace("postgres://", "postgresql+asyncpg://", 1)
        if valor.startswith("postgresql://"):
            return valor.replace("postgresql://", "postgresql+asyncpg://", 1)
        return valor

    # --- CORS Frontend (Opcional) ---
    frontend_origins: str = "http://localhost:5173"

    @property
    def frontend_origins_lista(self) -> list[str]:
        return [origen.strip() for origen in self.frontend_origins.split(",") if origen.strip()]

    # --- Cadencias del Programador (APScheduler) ---
    captura_intervalo_minutos: int = 60
    guerra_intervalo_minutos: int = 10
    guerra_captura_final_demora_minutos: int = 2
    liga_intervalo_minutos: int = 30
    asalto_intervalo_minutos: int = 30
    asalto_inicio_dia_semana: int = 4  # viernes
    asalto_inicio_hora_utc: int = 7
    asalto_fin_dia_semana: int = 0     # lunes
    asalto_fin_hora_utc: int = 7
    asalto_captura_final_demora_minutos: int = 15

    # --- Motores de IA para S.T.A.C.Y. (Híbrido 2 Etapas) ---
    anthropic_api_key: str | None = None
    groq_api_key: str | None = None
    nvidia_api_key: str | None = None
    mostrar_firma_modelo: bool = True

    # --- Búsqueda Web en Cascada (Tavily -> Google) ---
    tavily_api_key: str | None = None
    google_search_api_key: str | None = None
    google_search_cx: str | None = None

    # --- WhatsApp (Green-API) ---
    bot_phone_number: str = "51922982880"
    green_api_url: str = "https://7107.api.greenapi.com"
    green_id_instance: str = "710722767009"
    green_api_token: str | None = None
    allowed_group_id: str | None = None


settings = Settings()