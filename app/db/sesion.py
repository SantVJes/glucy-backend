"""El motor de la base y la dependencia de sesión que usan los routers.

SQLite para arrancar (D-4). Nada de aquí supone extensiones de TimescaleDB: eso llega en el
paso 4 y se queda en `repositories/`.
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import ajustes


def crear_motor(url: str) -> Engine:
    """Crea el motor; con SQLite permite usarlo desde los hilos del servidor.

    FastAPI corre las dependencias síncronas en un pool de hilos, y SQLite por omisión se
    niega a usar una conexión desde un hilo distinto del que la abrió.
    """
    argumentos = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=argumentos)


@lru_cache
def SessionLocal() -> sessionmaker[Session]:  # noqa: N802 — el nombre de costumbre en SQLAlchemy
    """Se crea al primer uso y no al importar, para que importar la app no abra la base."""
    return sessionmaker(bind=crear_motor(ajustes().database_url), expire_on_commit=False)


def obtener_sesion() -> Iterator[Session]:
    """Una sesión por petición, cerrada siempre, haya error o no."""
    sesion = SessionLocal()()
    try:
        yield sesion
    finally:
        sesion.close()
