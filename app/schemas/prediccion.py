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


class Factor(BaseModel):
    """Una contribución **lista para enseñarse**: con nombre en palabras y ya sumada.

    Va aparte de `shap` y no en su lugar porque las dos listas tienen consumidores distintos.
    `shap` es el contrato con el pipeline y con glucy-ml, y `/explain` lo necesita crudo.
    `factores` es lo que dibuja la pantalla de factores de la app, y ahí `rezago_30` no puede
    aparecer: la regla del proyecto es que en la superficie no hay tecnicismos.

    Son dos listas y no una porque `hora_sin` y `hora_cos` son **una sola idea** para quien lee
    —la hora del día— y dos columnas para el modelo. SHAP es aditivo, así que aquí se suman; en
    `shap` se quedan separadas, que es lo que el modelo entiende.

    Que la app no tenga que traducir también es a propósito: un diccionario de nombres de
    características repetido en Swift se queda viejo el día que el pipeline agrega una columna,
    y nadie se entera hasta que alguien lee «rezago_45» en la pantalla.
    """

    nombre: str
    mg_dl: float


class PrediccionHorizonte(BaseModel):
    """Una predicción, con la versión del modelo que la calculó (RF-25)."""

    horizonte_min: int
    #: El instante al que apunta: `ts_base` más el horizonte, **no el reloj más el horizonte**.
    #: Va explícito porque la app tiene que enseñar la hora y no «dentro de 30 minutos»: con
    #: una lectura de doce minutos de antigüedad, una predicción a 30 alcanza a dieciocho.
    ts_objetivo: datetime
    valor_predicho: float
    modelo_version: str
    alerta: Alerta | None = None
    shap: list[ContribucionShap]
    factores: list[Factor]


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
    #: El instante de la última lectura del **sensor**, que es donde se armó la fila y desde
    #: donde se cuenta el horizonte. `None` en modo sin sensor, donde no hay predicción.
    #:
    #: `valor_actual` puede no ser este valor: es la última lectura de cualquier origen, y un
    #: pinchazo capturado hace un minuto no entra al juego denso, que se construye sobre la
    #: serie continua. Son dos cosas distintas y la app las enseña distinto.
    ts_base: datetime | None = None
    valor_base: float | None = None
    puede_alertar_hipoglucemia: bool
    umbral_hipo: float
    umbral_hiper: float
    predicciones: list[PrediccionHorizonte]
    aviso: str | None = None
