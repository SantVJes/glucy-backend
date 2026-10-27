"""Pruebas 78 a 80: la orden `python -m app.pipeline` (decisión 2.11 del paso 4).

Se corre de verdad, en un subproceso y contra la base de la prueba, porque lo que se prueba es
la orden con su código de salida y no solo la función.
"""

import math
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from app.models.tablas import AgregadoDiario, AgregadoHorario, Base, SerieLimpia
from tests.conftest import RAIZ, USUARIO, cabeceras, contar

INICIO = datetime(2026, 9, 1, 6, 0, tzinfo=UTC)  # medianoche en Monterrey
PERIODO = ["--desde", "2026-09-01T06:00:00+00:00", "--hasta", "2026-09-03T06:00:00+00:00"]


def subir_dos_dias_de_sensor(cliente) -> int:
    """Dos días cada 5 minutos, con un hueco de 10 min, uno de 30 y un salto imposible."""
    items = []
    for i in range(2 * 288):
        if i in (100, 200, 201, 202, 203, 204):  # un hueco de 10 min y otro de 30
            continue
        items.append(
            {
                "uuid": str(uuid4()),
                "ts_utc": (INICIO + timedelta(minutes=5 * i)).isoformat(),
                "zona_horaria": "America/Monterrey",
                "mg_dl": 400 if i == 300 else round(130 + 30 * math.sin(i / 20), 1),
                "origen": "sensor",
            }
        )
    for inicio in range(0, len(items), 500):
        lote = items[inicio : inicio + 500]
        cuerpo = cliente.post("/readings", json={"items": lote}, headers=cabeceras()).json()
        assert len(cuerpo["aceptados"]) == len(lote)
    return len(items)


def pipeline(motor, *argumentos: str) -> subprocess.CompletedProcess:
    entorno = {**os.environ, "GLUCY_DATABASE_URL": str(motor.url)}
    return subprocess.run(
        [sys.executable, "-m", "app.pipeline", *argumentos],
        cwd=RAIZ,
        env=entorno,
        capture_output=True,
        text=True,
        timeout=120,
    )


def foto(sesion) -> dict:
    """Todo lo que el pipeline escribe, para comparar dos corridas."""
    sesion.expire_all()
    return {
        modelo.__tablename__: [
            tuple(getattr(fila, c.name) for c in modelo.__table__.columns)
            for fila in sesion.scalars(select(modelo))
        ]
        for modelo in (SerieLimpia, AgregadoHorario, AgregadoDiario)
    }


# 78 --------------------------------------------------------------------------


def test_78_la_orden_llena_la_serie_y_los_dos_agregados(cliente, sesion, motor):
    lecturas = subir_dos_dias_de_sensor(cliente)

    resultado = pipeline(motor, "--usuario", str(USUARIO), *PERIODO)

    assert resultado.returncode == 0, resultado.stderr
    assert f"{lecturas} lecturas" in resultado.stdout
    sesion.expire_all()
    serie = list(sesion.scalars(select(SerieLimpia)))
    assert len(serie) == lecturas + 1  # el hueco de 10 min se rellena; el de 30 no
    assert sum(f.interpolada for f in serie) == 1
    assert sum(f.atipica for f in serie) == 1
    assert contar(sesion, AgregadoDiario) == 2
    assert contar(sesion, AgregadoHorario) == 48


# 79 --------------------------------------------------------------------------


def test_79_correrla_dos_veces_deja_la_base_igual(cliente, sesion, motor):
    subir_dos_dias_de_sensor(cliente)
    assert pipeline(motor, "--usuario", str(USUARIO), *PERIODO).returncode == 0
    primera = foto(sesion)

    assert pipeline(motor, "--todos", *PERIODO).returncode == 0

    assert foto(sesion) == primera


# 80 --------------------------------------------------------------------------


def test_80_un_usuario_sin_lecturas_no_falla_ni_escribe(cliente, sesion, motor):
    subir_dos_dias_de_sensor(cliente)
    antes = {tabla.name: contar(sesion, tabla) for tabla in Base.metadata.sorted_tables}

    resultado = pipeline(motor, "--usuario", str(uuid4()), *PERIODO)

    assert resultado.returncode == 0, resultado.stderr
    assert "0 lecturas" in resultado.stdout
    assert {tabla.name: contar(sesion, tabla) for tabla in Base.metadata.sorted_tables} == antes


def test_sin_periodo_la_orden_sale_con_error_y_no_toca_nada(motor):
    resultado = pipeline(motor, "--usuario", str(USUARIO))

    assert resultado.returncode == 2
    assert "--desde" in resultado.stderr
