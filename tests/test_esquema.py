"""Prueba 14: el esquema que deja `alembic upgrade head` es el del Documento 3."""

from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.db.sesion import crear_motor
from tests.conftest import migrar

DOCE_TABLAS = {
    "usuarios",
    "glucose_readings",
    "meals",
    "insulin_doses",
    "context_events",
    "predictions",
    "alerts",
    "modelos",
    "cuarentena",
    "agregados_horarios",
    "agregados_diarios",
    "xapi_events",
}


def test_14_alembic_crea_las_catorce_tablas_y_uuid_es_unico(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'esquema.db'}"
    migrar(url)
    motor = crear_motor(url)

    inspector = inspect(motor)
    # Las dos que no están en el Documento 3, cada una anotada donde se decidió:
    # `serie_limpia` es C-9 (paso 4) y `explicaciones` es C-13 (paso 2 de la fase 6).
    assert set(inspector.get_table_names()) - {"alembic_version"} == DOCE_TABLAS | {
        "serie_limpia",
        "explicaciones",
    }
    assert inspector.get_pk_constraint("glucose_readings")["constrained_columns"] == ["uuid"]

    # Y que la base lo haga cumplir, no solo que lo declare.
    fila = (
        "insert into glucose_readings (uuid, usuario_uuid, ts_utc, zona_horaria, mg_dl, origen) "
        "values ('6f3a1b2c000040008000000000000001', '11111111111111111111111111111111', "
        "'2026-10-13 14:32:00', 'America/Monterrey', 112, 'manual')"
    )
    with motor.begin() as conexion:
        conexion.exec_driver_sql(fila)
    with pytest.raises(IntegrityError), motor.begin() as conexion:
        conexion.exec_driver_sql(fila)
    motor.dispose()
