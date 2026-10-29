"""Lo que devuelve `GET /predict` (paso 5).

La respuesta dice **con qué modo respondió** (RF-21) y, en modo sin sensor, **declara que no
puede anticipar hipoglucemias** (RF-10b). Esa declaración no es un texto decorativo: es la
diferencia entre informar y prometer algo que el sistema no puede dar.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Modo = Literal["sensor", "sin_sensor"]
# La alerta se **deriva** del valor comparándolo con el umbral del perfil; el modelo predice un
# número, no una clase. Así la persona ve la curva y entiende por qué se disparó (RF-26).
Alerta = Literal["hipoglucemia", "hiperglucemia"]

AVISO_SIN_SENSOR = (
    "Sin sensor conectado no se puede anticipar una glucosa baja: solo se estima a partir de "
    "mediciones sueltas, y conviene medirte antes de actuar."
)


class ContribucionShap(BaseModel):
    """Lo que aportó una característica, en mg/dL y con signo. Es lo que consume `/explain`."""

    variable: str
    mg_dl: float


class PrediccionHorizonte(BaseModel):
    """Una predicción, con la versión del modelo que la calculó (RF-25)."""

    horizonte_min: int
    valor_predicho: float
    modelo_version: str
    alerta: Alerta | None = None
    shap: list[ContribucionShap]


class RespuestaPredecir(BaseModel):
    """Las predicciones del momento, o ninguna y el motivo.

    `predicciones` viene vacía en modo sin sensor: este paso no incluye M-3, el modelo del pico
    después de una comida, porque su salida es distinta —un valor y cuándo ocurre— y se dispara
    con una comida, no con el reloj.
    """

    ts_utc: datetime
    modo: Modo
    valor_actual: float | None
    antiguedad_min: float | None
    puede_alertar_hipoglucemia: bool
    umbral_hipo: float
    umbral_hiper: float
    predicciones: list[PrediccionHorizonte]
    aviso: str | None = None
