"""Savitzky-Golay con numpy (decisión 2.7 del paso 4).

Meter scipy en la imagen de la API para una sola función es mucho peso, y reescribir el filtro
a mano y esperar que esté bien es peor. Así que se escribe con numpy, que ya hace falta para el
vector de características, y `scipy.signal.savgol_filter` queda en `requirements-dev.txt` como
árbitro: una prueba compara las dos salidas en el centro y en los extremos.
"""

from collections.abc import Sequence
from functools import lru_cache

import numpy as np

VENTANA_SUAVIZADO = 7  # 7 muestras de 5 min = 35 min (decisión 2.7)
GRADO_SUAVIZADO = 2  # una parábola


@lru_cache
def _vandermonde(ventana: int, grado: int) -> np.ndarray:
    """Las potencias 0..grado de las posiciones −m..m de la ventana, una fila por posición."""
    if ventana % 2 == 0 or ventana <= grado:
        raise ValueError("la ventana tiene que ser impar y mayor que el grado")
    posiciones = np.arange(ventana) - ventana // 2
    return np.vander(posiciones, grado + 1, increasing=True)


@lru_cache
def _ajuste(ventana: int, grado: int) -> np.ndarray:
    """La pseudoinversa: multiplicada por una ventana de valores da los coeficientes de la
    parábola de mínimos cuadrados que mejor la ajusta."""
    return np.linalg.pinv(_vandermonde(ventana, grado))


def coeficientes(ventana: int = VENTANA_SUAVIZADO, grado: int = GRADO_SUAVIZADO) -> np.ndarray:
    """Los pesos del filtro: la fila central de la pseudoinversa de Vandermonde.

    El valor suavizado en el centro es el término independiente del polinomio ajustado, es
    decir la fila 0 de la pseudoinversa. Con ventana 7 y grado 2 salen
    (−2, 3, 6, 7, 6, 3, −2)/21, los publicados: es la comprobación de que este filtro es el de
    la literatura y no uno inventado.
    """
    return _ajuste(ventana, grado)[0].copy()


def suavizar(valores: Sequence[float]) -> np.ndarray:
    """Savitzky-Golay. Con menos muestras que la ventana devuelve la serie intacta.

    En el centro, cada valor es el promedio ponderado de su ventana. En los extremos, donde no
    hay ventana centrada, se ajusta la parábola a la primera (o la última) ventana completa y
    se evalúa en las posiciones que faltan: es lo que hace `savgol_filter` con su modo por
    omisión (`interp`), y es donde suelen fallar estas reescrituras.

    Supone muestras equiespaciadas: la serie continua del sensor, cada 5 minutos.
    """
    serie = np.asarray(valores, dtype=float)
    ventana, grado = VENTANA_SUAVIZADO, GRADO_SUAVIZADO
    if len(serie) < ventana:
        return serie.copy()

    mitad = ventana // 2
    salida = np.empty_like(serie)
    salida[mitad : len(serie) - mitad] = np.correlate(serie, coeficientes(), mode="valid")

    vandermonde, ajuste = _vandermonde(ventana, grado), _ajuste(ventana, grado)
    inicio = ajuste @ serie[:ventana]
    final = ajuste @ serie[-ventana:]
    salida[:mitad] = vandermonde[:mitad] @ inicio
    salida[len(serie) - mitad :] = vandermonde[mitad + 1 :] @ final
    return salida
