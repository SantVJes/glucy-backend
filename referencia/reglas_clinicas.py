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
from datetime import UTC, datetime
from enum import StrEnum

# ---------------------------------------------------------------------------
# Constantes. Que vivan en un solo lugar, no repartidas por el código.
# ---------------------------------------------------------------------------

GLUCOSA_MIN = 20  # mg/dL, RF-05
GLUCOSA_MAX = 600  # mg/dL, RF-05
UMBRAL_HIPO_DEFECTO = 70  # configurable 50-90
UMBRAL_HIPER_DEFECTO = 180  # configurable 140-300
RANGO_OBJETIVO = (70, 180)  # para el TIR

ABSORCION_DEFECTO_MIN = 180  # D-8; presets 30 (rápida) y 300 (lenta)
ABSORCION_MIN, ABSORCION_MAX = 30, 300

DIA_DEFECTO_H = 5  # duración de acción de la insulina, rango 2-8
DIA_RANGO_H = (2, 8)
PICO_INSULINA_MIN = 75  # insulinas rápidas (55 en ultrarrápidas)

FRESCURA_SENSOR_MIN = 15  # D-13: recomendación adoptada, pendiente de confirmar
INTERPOLACION_MAX_MIN = 15  # RF-23
TASA_CAMBIO_IMPOSIBLE = 4.0  # mg/dL por minuto, solo en serie continua

UMBRAL_HIPO_RANGO = (50, 90)  # lo que el perfil puede mover
UMBRAL_HIPER_RANGO = (140, 300)

CARBS_MIN_G = 0
CARBS_MAX_G = 300
INSULINA_MIN_UI = 0  # estricto: cero no es una dosis, es un campo sin llenar
INSULINA_MAX_UI = 50
INSULINA_RESOLUCION_UI = 0.5  # la pluma dosifica de media en media unidad
PESO_MIN_KG, PESO_MAX_KG = 25, 300
EDAD_MINIMA = 15
EDAD_MAXIMA = 120
TIPO_INSULINA_MAX_CARACTERES = 40
TIMEOUT_MODELO_LENGUAJE_S = 10

# Cuándo una cifra del periodo significa algo (RF-16). Los mismos valores que
# ConfiguracionDominio.diasMinimosIndicadores y .diasMinimosGmi en Swift.
DIAS_MINIMOS_INDICADORES = 3
DIAS_MINIMOS_GMI = 14


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


def validar_comida(
    carbs_g: float,
    tiempo_absorcion_min: int,
    porciones: float,
    ts_utc: datetime,
    ahora: datetime,
) -> Rechazo | None:
    """Espejo de `Validacion.validarComida` en Swift, con el mismo orden de comprobaciones.

    `carbs_g` son los gramos TOTALES, ya multiplicados por las porciones: volver a multiplicar
    aquí duplicaría el COB. `porciones` viaja solo como información, y por eso solo se pide
    que sea positiva.

    El orden decide qué motivo se reporta cuando la comida falla por dos cosas a la vez:
    1. rango de carbohidratos, 2. absorción, 3. porciones, 4. hora no futura.
    """
    if not (CARBS_MIN_G <= carbs_g <= CARBS_MAX_G):
        return Rechazo(f"carbohidratos fuera del rango {CARBS_MIN_G}-{CARBS_MAX_G} g")
    if not (ABSORCION_MIN <= tiempo_absorcion_min <= ABSORCION_MAX):
        return Rechazo(f"tiempo de absorción fuera del rango {ABSORCION_MIN}-{ABSORCION_MAX} min")
    if not porciones > 0:
        return Rechazo("porciones tiene que ser mayor que cero")
    # Una comida futura llegaría a `cob` con minutos negativos.
    if ts_utc > ahora:
        return Rechazo("marca de tiempo futura: corrompe el orden de la serie")
    return None


