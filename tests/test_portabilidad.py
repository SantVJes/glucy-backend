"""Pruebas 55 a 57: el mismo código en SQLite y en PostgreSQL (decisiones 2.1 a 2.3 del paso 4).

No necesitan un servidor: compilan las sentencias que arman los repositorios contra el dialecto
de cada motor. Si una no compila en PostgreSQL, truena aquí y no en el contenedor.
"""

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateTable

from app.models.tablas import Base, Comida, DosisInsulina, LecturaGlucosa, SerieLimpia
from app.models.tipos import FechaUtc
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


# 56 --------------------------------------------------------------------------


@pytest.mark.parametrize("dialecto", DIALECTOS)
def test_56_las_catorce_tablas_compilan_en_los_dos_motores(dialecto):
    tablas = Base.metadata.sorted_tables

    for tabla in tablas:
        sql = str(CreateTable(tabla).compile(dialect=dialecto))
        assert f"CREATE TABLE {tabla.name}" in sql

    assert len(tablas) == 14
    nombres = {tabla.name for tabla in tablas}
    assert "serie_limpia" in nombres
    assert "explicaciones" in nombres


def test_serie_limpia_tiene_la_llave_de_la_hipertabla_y_glucose_readings_la_suya():
    """La llave de `serie_limpia` incluye el tiempo, que es lo que exige TimescaleDB; la de
    `glucose_readings` sigue siendo el `uuid` solo, la llave de idempotencia (decisión 2.4)."""
    assert [c.name for c in SerieLimpia.__table__.primary_key] == ["usuario_uuid", "ts_utc"]
    assert [c.name for c in LecturaGlucosa.__table__.primary_key] == ["uuid"]


# 57 --------------------------------------------------------------------------


def test_57_fecha_utc_devuelve_utc_con_zona_tambien_si_el_motor_ya_trae_zona():
    """En PostgreSQL `TIMESTAMPTZ` vuelve con la zona de la sesión, no necesariamente UTC."""
    tipo = FechaUtc()
    en_monterrey = datetime(2026, 10, 23, 22, 0, tzinfo=timezone(timedelta(hours=-6)))

    leida = tipo.process_result_value(en_monterrey, postgresql.dialect())

    assert leida == datetime(2026, 10, 24, 4, 0, tzinfo=UTC)
    assert leida.utcoffset() == timedelta(0)
    sin_zona = tipo.process_result_value(datetime(2026, 10, 24, 4, 0), sqlite.dialect())
    assert sin_zona.tzinfo is not None and sin_zona == leida
