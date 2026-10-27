"""La limpieza de la señal del sensor (RF-23, decisión 2.8 del paso 4).

Tres operaciones, en orden: atípicos por tasa de cambio, interpolación de huecos de hasta 15
minutos y suavizado Savitzky-Golay. **Solo sobre las lecturas de origen `sensor`**: una lectura
manual o de foto es un punto aislado, entre dos pinchazos separados por horas cualquier tasa de
cambio es posible, y suavizar dos puntos sueltos no significa nada. La referencia ya lo tiene
decidido en su firma: `es_atipica_por_tasa` y `se_puede_interpolar` reciben el origen.

Nada se borra. Una atípica sale marcada, no ausente: un dato descartado sin rastro es una falla
invisible, igual que en cuarentena.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from app.models.tablas import LecturaGlucosa
from app.services.pipeline.filtro import suavizar
from referencia.reglas_clinicas import (
    INTERPOLACION_MAX_MIN,
    Origen,
    es_atipica_por_tasa,
    se_puede_interpolar,
)

# El sensor reporta cada 5 minutos; las filas interpoladas caen en esa misma rejilla.
INTERVALO_SENSOR_MIN = 5
# Media muestra: dos marcas de tiempo más cercanas que esto son el mismo instante de la serie.
TOLERANCIA_MIN = INTERVALO_SENSOR_MIN / 2


@dataclass(frozen=True)
class Punto:
    """Una fila de la serie limpia.

    `zona_horaria` y `contexto_comida` son *keyword-only* para no mover el orden posicional que
    fija el documento del paso 4. La zona hace falta para la hora cíclica, el día de la semana y
    el día local de los agregados (regla 5); el contexto, para el juego disperso.
    """

    ts_utc: datetime
    mg_dl: float
    origen: Origen
    atipica: bool = False
    interpolada: bool = False
    zona_horaria: str = field(kw_only=True)
    contexto_comida: str | None = field(default=None, kw_only=True)


def limpiar(lecturas: Sequence[LecturaGlucosa]) -> list[Punto]:
    """Las tres operaciones de RF-23, en orden: atípicos, interpolación, suavizado.

    Solo toca las filas de origen `sensor` (decisión 2.8). Nada se borra: una atípica sale
    marcada, no ausente. Devuelve la serie ordenada por tiempo, con a lo más una fila por
    instante, que es la llave de `serie_limpia`.
    """
    sensor = sorted(
        (lectura for lectura in lecturas if lectura.origen == Origen.SENSOR),
        key=lambda lectura: lectura.ts_utc,
    )
    otras = [_punto(lectura) for lectura in lecturas if lectura.origen != Origen.SENSOR]

    # 1. Atípicos: se marcan y se apartan; no entran ni a la interpolación ni al suavizado.
    marcadas = _marcar_atipicas([_punto(lectura) for lectura in sensor])
    atipicas = [p for p in marcadas if p.atipica]
    validas = [p for p in marcadas if not p.atipica]

    # 2. Huecos de hasta 15 minutos, por interpolación lineal.
    con_huecos = _interpolar(validas, ocupados=[p.ts_utc for p in atipicas])

    # 3. Suavizado, por tramos continuos: no se mezcla la señal de dos lados de un hueco largo.
    suavizadas = [p for tramo in _tramos(con_huecos) for p in _suavizar_tramo(tramo)]

    return _una_por_instante(otras + atipicas + suavizadas)


def _punto(lectura: LecturaGlucosa) -> Punto:
    return Punto(
        lectura.ts_utc,
        lectura.mg_dl,
        Origen(lectura.origen),
        zona_horaria=lectura.zona_horaria,
        contexto_comida=lectura.contexto_comida,
    )


def _marcar_atipicas(serie: list[Punto]) -> list[Punto]:
    """Tasa de cambio > 4 mg/dL/min contra la última lectura **no** atípica.

    Comparar contra la anterior a secas marcaría también la lectura que vuelve a la normalidad
    después de un salto, que es buena.
    """
    marcadas: list[Punto] = []
    anterior: Punto | None = None
    for punto in serie:
        if anterior is not None and es_atipica_por_tasa(
            anterior.mg_dl, anterior.ts_utc, punto.mg_dl, punto.ts_utc, punto.origen
        ):
            marcadas.append(replace(punto, atipica=True))
        else:
            marcadas.append(punto)
            anterior = punto
    return marcadas


def _interpolar(validas: list[Punto], ocupados: list[datetime]) -> list[Punto]:
    """Rellena cada hueco de hasta 15 minutos entre dos lecturas válidas consecutivas.

    Las filas nuevas caen cada 5 minutos desde la lectura anterior, con `interpolada=True`,
    `origen=sensor` y la zona de la lectura anterior. Un hueco de más de 15 minutos se queda
    como está: interpolar ahí sería inventar datos (RF-23).

    No se crea una fila donde ya hay una atípica: no se puede borrar y dos filas no caben en
    el mismo instante. Ese lugar queda sin valor válido, y las características lo ven como
    `NaN`.
    """
    resultado: list[Punto] = []
    paso = timedelta(minutes=INTERVALO_SENSOR_MIN)
    tolerancia = timedelta(minutes=TOLERANCIA_MIN)
    for actual, siguiente in zip(validas, validas[1:], strict=False):
        resultado.append(actual)
        hueco = siguiente.ts_utc - actual.ts_utc
        if not se_puede_interpolar(hueco.total_seconds() / 60, Origen.SENSOR):
            continue
        instante = actual.ts_utc + paso
        while instante < siguiente.ts_utc - tolerancia:
            if not any(abs(instante - o) <= tolerancia for o in ocupados):
                fraccion = (instante - actual.ts_utc) / hueco
                resultado.append(
                    Punto(
                        instante,
                        actual.mg_dl + (siguiente.mg_dl - actual.mg_dl) * fraccion,
                        Origen.SENSOR,
                        interpolada=True,
                        zona_horaria=actual.zona_horaria,
                    )
                )
            instante += paso
    if validas:
        resultado.append(validas[-1])
    return resultado


def _tramos(serie: list[Punto]) -> list[list[Punto]]:
    """Parte la serie donde hay un hueco de más de 15 minutos, que ya no se interpoló."""
    tramos: list[list[Punto]] = []
    for punto in serie:
        if tramos and punto.ts_utc - tramos[-1][-1].ts_utc <= timedelta(
            minutes=INTERPOLACION_MAX_MIN
        ):
            tramos[-1].append(punto)
        else:
            tramos.append([punto])
    return tramos


def _suavizar_tramo(tramo: list[Punto]) -> list[Punto]:
    """Savitzky-Golay sobre el tramo; con menos de 7 muestras queda intacto."""
    valores = suavizar([p.mg_dl for p in tramo])
    return [replace(p, mg_dl=float(v)) for p, v in zip(tramo, valores, strict=True)]


def _una_por_instante(puntos: list[Punto]) -> list[Punto]:
    """Ordena por tiempo y deja una fila por instante, la llave de `serie_limpia`.

    Si dos caen en el mismo instante gana la lectura real sobre la interpolada, y la del sensor
    sobre la manual: es la que pertenece a la serie continua.
    """
    por_instante: dict[datetime, Punto] = {}
    for punto in sorted(puntos, key=lambda p: (p.interpolada, p.origen != Origen.SENSOR)):
        por_instante.setdefault(punto.ts_utc, punto)
    return sorted(por_instante.values(), key=lambda p: p.ts_utc)
