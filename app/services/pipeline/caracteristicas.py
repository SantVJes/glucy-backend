"""Los dos juegos de características de RF-24 (decisiones 2.9 y 2.10 del paso 4).

**Este módulo es la autoridad sobre los nombres y el orden.** El artefacto que entrene
`glucy-ml` recibe un vector de números en un orden; si aquí se llaman o se ordenan distinto, la
predicción se alimenta con las columnas cambiadas de lugar y nada falla: salen números
plausibles y equivocados. `glucy-ml` copia estas tuplas, no las reinventa.

Reglas que van con la lista:

- Lo que falta es `NaN`, **nunca cero**. Un rezago de 60 minutos que no existe porque la serie
  empieza ahí no es glucosa cero; el modelo trata el `NaN` como información y el cero como un
  valor.
- COB e IOB salen de la referencia (`cob_total`, `iob`). El IOB cuenta solo el bolo.
- Ninguna característica sale de una comida que la persona no registró (D-9, RF-37).
- Sin `actividad` ni `sueno` en el juego denso (C-10, C-11): no hay de dónde sacarlas, y
  entrenar con una variable que en producción siempre falta es peor que no tenerla.
"""

import math
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.services.pipeline.limpieza import TOLERANCIA_MIN, Punto
from referencia.reglas_clinicas import ABSORCION_DEFECTO_MIN, DIA_DEFECTO_H, cob_total, iob

CARACTERISTICAS_DENSAS: tuple[str, ...] = (
    "mg_dl", "rezago_5", "rezago_10", "rezago_15", "rezago_30", "rezago_60",
    "derivada_1", "derivada_2", "media_30", "media_60",
    "cob", "iob", "hora_sin", "hora_cos", "dia_semana",
)  # fmt: skip
CARACTERISTICAS_DISPERSAS: tuple[str, ...] = (
    "mg_dl", "antiguedad_min", "carbs_g", "dosis_ui",
    "cob", "iob", "hora_sin", "hora_cos", "contexto_comida", "promedio_7d",
)  # fmt: skip

# `contexto_comida` es categórica: un entero fijo por valor del enum. Sin contexto es un código
# propio, no un cero disfrazado. Cambiar un número de aquí obliga a reentrenar.
CODIGOS_CONTEXTO: dict[str | None, int] = {
    "en_ayunas": 0,
    "antes_de_comer": 1,
    "dos_horas_despues": 2,
    "antes_de_dormir": 3,
    "otro": 4,
    None: 5,
}

REZAGOS_MIN = (5, 10, 15, 30, 60)
MINUTOS_POR_DIA = 1440
FALTA = math.nan


def vector_denso(
    punto: datetime, serie: Sequence[Punto], comidas, dosis, perfil
) -> dict[str, float]:
    """El juego denso de RF-24, en el orden de CARACTERISTICAS_DENSAS.

    Lo que no se puede calcular es `NaN` y nunca cero (decisión 2.9): un rezago que no existe
    no es una glucosa de cero.

    `serie` es la serie limpia ordenada por tiempo; las filas atípicas se ignoran. Un valor «a
    los 5 minutos» es la fila válida más cercana a ese instante, a menos de media muestra.
    """
    validas = _validas(serie)
    actual = _valor_en(validas, punto)
    rezagos = {m: _valor_en(validas, punto - timedelta(minutes=m)) for m in REZAGOS_MIN}
    local = punto.astimezone(_zona_en(serie, punto))
    hora_sin, hora_cos = _hora_ciclica(local)

    vector = {
        "mg_dl": actual,
        **{f"rezago_{m}": rezagos[m] for m in REZAGOS_MIN},
        # mg/dL por minuto, y su cambio. NaN si falta cualquiera de los puntos.
        "derivada_1": (actual - rezagos[5]) / 5,
        "derivada_2": (actual - 2 * rezagos[5] + rezagos[10]) / 25,
        "media_30": _media(validas, punto - timedelta(minutes=30), punto),
        "media_60": _media(validas, punto - timedelta(minutes=60), punto),
        "cob": _cob(punto, comidas),
        "iob": _iob(punto, dosis, perfil),
        "hora_sin": hora_sin,
        "hora_cos": hora_cos,
        "dia_semana": float(local.weekday()),  # lunes = 0, en la zona de la fila
    }
    return {nombre: vector[nombre] for nombre in CARACTERISTICAS_DENSAS}


def vector_disperso(
    punto: datetime,
    ultima: Punto | None,
    comidas,
    dosis,
    perfil,
    *,
    serie: Sequence[Punto],
) -> dict[str, float]:
    """El juego disperso, para modo sin sensor. `antiguedad_min` es la edad de `ultima`.

    `serie` hace falta para `promedio_7d`: con la última lectura sola no se puede promediar
    una semana. Es *keyword-only* para no mover los argumentos que fija el documento.

    `carbs_g` y `dosis_ui` son los de la última comida y la última dosis de bolo que siguen
    activas en `punto` (dentro de su tiempo de absorción o de la duración de acción). Si no
    hay, `NaN`: no se inventa una comida (D-9, RF-37).
    """
    zona = _zona(ultima.zona_horaria) if ultima else UTC
    hora_sin, hora_cos = _hora_ciclica(punto.astimezone(zona))

    vector = {
        "mg_dl": ultima.mg_dl if ultima else FALTA,
        "antiguedad_min": _minutos(ultima.ts_utc, punto) if ultima else FALTA,
        "carbs_g": _ultima_comida_activa(punto, comidas),
        "dosis_ui": _ultima_dosis_activa(punto, dosis, perfil),
        "cob": _cob(punto, comidas),
        "iob": _iob(punto, dosis, perfil),
        "hora_sin": hora_sin,
        "hora_cos": hora_cos,
        "contexto_comida": float(CODIGOS_CONTEXTO[ultima.contexto_comida]) if ultima else FALTA,
        "promedio_7d": _media(_validas(serie), punto - timedelta(days=7), punto),
    }
    return {nombre: vector[nombre] for nombre in CARACTERISTICAS_DISPERSAS}


