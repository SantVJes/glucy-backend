"""
Glucy — reglas clínicas de referencia.

Este módulo es la *especificación ejecutable* de los cálculos que tienen que dar el mismo
número en los tres repositorios: en Swift dentro de la app (Domain/Rules), en el pipeline
del backend y en el entrenamiento del modelo. Si el Swift y esto no coinciden, uno de los
dos está mal.

Todo sale del Reporte del Avance 1 (19 sep 2026) y de los documentos 2 v6 y 3 v4.
Unidades: glucosa en mg/dL, tiempo en minutos, insulina en UI, carbohidratos en gramos.

Ninguna función de aquí calcula ni sugiere una dosis de insulina. Esa es la frontera entre
una herramienta de apoyo y un dispositivo médico regulado, y está fuera del alcance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

# ---------------------------------------------------------------------------
# Constantes. Que vivan en un solo lugar, no repartidas por el código.
# ---------------------------------------------------------------------------

GLUCOSA_MIN = 20             # mg/dL, RF-05
GLUCOSA_MAX = 600            # mg/dL, RF-05
UMBRAL_HIPO_DEFECTO = 70     # configurable 50-90
UMBRAL_HIPER_DEFECTO = 180   # configurable 140-300
RANGO_OBJETIVO = (70, 180)   # para el TIR

ABSORCION_DEFECTO_MIN = 180  # D-8; presets 30 (rápida) y 300 (lenta)
ABSORCION_MIN, ABSORCION_MAX = 30, 300

DIA_DEFECTO_H = 5            # duración de acción de la insulina, rango 2-8
PICO_INSULINA_MIN = 75       # insulinas rápidas (55 en ultrarrápidas)

FRESCURA_SENSOR_MIN = 15     # D-13: recomendación adoptada, pendiente de confirmar
INTERPOLACION_MAX_MIN = 15   # RF-23
TASA_CAMBIO_IMPOSIBLE = 4.0  # mg/dL por minuto, solo en serie continua

CARBS_MAX_G = 300
INSULINA_MAX_UI = 50
PESO_MIN_KG, PESO_MAX_KG = 25, 300
EDAD_MINIMA = 15
TIMEOUT_MODELO_LENGUAJE_S = 10


class Origen(StrEnum):
    SENSOR = "sensor"
    MANUAL = "manual"
    FOTO_GLUCOMETRO = "foto_glucometro"
    BARCODE = "barcode"
    OCR_ETIQUETA = "ocr_etiqueta"
    HEALTHKIT = "healthkit"


class Modo(StrEnum):
    SENSOR = "sensor"
    SIN_SENSOR = "sin_sensor"


# ---------------------------------------------------------------------------
# 1. Validación. Se aplica en el teléfono antes de guardar y otra vez en el
#    backend antes de persistir: un servidor nunca debe confiar en lo que le mandan.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Rechazo:
    """Un rechazo nunca es un descarte silencioso: lleva su motivo y va a cuarentena."""
    motivo: str


def validar_lectura(
    mg_dl: float,
    ts_utc: datetime,
    ahora: datetime,
    origen: Origen,
    confirmada_por_usuario: bool = True,
) -> Rechazo | None:
    """Devuelve None si la lectura es aceptable, o el Rechazo con su motivo.

    La confirmación del usuario es obligatoria para todo valor leído por OCR y **no existe
    umbral de confianza** (D-11, caso de prueba P-01).
    """
    if origen is Origen.FOTO_GLUCOMETRO and not confirmada_por_usuario:
        return Rechazo("valor de OCR sin confirmar: nada se guarda sin que la persona lo apruebe")
    if not (GLUCOSA_MIN <= mg_dl <= GLUCOSA_MAX):
        return Rechazo(f"fuera del rango fisiológico {GLUCOSA_MIN}-{GLUCOSA_MAX} mg/dL")
    if ts_utc > ahora:
        return Rechazo("marca de tiempo futura: corrompe el orden de la serie")
    return None


def es_atipica_por_tasa(
    mg_dl_previo: float, ts_previo: datetime, mg_dl: float, ts: datetime, origen: Origen
) -> bool:
    """Tasa de cambio imposible: > 4 mg/dL por minuto sostenido.

    Solo aplica a la serie continua del sensor. Entre dos pinchazos separados por horas
    cualquier tasa es posible, así que marcar eso como atípico sería un falso positivo.
    """
    if origen is not Origen.SENSOR:
        return False
    minutos = (ts - ts_previo).total_seconds() / 60
    if minutos <= 0:
        return False
    return abs(mg_dl - mg_dl_previo) / minutos > TASA_CAMBIO_IMPOSIBLE


def se_puede_interpolar(hueco_min: float, origen: Origen) -> bool:
    """Interpolar huecos de hasta 15 min, y solo en serie continua (RF-23).

    Interpolar entre dos lecturas manuales sería inventar datos.
    """
    return origen is Origen.SENSOR and 0 < hueco_min <= INTERPOLACION_MAX_MIN


# ---------------------------------------------------------------------------
# 2. Carbohidratos activos (COB). Absorción lineal, sin modelo fisiológico (D-8).
# ---------------------------------------------------------------------------

def cob(carbs_g: float, minutos_desde_comida: float,
        tiempo_absorcion_min: int = ABSORCION_DEFECTO_MIN) -> float:
    """COB(t) = carbs × (1 − t / tiempo_absorcion), y 0 pasado ese tiempo.

    Es una simplificación consciente y documentada, con el valor por omisión tomado de
    sistemas de lazo cerrado de código abierto. La alternativa exige datos que el usuario
    no captura y validación clínica que este proyecto no puede hacer.

    Caso de prueba P-11: 60 g con 180 min, a los 90 min → 30 g.
    """
    if minutos_desde_comida < 0:
        raise ValueError("el tiempo desde la comida no puede ser negativo")
    if minutos_desde_comida >= tiempo_absorcion_min:
        return 0.0
    return carbs_g * (1 - minutos_desde_comida / tiempo_absorcion_min)


def cob_total(comidas: list[tuple[float, float, int]]) -> float:
    """Suma el COB de varias comidas. Cada tupla es (carbs_g, minutos_desde, absorcion_min).

    No se infiere ninguna comida que la persona no haya registrado (D-9, RF-37): esta
    función solo suma lo que se le da.
    """
    return sum(cob(c, t, a) for c, t, a in comidas)


# ---------------------------------------------------------------------------
# 3. Insulina activa (IOB). Modelo exponencial, el de los sistemas de lazo cerrado abierto.
# ---------------------------------------------------------------------------

def fraccion_insulina_activa(minutos: float, dia_h: float = DIA_DEFECTO_H,
                             pico_min: float = PICO_INSULINA_MIN) -> float:
    """Fracción de una dosis que sigue activa a los `minutos` indicados.

    Curva exponencial con pico ~75 min y duración de acción de 5 h por omisión (rango
    2-8 h, que es lo que el perfil pregunta). Sin esos dos campos la insulina activa se
    calcularía con una curva equivocada.
    """
    dia_min = dia_h * 60
    if minutos <= 0:
        return 1.0
    if minutos >= dia_min:
        return 0.0
    tau = pico_min * (1 - pico_min / dia_min) / (1 - 2 * pico_min / dia_min)
    a = 2 * tau / dia_min
    s = 1 / (1 - a + (1 + a) * math.exp(-dia_min / tau))
    factor = minutos**2 / (tau * dia_min * (1 - a)) - minutos / tau - 1
    restante = 1 - s * (1 - a) * (factor * math.exp(-minutos / tau) + 1)
    return min(1.0, max(0.0, restante))


def iob(dosis: list[tuple[float, float]], dia_h: float = DIA_DEFECTO_H,
        pico_min: float = PICO_INSULINA_MIN) -> float:
    """Insulina activa total. Cada tupla es (unidades, minutos_desde_la_dosis).

    Solo cuenta la insulina de bolo: la basal no se acumula como insulina activa en este
    modelo, y la basal temporal no se modela porque no hay bomba en el alcance.
    """
    return sum(u * fraccion_insulina_activa(m, dia_h, pico_min) for u, m in dosis)


# ---------------------------------------------------------------------------
# 4. Indicadores clínicos. Se calculan en el teléfono, sin backend.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Indicadores:
    n: int
    promedio: float
    desviacion: float
    coeficiente_variacion: float
    tir: float
    tbr: float
    tar: float
    gmi: float


def indicadores(valores: list[float], umbral_hipo: int = UMBRAL_HIPO_DEFECTO,
                umbral_hiper: int = UMBRAL_HIPER_DEFECTO) -> Indicadores:
    """TIR, TBR, TAR, promedio, desviación, CV y GMI.

    GMI = 3.31 + 0.02392 × glucosa media en mg/dL.
    El TIR se calcula sobre el rango objetivo 70-180; el TBR y el TAR sobre los umbrales
    del perfil, que la persona puede cambiar.

    La pantalla de historial dice **sobre cuántas lecturas** se calculó, y no calcula nada
    con menos de tres días de datos: una cifra sobre cuatro lecturas engaña.
    """
    if not valores:
        raise ValueError(
            "no hay lecturas: la pantalla debe decir que faltan datos, no mostrar cero"
        )
    n = len(valores)
    promedio = sum(valores) / n
    varianza = sum((v - promedio) ** 2 for v in valores) / n
    desviacion = math.sqrt(varianza)
    bajo, alto = RANGO_OBJETIVO
    tir = 100 * sum(1 for v in valores if bajo <= v <= alto) / n
    tbr = 100 * sum(1 for v in valores if v < umbral_hipo) / n
    tar = 100 * sum(1 for v in valores if v > umbral_hiper) / n
    return Indicadores(
        n=n,
        promedio=promedio,
        desviacion=desviacion,
        coeficiente_variacion=100 * desviacion / promedio if promedio else 0.0,
        tir=tir,
        tbr=tbr,
        tar=tar,
        gmi=3.31 + 0.02392 * promedio,
    )


# ---------------------------------------------------------------------------
# 5. Decisión de modo (RF-06c). La regla que evita predecir con datos rancios.
# ---------------------------------------------------------------------------

def modo_actual(lectura_healthkit_activa: bool, ts_ultima_sensor: datetime | None,
                ahora: datetime, frescura_min: int = FRESCURA_SENSOR_MIN) -> Modo:
    """Devuelve el modo en el que la app tiene derecho a estar.

    Si la última lectura del sensor pasa el umbral de frescura, degrada a modo sin sensor
    **y la pantalla lo dice**, en lugar de seguir prediciendo con datos viejos (caso P-03).
    """
    if not lectura_healthkit_activa or ts_ultima_sensor is None:
        return Modo.SIN_SENSOR
    antiguedad_min = (ahora - ts_ultima_sensor).total_seconds() / 60
    return Modo.SENSOR if antiguedad_min <= frescura_min else Modo.SIN_SENSOR


def puede_alertar_hipoglucemia(modo: Modo) -> bool:
    """En modo sin sensor no hay alerta anticipada, y la app lo declara en pantalla.

    RF-10b y riesgo R-6. Un sistema que promete una alerta que no puede dar es peor que
    uno que no la promete (caso P-04).
    """
    return modo is Modo.SENSOR


# ---------------------------------------------------------------------------
# 6. Sincronización (RF-35, RF-36). Solo wifi, por lotes, lo más antiguo primero.
# ---------------------------------------------------------------------------

def debe_sincronizar(hay_wifi: bool, pendientes: int, forzado_por_usuario: bool = False) -> bool:
    """No sincroniza con datos móviles salvo que la persona toque «sincronizar ahora».

    Caso P-08. Se gana batería y plan de datos, se pierde inmediatez en una función que no
    es de emergencia.
    """
    if pendientes <= 0:
        return False
    return hay_wifi or forzado_por_usuario


# ---------------------------------------------------------------------------
# 7. Métricas de evaluación del modelo.
# ---------------------------------------------------------------------------

def rmse(reales: list[float], predichos: list[float]) -> float:
    n = len(reales)
    return math.sqrt(sum((r - p) ** 2 for r, p in zip(reales, predichos, strict=True)) / n)


def mae(reales: list[float], predichos: list[float]) -> float:
    n = len(reales)
    return sum(abs(r - p) for r, p in zip(reales, predichos, strict=True)) / n


def mard(reales: list[float], predichos: list[float]) -> float:
    """Error absoluto relativo medio, en por ciento. Es con lo que se comparan los sensores."""
    n = len(reales)
    return 100 * sum(abs(r - p) / r for r, p in zip(reales, predichos, strict=True)) / n


def zona_clarke(real: float, predicho: float) -> str:
    """Zona de la rejilla de error de Clarke (A a E) para una predicción.

    Clasifica el error por su **consecuencia clínica**, no por su tamaño: un error de
    30 mg/dL cerca de 70 es peligroso, el mismo cerca de 200 no lo es. Meta del proyecto:
    ≥ 95 % de las predicciones en A+B.

    Implementación de la formulación habitual de Clarke et al. (1987). Antes de reportar
    métricas en el documento final conviene cotejarla contra el artículo original y contra
    una implementación publicada: el orden de las condiciones es lo que decide el resultado.
    """
    if (abs(predicho - real) <= 0.2 * real) or (real <= 70 and predicho <= 70):
        return "A"
    if (real >= 180 and predicho <= 70) or (real <= 70 and predicho >= 180):
        return "E"
    if (real <= 70 < predicho < 180) or (real >= 240 and 70 < predicho < 180):
        return "D"
    if (70 <= real <= 180 and predicho >= real + 110) or (
        130 <= real <= 180 and predicho <= (7 / 5) * real - 182
    ):
        return "C"
    return "B"


def porcentaje_clarke_ab(reales: list[float], predichos: list[float]) -> float:
    zonas = [zona_clarke(r, p) for r, p in zip(reales, predichos, strict=True)]
    return 100 * sum(1 for z in zonas if z in ("A", "B")) / len(zonas)


def sensibilidad_hipoglucemia(reales: list[float], predichos: list[float],
                              umbral: int = UMBRAL_HIPO_DEFECTO) -> float:
    """De los episodios reales por debajo del umbral, cuántos se anticiparon. Meta ≥ 85 %."""
    episodios = [(r, p) for r, p in zip(reales, predichos, strict=True) if r < umbral]
    if not episodios:
        raise ValueError("no hay episodios reales de hipoglucemia en el conjunto")
    return 100 * sum(1 for _, p in episodios if p < umbral) / len(episodios)


def tasa_falsas_alarmas(reales: list[float], predichos: list[float],
                        umbral: int = UMBRAL_HIPO_DEFECTO) -> float:
    """De todas las alertas emitidas, cuántas no correspondieron a un episodio real.

    Meta ≤ 15 %, y se trata como criterio de aceptación: si la app alerta de más, la
    persona deja de hacerle caso y el sistema pierde todo su valor.
    """
    alertas = [(r, p) for r, p in zip(reales, predichos, strict=True) if p < umbral]
    if not alertas:
        return 0.0
    return 100 * sum(1 for r, _ in alertas if r >= umbral) / len(alertas)


def linea_base_persistencia(serie: list[float], pasos_horizonte: int) -> list[float]:
    """«La glucosa dentro de 30 minutos será igual a la de ahora».

    Es la línea base obligatoria: un modelo que no le gana a esto no justifica su
    existencia.
    """
    if pasos_horizonte <= 0:
        raise ValueError("el horizonte debe ser de al menos un paso")
    return serie[:-pasos_horizonte]


# ---------------------------------------------------------------------------
# 8. Plantilla determinista de la explicación (el respaldo del punto 11.8).
# ---------------------------------------------------------------------------

def plantilla_explicacion(valor_actual: float, valor_predicho: float,
                          shap: list[tuple[str, float]]) -> str:
    """Explicación armada por programa a partir de los mismos valores SHAP.

    Se usa cuando el modelo de lenguaje no responde en 10 s, cuando la respuesta no pasa
    la validación, cuando la computadora del backend está apagada y cuando la persona
    desactivó el asistente. Es menos natural de leer, pero es determinista, no cuesta nada
    y funciona sin internet. Nunca sugiere una dosis.
    """
    direccion = "baja" if valor_predicho < valor_actual else "sube"
    principales = sorted(shap, key=lambda kv: abs(kv[1]), reverse=True)[:2]
    partes = [f"{nombre} ({valor:+.0f} mg/dL)" for nombre, valor in principales]
    motivos = " y por ".join(partes) if partes else "los datos de las últimas horas"
    return (
        f"{direccion.capitalize()} sobre todo por {motivos}. "
        "Es una estimación: conviene confirmar con una medición antes de actuar."
    )
