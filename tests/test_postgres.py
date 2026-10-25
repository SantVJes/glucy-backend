"""El mismo código contra PostgreSQL con TimescaleDB (decisión 2.1 del paso 4).

Marcadas `postgres`: solo corren con `GLUCY_DATABASE_URL_POSTGRES` puesta, que es lo que hace
el segundo trabajo de la integración continua. Sin ella se saltan, y el trabajo rápido con
SQLite sigue igual.

Este módulo sustituye el accesorio `motor` del `conftest.py` por uno sobre PostgreSQL, así que
`cliente` y `sesion` son los mismos de siempre, pero contra el segundo motor. **Cada prueba
borra el esquema `public` de esa base**: no se apunta nunca a una base con datos.
"""

import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, select, text

from app.db.sesion import crear_motor
from app.models.tablas import AgregadoDiario, Comida, LecturaGlucosa, SerieLimpia, Usuario
from tests.conftest import RAIZ, USUARIO, cabeceras, contar, migrar

URL = os.environ.get("GLUCY_DATABASE_URL_POSTGRES")

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not URL, reason="sin GLUCY_DATABASE_URL_POSTGRES"),
]

INICIO = datetime(2026, 9, 1, 6, 0, tzinfo=UTC)


@pytest.fixture
def motor() -> Iterator[Engine]:
    """Una base vacía y migrada con `alembic upgrade head` para cada prueba."""
    limpio = crear_motor(URL)
    with limpio.begin() as conexion:
        conexion.execute(text("DROP SCHEMA public CASCADE"))
        conexion.execute(text("CREATE SCHEMA public"))
    limpio.dispose()
    migrar(URL)
    motor = crear_motor(URL)
    yield motor
    motor.dispose()


def lectura(minutos: int, mg_dl: float = 120, origen: str = "sensor") -> dict:
    return {
        "uuid": str(uuid4()),
        "ts_utc": (INICIO + timedelta(minutes=minutos)).isoformat(),
        "zona_horaria": "America/Monterrey",
        "mg_dl": mg_dl,
        "origen": origen,
    }


def test_la_licencia_es_apache_y_la_unica_hipertabla_es_serie_limpia(motor):
    with motor.connect() as conexion:
        licencia = conexion.execute(text("SHOW timescaledb.license")).scalar_one()
        hipertablas = conexion.execute(
            text("SELECT hypertable_name FROM timescaledb_information.hypertables")
        ).scalars()
        assert licencia == "apache"
        assert list(hipertablas) == ["serie_limpia"]


def test_p05_el_mismo_lote_dos_veces_no_duplica_en_postgresql(cliente, sesion):
    items = [lectura(0), lectura(5), lectura(10)]
    primera = cliente.post("/readings", json={"items": items}, headers=cabeceras()).json()

    segunda = cliente.post("/readings", json={"items": items}, headers=cabeceras()).json()

    assert primera["aceptados"] == [i["uuid"] for i in items]
    assert segunda["duplicados"] == [i["uuid"] for i in items]
    assert contar(sesion, LecturaGlucosa) == 3


def test_los_otros_lotes_y_el_perfil_en_postgresql(cliente, sesion):
    comida = {
        "uuid": str(uuid4()),
        "ts_utc": INICIO.isoformat(),
        "zona_horaria": "America/Monterrey",
        "carbs_g": 60,
        "origen": "barcode",
    }
    perfil = {
        "tipo_usuario": "tipo1",
        "anio_nacimiento": 2001,
        "umbral_hipo": 70,
        "umbral_hiper": 180,
        "duracion_accion_insulina": 5,
    }

    assert cliente.post("/meals", json={"items": [comida]}, headers=cabeceras()).json()[
        "aceptados"
    ] == [comida["uuid"]]
    assert cliente.post("/perfil", json=perfil, headers=cabeceras()).status_code == 200
    segundo = cliente.post("/perfil", json={**perfil, "umbral_hipo": 80}, headers=cabeceras())

    assert segundo.json()["umbral_hipo"] == 80
    assert contar(sesion, Comida) == 1 and contar(sesion, Usuario) == 1
    assert (
        cliente.post("/perfil", json={**perfil, "nombre": "x"}, headers=cabeceras()).status_code
        == 400
    )


def test_history_y_stats_en_postgresql(cliente):
    items = [lectura(24 * 60 * d + 5 * i, 100 + i) for d in range(3) for i in range(4)]
    cliente.post("/readings", json={"items": items}, headers=cabeceras())
    periodo = {"desde": "2026-09-01T00:00:00Z", "hasta": "2026-10-01T00:00:00Z"}

    vistas, cursor = [], None
    while True:
        pagina = cliente.get(
            "/history",
            params={**periodo, "limite": 5, **({"cursor": cursor} if cursor else {})},
            headers=cabeceras(),
        ).json()
        vistas += [r["uuid"] for r in pagina["lecturas"]]
        cursor = pagina["siguiente"]
        if cursor is None:
            break
    stats = cliente.get("/stats", params=periodo, headers=cabeceras()).json()

    assert vistas == [i["uuid"] for i in items]
    assert stats["dias_con_lecturas"] == 3 and stats["indicadores"]["n"] == 12


def test_el_pipeline_corre_y_es_idempotente_en_postgresql(cliente, sesion, motor):
    items = [lectura(5 * i, 120 + i % 3) for i in range(288) if i != 50]  # un hueco de 10 min
    for inicio in range(0, len(items), 250):
        cliente.post("/readings", json={"items": items[inicio : inicio + 250]}, headers=cabeceras())
    orden = [
        sys.executable, "-m", "app.pipeline", "--usuario", str(USUARIO),
        "--desde", "2026-09-01T06:00:00+00:00", "--hasta", "2026-09-02T06:00:00+00:00",
    ]  # fmt: skip
    entorno = {**os.environ, "GLUCY_DATABASE_URL": URL}

    for _ in range(2):
        resultado = subprocess.run(orden, cwd=RAIZ, env=entorno, capture_output=True, text=True)
        assert resultado.returncode == 0, resultado.stderr

    sesion.expire_all()
    serie = list(sesion.scalars(select(SerieLimpia)))
    assert len(serie) == 288 and sum(f.interpolada for f in serie) == 1
    assert contar(sesion, AgregadoDiario) == 1
    assert all(f.ts_utc.tzinfo is not None for f in serie)  # FechaUtc también en PostgreSQL
