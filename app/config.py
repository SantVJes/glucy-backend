"""Ajustes de la aplicación, leídos del entorno con el prefijo GLUCY_.

Ningún secreto vive en el código ni en el repositorio: `.env.example` lleva los nombres y
ningún valor.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from referencia.reglas_clinicas import TIMEOUT_MODELO_LENGUAJE_S


class Ajustes(BaseSettings):
    """Lee el entorno. Ningún valor por omisión que sea un secreto."""

    model_config = SettingsConfigDict(env_prefix="GLUCY_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./glucy.db"
    # Sin valor por omisión a propósito: un secreto con valor por omisión acaba en
    # producción. Si falta GLUCY_JWT_SECRET, la aplicación no arranca.
    jwt_secret: str
    jwt_minutos_vigencia: int = 15

    # El modelo de lenguaje del paso 6. **Sin URL no se llama a nada y sale la plantilla
    # determinista**, que es el piso de la función y no un plan de emergencia (P-13): la app
    # funciona igual con la computadora de Ollama apagada.
    ollama_url: str = ""
    ollama_modelo: str = "qwen3:8b"
    explicacion_timeout_s: float = TIMEOUT_MODELO_LENGUAJE_S

    # La carpeta con los artefactos del modelo y sus manifiestos (paso 5). Vacía = sin modelo,
    # y `/predict` contesta 503 en lugar de inventar un número.
    ruta_artefacto_modelo: str = ""

    # El Learning Record Store de la fase 6 (Learning Locker). **Sin URL no se manda nada y las
    # sentencias se quedan en la cola**: el LRS es para analítica de aprendizaje y ninguna
    # función de la app depende de que esté encendido (RF-19, RF-33). Los nombres de las tres
    # variables son los que ya estaban en `.env.example`.
    lrs_url: str = ""
    lrs_usuario: str = ""
    lrs_secreto: str = ""
    lrs_timeout_s: float = 10.0


@lru_cache
def ajustes() -> Ajustes:
    """Una sola lectura del entorno por proceso."""
    return Ajustes()
