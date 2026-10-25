"""Pruebas 55 a 57: el mismo código en SQLite y en PostgreSQL (decisiones 2.1 a 2.3 del paso 4).

No necesitan un servidor: compilan las sentencias que arman los repositorios contra el dialecto
de cada motor. Si una no compila en PostgreSQL, truena aquí y no en el contenedor.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from app.models.tablas import Comida, DosisInsulina, LecturaGlucosa
from app.repositories import lotes, perfil, usuarios

DIALECTOS = [
    pytest.param(sqlite.dialect(), id="sqlite"),
    pytest.param(postgresql.dialect(), id="postgresql"),
]


class SesionQueCompila:
    """Hace de sesión para un repositorio: en lugar de ejecutar, compila contra un dialecto.

    Lo que el repositorio le pase a `execute` o a `scalars` es exactamente la sentencia que
    llegaría a la base, así que compilarla prueba el repositorio de verdad, no una copia.
    """

    def __init__(self, dialecto) -> None:
        self.dialecto = dialecto
        self.sql: list[str] = []

    def get_bind(self):
        return SimpleNamespace(dialect=self.dialecto)

    def _compilar(self, sentencia) -> None:
        self.sql.append(str(sentencia.compile(dialect=self.dialecto)))

    def scalars(self, sentencia):
        self._compilar(sentencia)
        return []

    def execute(self, sentencia):
        self._compilar(sentencia)
        return SimpleNamespace(mappings=lambda: SimpleNamespace(one=dict))


# 55 --------------------------------------------------------------------------


@pytest.mark.parametrize("dialecto", DIALECTOS)
def test_55_usuarios_compila_en_los_dos_motores(dialecto):
    sesion = SesionQueCompila(dialecto)

    usuarios.asegurar_que_existe(sesion, uuid4(), ts_alta=datetime.now(UTC))

    [sql] = sesion.sql
    assert "INSERT INTO usuarios" in sql and "ON CONFLICT (uuid) DO NOTHING" in sql


@pytest.mark.parametrize("dialecto", DIALECTOS)
@pytest.mark.parametrize("modelo", [LecturaGlucosa, Comida, DosisInsulina])
def test_55_lotes_compila_en_los_dos_motores(dialecto, modelo):
    sesion = SesionQueCompila(dialecto)
    fila = {columna.name: None for columna in modelo.__table__.columns}
    fila.update(uuid=uuid4(), usuario_uuid=uuid4())

    lotes.insertar_ignorando_duplicados(sesion, modelo, [fila])

    [sql] = sesion.sql
    assert f"INSERT INTO {modelo.__tablename__}" in sql
    assert "ON CONFLICT (uuid) DO NOTHING" in sql and "RETURNING" in sql


@pytest.mark.parametrize("dialecto", DIALECTOS)
def test_55_perfil_compila_en_los_dos_motores(dialecto):
    sesion = SesionQueCompila(dialecto)
    campos = {
        "tipo_usuario": "tipo1",
        "anio_nacimiento": 2001,
        "umbral_hipo": 70.0,
        "umbral_hiper": 180.0,
        "tipo_insulina_rapida": None,
        "duracion_accion_insulina": 5.0,
    }

    perfil.guardar(sesion, uuid4(), campos, datetime.now(UTC))

    [sql] = sesion.sql
    assert "ON CONFLICT (uuid) DO UPDATE" in sql and "RETURNING" in sql
    assert "ts_alta" not in sql.split("DO UPDATE")[1]  # ts_alta no se toca al actualizar
