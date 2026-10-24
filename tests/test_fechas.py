"""Pruebas 15 a 17: las fechas vuelven de la base en UTC y con zona (decisión 2.1 del paso 2).

Sin `FechaUtc`, SQLite devuelve `datetime` sin `tzinfo` y compararlo con `datetime.now(UTC)`
levanta `TypeError`. No rompe nada mientras solo se escribe; truena en el primer `GET`.
"""

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import StatementError

from app.models.tablas import Base, Cuarentena, LecturaGlucosa, Usuario
from app.models.tipos import FechaUtc
from tests.conftest import USUARIO, cabeceras

MENOS_SEIS = timezone(timedelta(hours=-6))


# 15 --------------------------------------------------------------------------


def test_15_ida_y_vuelta_de_una_lectura(cliente, sesion):
    """Las 22:00 con offset −06:00 vuelven como las 04:00 UTC del día siguiente, con zona."""
    local = datetime(2026, 10, 23, 22, 0, tzinfo=MENOS_SEIS)
    renglon = {
        "uuid": str(uuid4()),
        "ts_utc": local.isoformat(),
        "zona_horaria": "America/Monterrey",
        "mg_dl": 112,
        "origen": "manual",
    }
    assert cliente.post("/readings", json={"items": [renglon]}, headers=cabeceras()).json()[
        "aceptados"
    ] == [renglon["uuid"]]

    sesion.expire_all()
    leida = sesion.scalars(select(LecturaGlucosa)).one()

    # Las tres cosas, no solo la última.
    assert leida.ts_utc == datetime(2026, 10, 24, 4, 0, tzinfo=UTC)
    assert leida.ts_utc.tzinfo is not None and leida.ts_utc.utcoffset() == timedelta(0)
    assert leida.ts_utc < datetime.now(UTC)  # antes de FechaUtc: TypeError


# 16 --------------------------------------------------------------------------


def test_16_ts_alta_y_ts_recepcion_tambien_vuelven_con_zona(cliente, sesion):
    malo = {"uuid": str(uuid4()), "ts_utc": "2026-10-13T14:32:00"}  # sin offset: cuarentena
    antes = datetime.now(UTC)
    cliente.post("/readings", json={"items": [malo]}, headers=cabeceras())

    sesion.expire_all()
    usuario = sesion.get(Usuario, USUARIO)
    fila = sesion.scalars(select(Cuarentena)).one()

    for valor in (usuario.ts_alta, fila.ts_recepcion):
        assert valor.tzinfo is not None and valor.utcoffset() == timedelta(0)
        assert antes - timedelta(seconds=5) <= valor <= datetime.now(UTC)


def test_las_doce_tablas_usan_fecha_utc_en_cada_columna_de_fecha():
    """Una columna de fecha nueva que se olvide del tipo volvería a devolver naive."""
    for tabla in Base.metadata.sorted_tables:
        for columna in tabla.columns:
            if columna.type.python_type is datetime:
                assert isinstance(columna.type, FechaUtc), f"{tabla.name}.{columna.name}"


# 17 --------------------------------------------------------------------------


def test_17_una_fecha_sin_zona_no_se_guarda(sesion):
    sesion.add(Usuario(uuid=uuid4(), ts_alta=datetime(2026, 10, 24, 4, 0)))

    with pytest.raises(StatementError) as error:
        sesion.flush()

    assert isinstance(error.value.orig, ValueError)
    assert "una fecha sin zona no se guarda" in str(error.value)