def validar_dosis(unidades: float, ts_utc: datetime, ahora: datetime) -> Rechazo | None:
    """Espejo de `Validacion.validarDosis` en Swift, con el mismo orden de comprobaciones.

    Revisa que la dosis sea *anotable*, no que sea la adecuada: opinar sobre la cantidad sería
    dosificar (regla 7). Por eso no recibe carbohidratos, glucosa ni ningún factor.

    `unidades % 0.5` es exacto porque 0.5 se representa sin error en binario (no así 0.1), y
    los negativos ya se rechazaron antes, así que el `%` de Python y el `truncatingRemainder`
    de Swift dan lo mismo.

    Orden: 1. mayor que cero, 2. a lo más 50 UI, 3. múltiplo de 0.5, 4. hora no futura.
    """
    if not unidades > INSULINA_MIN_UI:
        return Rechazo("unidades tiene que ser mayor que cero: cero no es una dosis")
    if not unidades <= INSULINA_MAX_UI:
        return Rechazo(f"unidades fuera del rango {INSULINA_MIN_UI}-{INSULINA_MAX_UI} UI")
    if unidades % INSULINA_RESOLUCION_UI != 0:
        return Rechazo(
            f"unidades fuera de la resolución de {INSULINA_RESOLUCION_UI} UI de la pluma"
        )
    # Una dosis futura contaría entera como insulina activa antes de haberse aplicado.
    if ts_utc > ahora:
        return Rechazo("marca de tiempo futura: corrompe el orden de la serie")
    return None


def validar_perfil(
    anio_nacimiento: int,
    umbral_hipo: float,
    umbral_hiper: float,
    duracion_accion_h: float,
    tiempo_absorcion_min: int,
    tipo_insulina_rapida: str | None,
    ahora: datetime,
) -> Rechazo | None:
    """Espejo de `Validacion.validarPerfil` en Swift, **sin nombre, apellidos ni peso**.

    Esos tres no llegan nunca al servidor, y una firma que no los acepta es la regla 3 hecha
    código: no hay manera de pasárselos por accidente.

    Mismo orden que el Swift, quitando los tres campos: año de nacimiento (no futuro, edad
    mínima, edad máxima), umbral de hipo, umbral de hiper, largo del tipo de insulina,
    duración de acción, absorción. La edad sale del año solo, en UTC, igual que
    `ReglasDePerfil.edad`: no se sabe más de la persona, a propósito.
    """
    edad = ahora.astimezone(UTC).year - anio_nacimiento
    if edad < 0:
        return Rechazo("año de nacimiento futuro")
    if edad < EDAD_MINIMA:
        return Rechazo(f"edad menor que {EDAD_MINIMA} años: el proyecto no tiene consentimiento")
    if edad > EDAD_MAXIMA:
        return Rechazo(f"año de nacimiento que da más de {EDAD_MAXIMA} años")
    bajo, alto = UMBRAL_HIPO_RANGO
    if not (bajo <= umbral_hipo <= alto):
        return Rechazo(f"umbral de hipoglucemia fuera del rango {bajo}-{alto} mg/dL")
    bajo, alto = UMBRAL_HIPER_RANGO
    if not (bajo <= umbral_hiper <= alto):
        return Rechazo(f"umbral de hiperglucemia fuera del rango {bajo}-{alto} mg/dL")
    maximo = TIPO_INSULINA_MAX_CARACTERES
    if tipo_insulina_rapida is not None and len(tipo_insulina_rapida) > maximo:
        return Rechazo(f"tipo de insulina de más de {maximo} caracteres")
    bajo, alto = DIA_RANGO_H
    if not (bajo <= duracion_accion_h <= alto):
        return Rechazo(f"duración de acción de la insulina fuera del rango {bajo}-{alto} h")
    if not (ABSORCION_MIN <= tiempo_absorcion_min <= ABSORCION_MAX):
        return Rechazo(f"tiempo de absorción fuera del rango {ABSORCION_MIN}-{ABSORCION_MAX} min")
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


def cob(
    carbs_g: float, minutos_desde_comida: float, tiempo_absorcion_min: int = ABSORCION_DEFECTO_MIN
) -> float:
    """COB(t) = carbs × (1 − t / tiempo_absorcion), y 0 pasado ese tiempo.

    Es una simplificación consciente y documentada, con el valor por omisión tomado de
    sistemas de lazo cerrado de código abierto. La alternativa exige datos que el usuario
    no captura y validación clínica que este proyecto no puede hacer.

    Caso de prueba P-11: 60 g con 180 min, a los 90 min → 30 g.

    Con minutos negativos —una comida que todavía no ocurre— devuelve 0 (paso 2, decisión
    2.3). Antes lanzaba y el Swift devolvía los gramos completos; devolver los gramos era la
    respuesta más peligrosa porque parece un número razonable. Las validaciones rechazan la
    hora futura, pero si algo lo esquiva, las tres implementaciones contestan lo mismo.
    """
    if minutos_desde_comida < 0:
        return 0.0
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


def fraccion_insulina_activa(
    minutos: float, dia_h: float = DIA_DEFECTO_H, pico_min: float = PICO_INSULINA_MIN
) -> float:
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


def iob(
    dosis: list[tuple[float, float]],
    dia_h: float = DIA_DEFECTO_H,
    pico_min: float = PICO_INSULINA_MIN,
) -> float:
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


