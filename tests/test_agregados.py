"""Pruebas 73 a 77: los agregados por hora y por día (decisión 2.6 del paso 4).

Se llenan con `indicadores()` de la referencia, nunca en SQL, y agrupan por día **local**.
"""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.models.tablas import AgregadoDiario, AgregadoHorario
from app.repositories import serie as repo_serie
from app.repositories import usuarios as repo_usuarios
from app.services.pipeline.agregados import recalcular
from referencia.reglas_clinicas import indicadores
from tests.conftest import USUARIO

MONTERREY = "America/Monterrey"
MENOS_SEIS = timezone(timedelta(hours=-6))
# Tres días locales de Monterrey: del 1 al 3 de septiembre.
DESDE = datetime(2026, 9, 1, tzinfo=MENOS_SEIS).astimezone(UTC)
HASTA = DESDE + timedelta(days=3)


def fila(ts: datetime, mg_dl: float, zona: str = MONTERREY, **extra) -> dict:
    return {
        "ts_utc": ts,
        "zona_horaria": zona,
        "mg_dl": mg_dl,
        "origen": "sensor",
        "atipica": extra.get("atipica", False),
        "interpolada": extra.get("interpolada", False),
    }


def cada_5_min(desde: datetime, hasta: datetime, valor=lambda i: 80 + (i * 7) % 160) -> list[dict]:
    """Una fila cada 5 minutos; el valor recorre 80–239 para que haya TIR, TBR y TAR."""
    filas, instante, i = [], desde, 0
    while instante < hasta:
        filas.append(fila(instante, float(valor(i))))
        instante += timedelta(minutes=5)
        i += 1
    return filas


def sembrar(sesion, filas: list[dict], usuario: UUID = USUARIO) -> None:
    repo_usuarios.asegurar_que_existe(sesion, usuario, ts_alta=datetime.now(UTC))
    repo_serie.reemplazar(
        sesion, usuario, DESDE - timedelta(days=2), HASTA + timedelta(days=2), filas
    )
    sesion.commit()


def leer(sesion, modelo, usuario: UUID = USUARIO) -> list:
    sesion.expire_all()
    return list(
        sesion.scalars(
            select(modelo).where(modelo.usuario_uuid == usuario).order_by(modelo.periodo)
        )
    )


# 73 --------------------------------------------------------------------------


def test_73_tres_dias_dejan_3_filas_diarias_y_72_horarias(sesion):
    sembrar(sesion, cada_5_min(DESDE, HASTA))

    horarias, diarias = recalcular(sesion, USUARIO, DESDE, HASTA)
    sesion.commit()

    assert (horarias, diarias) == (72, 3)
    assert len(leer(sesion, AgregadoHorario)) == 72
    dias = leer(sesion, AgregadoDiario)
    assert [d.periodo for d in dias] == [DESDE + timedelta(days=i) for i in range(3)]


# 74 --------------------------------------------------------------------------


def test_74_las_cifras_son_las_de_indicadores_campo_por_campo(sesion):
    filas = cada_5_min(DESDE, HASTA)
    sembrar(sesion, filas)

    recalcular(sesion, USUARIO, DESDE, HASTA)
    sesion.commit()

    primer_dia = [f["mg_dl"] for f in filas if f["ts_utc"] < DESDE + timedelta(days=1)]
    esperado = indicadores(primer_dia)
    dia = leer(sesion, AgregadoDiario)[0]
    for campo in ("promedio", "desviacion", "tir", "tbr", "tar"):
        assert getattr(dia, campo) == getattr(esperado, campo), campo
    assert (dia.minimo, dia.maximo) == (min(primer_dia), max(primer_dia))
    assert dia.gmi is None  # un día no basta para el GMI (gmi_es_fiable)

    primera_hora = [f["mg_dl"] for f in filas if f["ts_utc"] < DESDE + timedelta(hours=1)]
    hora = leer(sesion, AgregadoHorario)[0]
    assert hora.promedio == indicadores(primera_hora).promedio
    assert hora.tir == indicadores(primera_hora).tir


