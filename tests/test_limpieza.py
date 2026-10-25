"""Pruebas 58 a 64: la limpieza de la serie del sensor (RF-23) y el filtro que la suaviza.

El filtro se escribió con numpy, y `scipy.signal.savgol_filter` es el árbitro (decisión 2.7).
"""

from datetime import UTC, datetime, timedelta
from fractions import Fraction
from uuid import uuid4

import numpy as np
import pytest
from scipy.signal import savgol_filter

from app.models.tablas import LecturaGlucosa
from app.services.pipeline.filtro import (
    GRADO_SUAVIZADO,
    VENTANA_SUAVIZADO,
    coeficientes,
    suavizar,
)
from app.services.pipeline.limpieza import limpiar
from referencia.reglas_clinicas import Origen

# 62 --------------------------------------------------------------------------


@pytest.mark.parametrize("n", [7, 12, 50, 289])
def test_62_el_suavizado_coincide_con_scipy_en_el_centro_y_en_los_extremos(n):
    rng = np.random.default_rng(n)
    serie = 120 + 40 * np.sin(np.arange(n) / 9) + rng.normal(0, 6, n)

    propio = suavizar(serie)
    arbitro = savgol_filter(serie, VENTANA_SUAVIZADO, GRADO_SUAVIZADO)

    mitad = VENTANA_SUAVIZADO // 2
    assert np.max(np.abs(propio - arbitro)) < 1e-9
    assert np.max(np.abs(propio[:mitad] - arbitro[:mitad])) < 1e-9  # extremo inicial
    assert np.max(np.abs(propio[-mitad:] - arbitro[-mitad:])) < 1e-9  # extremo final


def test_con_menos_muestras_que_la_ventana_la_serie_queda_intacta():
    serie = [100.0, 130.0, 90.0, 140.0, 110.0, 105.0]

    assert list(suavizar(serie)) == serie


# 63 --------------------------------------------------------------------------


def test_63_los_pesos_de_ventana_7_grado_2_son_los_publicados():
    publicados = [Fraction(p, 21) for p in (-2, 3, 6, 7, 6, 3, -2)]

    pesos = coeficientes()

    assert np.allclose(pesos, [float(p) for p in publicados], atol=1e-12)
    assert sum(pesos) == pytest.approx(1.0, abs=1e-12)


# --- La limpieza (RF-23, decisión 2.8) ---------------------------------------

INICIO = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def lectura(minuto: float, mg_dl: float, origen: str = "sensor") -> LecturaGlucosa:
    return LecturaGlucosa(
        uuid=uuid4(),
        usuario_uuid=uuid4(),
        ts_utc=INICIO + timedelta(minutes=minuto),
        zona_horaria="America/Monterrey",
        mg_dl=mg_dl,
        origen=origen,
    )


def serie_sensor(valores: list[float], cada: int = 5) -> list[LecturaGlucosa]:
    return [lectura(i * cada, v) for i, v in enumerate(valores)]


# 58 --------------------------------------------------------------------------


def test_58_una_tasa_imposible_se_marca_y_sigue_en_la_lista():
    # 100 → 160 en 5 minutos son 12 mg/dL/min.
    lecturas = serie_sensor([100, 102, 160, 104, 106])

    puntos = limpiar(lecturas)

    assert len(puntos) == 5
    [atipica] = [p for p in puntos if p.atipica]
    assert atipica.ts_utc == INICIO + timedelta(minutes=10)
    assert atipica.mg_dl == 160  # sin suavizar: tal como llegó
    assert [p.atipica for p in puntos] == [False, False, True, False, False]


# 59 --------------------------------------------------------------------------


def test_59_la_misma_tasa_entre_dos_manuales_no_marca_nada():
    lecturas = [lectura(0, 100, "manual"), lectura(5, 160, "manual")]

    puntos = limpiar(lecturas)

    assert [(p.mg_dl, p.atipica, p.origen) for p in puntos] == [
        (100, False, Origen.MANUAL),
        (160, False, Origen.MANUAL),
    ]


# 60 --------------------------------------------------------------------------


def test_60_un_hueco_de_10_min_se_rellena_y_uno_de_20_no():
    lecturas = [lectura(0, 100), lectura(10, 110), lectura(30, 130)]

    puntos = limpiar(lecturas)

    minutos = [(p.ts_utc - INICIO) / timedelta(minutes=1) for p in puntos]
    assert minutos == [0, 5, 10, 30]
    [interpolada] = [p for p in puntos if p.interpolada]
    assert interpolada.ts_utc == INICIO + timedelta(minutes=5)
    assert interpolada.mg_dl == 105
    assert interpolada.origen == Origen.SENSOR
    assert interpolada.zona_horaria == "America/Monterrey"


def test_un_hueco_de_15_min_exactos_se_rellena_con_dos_filas():
    puntos = limpiar([lectura(0, 100), lectura(15, 130)])

    assert [p.mg_dl for p in puntos if p.interpolada] == [110, 120]


# 61 --------------------------------------------------------------------------


def test_61_un_hueco_de_10_min_entre_dos_manuales_no_se_rellena():
    puntos = limpiar([lectura(0, 100, "manual"), lectura(10, 110, "manual")])

    assert len(puntos) == 2
    assert not any(p.interpolada for p in puntos)


def test_las_manuales_entran_tal_cual_aunque_haya_serie_del_sensor():
    """Una lectura de foto no se suaviza aunque caiga en medio de la serie."""
    lecturas = serie_sensor([100, 104, 108, 112, 116, 120, 124, 128])
    foto = lectura(12, 150, "foto_glucometro")

    puntos = limpiar([*lecturas, foto])

    [de_foto] = [p for p in puntos if p.origen == Origen.FOTO_GLUCOMETRO]
    assert de_foto.mg_dl == 150 and not de_foto.atipica and not de_foto.interpolada


# 64 --------------------------------------------------------------------------


def test_64_una_atipica_no_entra_al_suavizado():
    """Con la atípica dentro, los vecinos saldrían arrastrados hacia ella. Lo correcto es
    suavizar la serie **sin** ella: así lo fija esta prueba."""
    valores = [100, 103, 101, 104, 102, 105, 250, 106, 104, 107, 105, 108]
    lecturas = serie_sensor(valores)

    puntos = limpiar(lecturas)

    validas = [p for p in puntos if not p.atipica]
    sin_la_atipica = suavizar(valores[:6] + valores[7:])
    con_la_atipica = suavizar(valores)
    assert np.allclose([p.mg_dl for p in validas], sin_la_atipica, atol=1e-12)
    assert not np.allclose([p.mg_dl for p in validas], np.delete(con_la_atipica, 6))
    [atipica] = [p for p in puntos if p.atipica]
    assert atipica.mg_dl == 250


def test_un_hueco_largo_parte_el_suavizado_en_dos_tramos():
    """No se mezcla la señal de los dos lados de un hueco que no se interpoló."""
    primero = [100, 104, 99, 106, 101, 107, 102, 108]
    segundo = [180, 176, 183, 177, 184, 178, 185, 179]
    lecturas = serie_sensor(primero) + [lectura(60 + 5 * i, v) for i, v in enumerate(segundo)]

    puntos = limpiar(lecturas)

    assert np.allclose([p.mg_dl for p in puntos], list(suavizar(primero)) + list(suavizar(segundo)))
