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


@lru_cache
def ajustes() -> Ajustes:
    """Una sola lectura del entorno por proceso."""
    return Ajustes()