def hay_suficientes_dias(dias_con_lecturas: int) -> bool:
    """Con menos de tres días distintos, un tiempo en rango describe un día suelto.

    Quien consulta tiene que decir que faltan datos, no mostrar un cero (RF-16). La puerta
    vive aquí y no en el servidor para que el teléfono, el backend y el entrenamiento la
    tengan en el mismo sitio.
    """
    return dias_con_lecturas >= DIAS_MINIMOS_INDICADORES


def gmi_es_fiable(dias_con_lecturas: int) -> bool:
    """El GMI estima la hemoglobina glucosilada, que resume semanas. Con seis pinchazos sale
    igual de bonito y no significa nada. La fórmula se validó sobre series de al menos 14
    días."""
    return dias_con_lecturas >= DIAS_MINIMOS_GMI


def indicadores(
    valores: list[float],
    umbral_hipo: int = UMBRAL_HIPO_DEFECTO,
    umbral_hiper: int = UMBRAL_HIPER_DEFECTO,
) -> Indicadores:
    """TIR, TBR, TAR, promedio, desviación, CV y GMI.

    GMI = 3.31 + 0.02392 × glucosa media en mg/dL.
    El TIR se calcula sobre el rango objetivo 70-180; el TBR y el TAR sobre los umbrales
    del perfil, que la persona puede cambiar.

    Calcula con cualquier lista no vacía: **esta función no decide si la cifra se enseña.**
    Esa puerta vive en `hay_suficientes_dias` (tres días distintos con lecturas) y en
    `gmi_es_fiable` (catorce días para el GMI), y la aplica quien consulta antes de llamar
    aquí, porque los días no se pueden contar con una lista de valores sin fecha. La pantalla
    dice **sobre cuántas lecturas** se calculó: una cifra sobre cuatro lecturas engaña.
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


def modo_actual(
    lectura_healthkit_activa: bool,
    ts_ultima_sensor: datetime | None,
    ahora: datetime,
    frescura_min: int = FRESCURA_SENSOR_MIN,
) -> Modo:
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

    **El orden de las condiciones decide el resultado**: las zonas se solapan y se evalúan de
    la más benigna a la más grave por diseño. Cambiar el orden cambia las métricas.

    ## El cotejo, rehecho el 29/10/2026 contra las dos implementaciones públicas

    Se comparó par por par sobre los 337 561 pares enteros de 20 a 600 mg/dL contra:

    - el puerto de Python de la implementación de MATLAB File Exchange
      (`suetAndTie/ClarkeErrorGrid`), leyendo su código fuente, y
    - el código SAS del paper 133-2013 del SAS Global Forum.

    Con el puerto, esta función **coincide en los 337 561 pares**. Con el código SAS difiere
    en cuatro familias, y tres son `<` contra `<=` en los umbrales exactos 70, 180 y 240, donde
    esta función ya toma la lectura severa. La cuarta sí es de fondo:

    **19 900 pares: real de 291 a 489 con predicho de `real + 110` o más.** Esta función decía
    **B** —igual que el puerto— y el código SAS dice **C**. El SAS tiene razón, y el motivo es
    bueno: el puerto acota la zona C con `real <= 290`, y **290 es el punto donde la recta
    `y = x + 110` se sale por arriba de una gráfica de 0 a 400 mg/dL**, que es exactamente el
    `set_ylim([0, 400])` de su código. No es una frontera clínica, es el borde del dibujo. El
    rango válido de Glucy es 20 a 600 (RF-05), así que ese tope recortaba la zona C justo donde
    este proyecto todavía tiene datos: un real de 300 predicho como 420 invita a sobrecorregir
    a lo grande, y salía contado como error benigno. Se quita el tope.

    ## Lo que la versión anterior de esta función tenía mal, y una corrección

    Antes acotaba la zona C por arriba en 180 (28 105 pares que son C y decía B) y comparaba
    con `70 < p < 180` donde va `70 <= p <= 180` (361 pares que son D y decía B). Las dos ya
    estaban corregidas.

    **Y una afirmación de este mismo docstring estaba equivocada.** Decía que para un real de
    59 a 70 con predicho de 71 a 180 el puerto público contestaba B por culpa de una condición
    `p >= (7/5)*real + 110`. Leído el archivo, la condición del puerto es `p >= (6/5)*real`,
    la misma de aquí, y contesta **D** igual que esta función. No había tal discrepancia: la
    comparación anterior se hizo contra una transcripción equivocada del puerto.

    ## Por qué importa

    B cuenta para el A+B que el proyecto promete en >= 95 %: llamar B a lo que es C o D infla
    justo la cifra que decide si el modelo sirve. Donde las formulaciones públicas difieren,
    aquí se toma **la severa**. Si al cotejar contra el artículo original resultara que la
    indulgente es la correcta, el proyecto habría reportado una métrica peor que la real, que
    es el error que se puede defender; al revés, no.

    `src/eval/clarke.py` de `glucy-ml` implementa esta misma formulación, y hay pruebas en los
    dos repositorios que fijan los casos concretos.

    Sigue pendiente cotejar contra el artículo original de 1987, que no está accesible sin
    suscripción. Hasta entonces, el documento final tiene que decir **qué formulación se usó**
    y no solo «rejilla de Clarke».
    """
    if (abs(predicho - real) <= 0.2 * real) or (real <= 70 and predicho <= 70):
        return "A"
    if (real >= 180 and predicho <= 70) or (real <= 70 and predicho >= 180):
        return "E"
    # Sin tope por arriba: el `real <= 290` del puerto público es el borde de una gráfica de
    # 400 mg/dL, no una frontera clínica, y aquí el rango llega a 600.
    if (real >= 70 and predicho >= real + 110) or (
        130 <= real <= 180 and predicho <= (7 / 5) * real - 182
    ):
        return "C"
    if (
        (real >= 240 and 70 <= predicho <= 180)
        or (real <= 175 / 3 and 70 <= predicho <= 180)
        or (175 / 3 <= real <= 70 and predicho >= 1.2 * real)
    ):
        return "D"
    return "B"