def como_fila(vector: dict[str, float], juego: tuple[str, ...]) -> list[float]:
    """El vector en el orden del juego. Es lo único que el modelo recibe (decisión 2.9).

    Un nombre de más o de menos es un error, no algo que se ignore: es justo el desajuste que
    produce números plausibles y equivocados.
    """
    if set(vector) != set(juego):
        sobran, faltan = set(vector) - set(juego), set(juego) - set(vector)
        raise ValueError(
            f"el vector no es del juego: sobran {sorted(sobran)}, faltan {sorted(faltan)}"
        )
    return [float(vector[nombre]) for nombre in juego]


# ---------------------------------------------------------------------------
# Auxiliares.
# ---------------------------------------------------------------------------


def _validas(serie: Sequence[Punto]) -> list[Punto]:
    return sorted((p for p in serie if not p.atipica), key=lambda p: p.ts_utc)


def _valor_en(validas: list[Punto], instante: datetime) -> float:
    """El valor de la fila válida más cercana a `instante`, a menos de media muestra, o NaN."""
    tolerancia = timedelta(minutes=TOLERANCIA_MIN)
    tiempos = [p.ts_utc for p in validas]
    i = bisect_left(tiempos, instante - tolerancia)
    candidatos = [p for p in validas[i:] if p.ts_utc <= instante + tolerancia]
    if not candidatos:
        return FALTA
    return min(candidatos, key=lambda p: abs(p.ts_utc - instante)).mg_dl


def _media(validas: list[Punto], desde: datetime, hasta: datetime) -> float:
    """Promedio de las filas válidas en `(desde, hasta]`, o NaN si no hay ninguna."""
    tiempos = [p.ts_utc for p in validas]
    ventana = validas[bisect_right(tiempos, desde) : bisect_right(tiempos, hasta)]
    return sum(p.mg_dl for p in ventana) / len(ventana) if ventana else FALTA


def _minutos(desde: datetime, hasta: datetime) -> float:
    return (hasta - desde).total_seconds() / 60


def _cob(punto: datetime, comidas) -> float:
    """`cob_total` de la referencia sobre las comidas registradas hasta `punto`. Sin comidas
    es 0, porque no hay nada que absorber; no es un dato que falte."""
    return cob_total(
        [
            (c.carbs_g, _minutos(c.ts_utc, punto), c.tiempo_absorcion_min or ABSORCION_DEFECTO_MIN)
            for c in comidas
            if c.ts_utc <= punto
        ]
    )


def _iob(punto: datetime, dosis, perfil) -> float:
    """`iob` de la referencia, **solo con las dosis de bolo**: la basal no se acumula como
    insulina activa en este modelo. La duración de acción es la del perfil, o 5 h."""
    return iob(
        [
            (d.unidades, _minutos(d.ts_utc, punto))
            for d in dosis
            if d.tipo == "bolo" and d.ts_utc <= punto
        ],
        dia_h=_duracion_accion_h(perfil),
    )


def _duracion_accion_h(perfil: Any) -> float:
    duracion = getattr(perfil, "duracion_accion_insulina", None) if perfil else None
    return duracion if duracion is not None else DIA_DEFECTO_H


def _ultima_comida_activa(punto: datetime, comidas) -> float:
    activas = [
        c
        for c in comidas
        if 0 <= _minutos(c.ts_utc, punto) < (c.tiempo_absorcion_min or ABSORCION_DEFECTO_MIN)
    ]
    return max(activas, key=lambda c: c.ts_utc).carbs_g if activas else FALTA


def _ultima_dosis_activa(punto: datetime, dosis, perfil) -> float:
    limite = _duracion_accion_h(perfil) * 60
    activas = [d for d in dosis if d.tipo == "bolo" and 0 <= _minutos(d.ts_utc, punto) < limite]
    return max(activas, key=lambda d: d.ts_utc).unidades if activas else FALTA


def _hora_ciclica(local: datetime) -> tuple[float, float]:
    """`sin` y `cos` de `2π × minutos/1440`: a las 23:50 y a las 00:10 la hora cruda está a
    23 horas de distancia y en realidad son veinte minutos."""
    minutos = local.hour * 60 + local.minute + local.second / 60
    angulo = 2 * math.pi * minutos / MINUTOS_POR_DIA
    return math.sin(angulo), math.cos(angulo)


def _zona_en(serie: Sequence[Punto], instante: datetime) -> tzinfo:
    """La zona de la última fila en o antes de `instante`; si no hay, la de la primera; si la
    serie está vacía, UTC, que es lo único que se sabe con certeza."""
    anteriores = [p for p in serie if p.ts_utc <= instante]
    if anteriores:
        return _zona(max(anteriores, key=lambda p: p.ts_utc).zona_horaria)
    return _zona(serie[0].zona_horaria) if serie else UTC


def _zona(nombre: str) -> tzinfo:
    try:
        return ZoneInfo(nombre)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return UTC
