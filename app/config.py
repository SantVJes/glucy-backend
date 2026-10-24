"""Ajustes de la aplicación, leídos del entorno con el prefijo GLUCY_.

Ningún secreto vive en el código ni en el repositorio: `.env.example` lleva los nombres y
ningún valor.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Ajustes(BaseSettings):
    """Lee el entorno. Ningún valor por omisión que sea un secreto."""

    model_config = SettingsConfigDict(env_prefix="GLUCY_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./glucy.db"
    # Sin valor por omisión a propósito: un secreto con valor por omisión acaba en
    # producción. Si falta GLUCY_JWT_SECRET, la aplicación no arranca.
    jwt_secret: str
    jwt_minutos_vigencia: int = 15


@lru_cache
def ajustes() -> Ajustes:
    """Una sola lectura del entorno por proceso."""
    return Ajustes()
