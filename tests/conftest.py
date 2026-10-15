"""Accesorios comunes de las pruebas de la API.

Cada prueba corre sobre su propia base SQLite, creada con `alembic upgrade head`: se prueba el
esquema que de verdad se despliega, no uno que SQLAlchemy arme por su cuenta.
"""

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import jwt
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.sesion import crear_motor, obtener_sesion
from app.seguridad import ALGORITMO

# Sin GLUCY_JWT_SECRET la aplicación no arranca, a propósito; por eso `app.main` se importa
# dentro del accesorio `cliente`, ya con la variable puesta. Este valor solo existe dentro de
# las pruebas y no firma nada fuera de ellas.
SECRETO = "secreto-que-solo-existe-en-las-pruebas"
os.environ["GLUCY_JWT_SECRET"] = SECRETO

RAIZ = Path(__file__).resolve().parent.parent
USUARIO = UUID("11111111-1111-1111-1111-111111111111")


def migrar(url: str) -> None:
    """`alembic upgrade head` contra la URL dada."""
    configuracion = Config(str(RAIZ / "alembic.ini"))
    configuracion.set_main_option("sqlalchemy.url", url)
    command.upgrade(configuracion, "head")


@pytest.fixture
def motor(tmp_path: Path) -> Iterator[Engine]:
    url = f"sqlite:///{tmp_path / 'glucy-pruebas.db'}"
    migrar(url)
    motor = crear_motor(url)
    yield motor
    motor.dispose()


@pytest.fixture
def sesion(motor: Engine) -> Iterator[Session]:
    """Una sesión aparte para que las pruebas cuenten filas en la base."""
    with sessionmaker(bind=motor)() as sesion:
        yield sesion


@pytest.fixture
def cliente(motor: Engine) -> Iterator[TestClient]:
    from app.main import app

    fabrica = sessionmaker(bind=motor, expire_on_commit=False)

    def sesion_de_prueba() -> Iterator[Session]:
        with fabrica() as sesion:
            yield sesion

    app.dependency_overrides[obtener_sesion] = sesion_de_prueba
    with TestClient(app) as cliente:
        yield cliente
    app.dependency_overrides.clear()


def token(
    sub: UUID | str = USUARIO, *, vence_en: timedelta = timedelta(minutes=15), secreto=SECRETO
) -> str:
    ahora = datetime.now(UTC)
    carga = {"sub": str(sub), "iat": ahora, "exp": ahora + vence_en}
    return jwt.encode(carga, secreto, algorithm=ALGORITMO)


def cabeceras(sub: UUID | str = USUARIO) -> dict[str, str]:
    return {"Authorization": f"Bearer {token(sub)}"}


def contar(sesion: Session, tabla) -> int:
    sesion.expire_all()
    return sesion.scalar(select(func.count()).select_from(tabla))