def test_las_atipicas_no_entran_a_los_agregados(sesion):
    filas = cada_5_min(DESDE, DESDE + timedelta(hours=1), valor=lambda i: 100)
    filas[3] = fila(filas[3]["ts_utc"], 400, atipica=True)
    sembrar(sesion, filas)

    recalcular(sesion, USUARIO, DESDE, HASTA)
    sesion.commit()

    [hora] = leer(sesion, AgregadoHorario)
    assert (hora.promedio, hora.maximo) == (100, 100)


# 75 --------------------------------------------------------------------------


def test_75_recalcular_dos_veces_no_duplica_y_deja_los_mismos_numeros(sesion):
    sembrar(sesion, cada_5_min(DESDE, HASTA))
    recalcular(sesion, USUARIO, DESDE, HASTA)
    sesion.commit()
    antes = [(d.periodo, d.promedio, d.tir) for d in leer(sesion, AgregadoDiario)]
    horas_antes = len(leer(sesion, AgregadoHorario))

    assert recalcular(sesion, USUARIO, DESDE, HASTA) == (72, 3)
    sesion.commit()

    assert [(d.periodo, d.promedio, d.tir) for d in leer(sesion, AgregadoDiario)] == antes
    assert len(leer(sesion, AgregadoHorario)) == horas_antes == 72


def test_un_periodo_parcial_no_deja_un_dia_a_medias(sesion):
    """Un periodo que empieza a media tarde no escribe el día que ya había empezado."""
    sembrar(sesion, cada_5_min(DESDE, HASTA))

    _, diarias = recalcular(sesion, USUARIO, DESDE + timedelta(hours=15), HASTA)
    sesion.commit()

    assert diarias == 2
    assert [d.periodo for d in leer(sesion, AgregadoDiario)] == [
        DESDE + timedelta(days=1),
        DESDE + timedelta(days=2),
    ]


# 76 --------------------------------------------------------------------------


def test_76_el_dia_es_el_local_con_la_zona_de_cada_fila(sesion):
    """Las 10:00, 19:00 y 20:00 del 1 de septiembre en Monterrey son un solo día local, aunque
    las dos últimas sean el 2 de septiembre en UTC. Y una fila de Madrid a la misma hora UTC
    cae en otro día local."""
    dia = datetime(2026, 9, 1, tzinfo=MENOS_SEIS)
    filas = [fila(dia.replace(hour=h).astimezone(UTC), 100 + h) for h in (10, 19, 20)]
    sembrar(sesion, filas)

    recalcular(sesion, USUARIO, DESDE, HASTA)
    sesion.commit()

    [unico] = leer(sesion, AgregadoDiario)
    assert unico.periodo == DESDE  # medianoche de Monterrey, en UTC
    assert unico.promedio == pytest.approx((110 + 119 + 120) / 3)

    madrid = fila(dia.replace(hour=19).astimezone(UTC) + timedelta(seconds=1), 150, "Europe/Madrid")
    sembrar(sesion, [*filas, madrid])
    recalcular(sesion, USUARIO, DESDE, HASTA)
    sesion.commit()
    assert len(leer(sesion, AgregadoDiario)) == 2


# 77 --------------------------------------------------------------------------


def test_77_los_agregados_de_un_usuario_no_incluyen_filas_de_otro(sesion):
    otro = uuid4()
    sembrar(sesion, cada_5_min(DESDE, HASTA, valor=lambda i: 100))
    sembrar(sesion, cada_5_min(DESDE, HASTA, valor=lambda i: 250), usuario=otro)

    recalcular(sesion, USUARIO, DESDE, HASTA)
    sesion.commit()

    assert all(d.promedio == 100 for d in leer(sesion, AgregadoDiario))
    assert leer(sesion, AgregadoDiario, otro) == []
    recalcular(sesion, otro, DESDE, HASTA)
    sesion.commit()
    assert all(d.promedio == 250 for d in leer(sesion, AgregadoDiario, otro))
    assert all(d.promedio == 100 for d in leer(sesion, AgregadoDiario))