def porcentaje_clarke_ab(reales: list[float], predichos: list[float]) -> float:
    zonas = [zona_clarke(r, p) for r, p in zip(reales, predichos, strict=True)]
    return 100 * sum(1 for z in zonas if z in ("A", "B")) / len(zonas)


def sensibilidad_hipoglucemia(
    reales: list[float], predichos: list[float], umbral: int = UMBRAL_HIPO_DEFECTO
) -> float:
    """De los episodios reales por debajo del umbral, cuántos se anticiparon. Meta ≥ 85 %."""
    episodios = [(r, p) for r, p in zip(reales, predichos, strict=True) if r < umbral]
    if not episodios:
        raise ValueError("no hay episodios reales de hipoglucemia en el conjunto")
    return 100 * sum(1 for _, p in episodios if p < umbral) / len(episodios)


def tasa_falsas_alarmas(
    reales: list[float], predichos: list[float], umbral: int = UMBRAL_HIPO_DEFECTO
) -> float:
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


def plantilla_explicacion(
    valor_actual: float, valor_predicho: float, shap: list[tuple[str, float]]
) -> str:
    """Explicación armada por programa a partir de los mismos valores SHAP.

    Se usa cuando el modelo de lenguaje no responde en 10 s, cuando la respuesta no pasa
    la validación, cuando la computadora del backend está apagada y cuando la persona
    desactivó el asistente. Es menos natural de leer, pero es determinista, no cuesta nada
    y funciona sin internet. Nunca sugiere una dosis.

    **La dirección y las contribuciones se dicen por separado, y es la corrección C-15.**
    Antes decía «sube sobre todo POR X (-29 mg/dL)», y eso se lee como una contradicción: no
    se entiende que algo que resta haga subir. Y no era un problema de redacción: la dirección
    compara el valor predicho con el actual, mientras que una contribución SHAP se mide contra
    el valor base del modelo, no contra el de ahora. Son dos referencias distintas, así que la
    palabra «por» unía dos cosas que no se pueden unir. Ahora se enuncia la dirección y luego
    **lo que más pesó**, que es lo que SHAP de verdad dice, con su signo a la vista.

    Esta plantilla es el piso de la función de explicación —lo único que se promete que
    funciona con todo lo demás apagado—, así que no puede producir una frase que se contradice.
    """
    if valor_predicho < valor_actual:
        direccion = "Vas a bajar."
    elif valor_predicho > valor_actual:
        direccion = "Vas a subir."
    else:
        direccion = "Te mantienes igual."
    principales = sorted(shap, key=lambda kv: abs(kv[1]), reverse=True)[:2]
    partes = [f"{nombre} ({valor:+.0f} mg/dL)" for nombre, valor in principales]
    motivos = " y ".join(partes) if partes else "los datos de las últimas horas"
    return (
        f"{direccion} Lo que más pesa en la estimación: {motivos}. "
        "Es una estimación: conviene confirmar con una medición antes de actuar."
    )
