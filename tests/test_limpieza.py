"""Pruebas 58 a 64: la limpieza de la serie del sensor (RF-23) y el filtro que la suaviza.

El filtro se escribió con numpy, y `scipy.signal.savgol_filter` es el árbitro (decisión 2.7).
"""

from fractions import Fraction

import numpy as np
import pytest
from scipy.signal import savgol_filter

from app.services.pipeline.filtro import (
    GRADO_SUAVIZADO,
    VENTANA_SUAVIZADO,
    coeficientes,
    suavizar,
)

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
