"""Arma `tableros/glucy.json` desde las consultas de `consultas/`.

El tablero **no se escribe a mano**. El JSON de Grafana es largo y lleno de campos que no
significan nada, y la consulta es lo único que importa de cada panel: si el SQL vive en un
archivo aparte, se puede leer, se puede correr contra la base y se puede revisar en un pull
request. Pegado dentro del JSON, con los saltos de línea escapados, no se puede hacer ninguna
de las tres cosas.

Correrlo:

    python grafana/armar_tablero.py          # reescribe el JSON
    python grafana/armar_tablero.py --ver    # solo dice si el JSON está al día

`tests/test_tablero.py` corre lo segundo, así que un cambio en un `.sql` que no se refleje en
el JSON hace fallar la integración continua en lugar de quedar como un panel que enseña una
consulta vieja.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from dataclasses import dataclass, field

AQUI = pathlib.Path(__file__).parent
CONSULTAS = AQUI / "consultas"
SALIDA = AQUI / "tableros" / "glucy.json"
ORIGEN = {"type": "grafana-postgresql-datasource", "uid": "glucy-postgres"}

# La regla del Documento 3 para este tablero, escrita donde se ve: todo panel con pocas
# personas detrás se marca **no concluyente**. Con doce sujetos no hay población, hay doce
# fisiologías (riesgo R-2), y una curva promedio invita a leerla como si fuera una población.
MINIMO_CONCLUYENTE = 30
AVISO = (
    "**Este tablero no es un resultado de población.** Enseña los datos seudonimizados de "
    f"las personas que usan Glucy, y mientras sean menos de {MINIMO_CONCLUYENTE} toda curva "
    "de aquí abajo es **no concluyente**: describe a quien está, no a quien tiene diabetes. "
    "Ningún panel lleva nombres, y el servidor no los tiene (regla 3): solo conoce un UUID.\n\n"
    "Glucy no es un dispositivo médico certificado: informa, nunca prescribe ni administra, y "
    "jamás calcula ni sugiere una dosis de insulina."
)


@dataclass
class Panel:
    """Un panel: su título, su consulta y lo poco de presentación que de verdad decide algo."""

    titulo: str
    descripcion: str
    consulta: str
    tipo: str
    formato: str
    ancho: int
    alto: int
    unidad: str | None = None
    porcentajes: tuple[str, ...] = ()
    eje_x: str | None = None
    min_y: float | None = None
    max_y: float | None = None
    mapeos: dict[str, str] = field(default_factory=dict)


PANELES: list[Panel] = [
    Panel(
        titulo="Personas en el periodo",
        descripcion=(
            "Cuántas personas distintas hay detrás de todo lo demás. Con menos de "
            f"{MINIMO_CONCLUYENTE} el tablero entero es no concluyente."
        ),
        consulta="00-personas-en-el-periodo.sql",
        tipo="stat",
        formato="table",
        ancho=6,
        alto=4,
    ),
    Panel(
        titulo="Glucosa por hora del día",
        descripcion=(
            "Promedio y rango por hora **local** de cada lectura, con su propia zona horaria. "
            "Se lee de `serie_limpia` y no de los agregados porque `agregados_horarios` guarda "
            "la hora local convertida a UTC y no tiene columna de zona, así que de ahí saldría "
            "la hora UTC: en México, la curva corrida seis horas (C-14). Sin filas atípicas."
        ),
        consulta="01-distribucion-por-hora.sql",
        tipo="barchart",
        formato="table",
        ancho=12,
        alto=9,
        unidad="mgdL",
        eje_x="Hora local",
    ),
    Panel(
        titulo="Tiempo en rango, bajo y alto",
        descripcion=(
            "TIR, TBR y TAR por día **local**, leídos ya calculados de `agregados_diarios`: "
            "los calcula el pipeline con la referencia clínica, y rehacerlos en SQL sería una "
            "cuarta implementación de las mismas reglas sin nada que la compare. Rango "
            "objetivo 70-180 mg/dL. Con varias zonas horarias un mismo día de calendario "
            "aparece como puntos distintos (C-14)."
        ),
        consulta="02-tir-tbr-tar.sql",
        tipo="timeseries",
        formato="time_series",
        ancho=12,
        alto=9,
        unidad="percent",
        min_y=0,
        max_y=100,
    ),
    Panel(
        titulo="Episodios de hipoglucemia, los nocturnos aparte",
        descripcion=(
            "Un episodio es una racha por debajo de 70 mg/dL; dos rachas separadas por menos "
            "de 15 minutos son el mismo episodio. Nocturno es 00:00-06:00 en hora **local**. "
            "No entran las filas interpoladas ni las atípicas: una hipoglucemia inventada por "
            "una interpolación es el dato que más alarma de todo el tablero."
        ),
        consulta="03-episodios-de-hipoglucemia.sql",
        tipo="timeseries",
        formato="time_series",
        ancho=12,
        alto=9,
        min_y=0,
    ),
    Panel(
        titulo="Desempeño del modelo contra la persistencia",
        descripcion=(
            "Las dos columnas de RMSE se calculan sobre **las mismas** predicciones. Un RMSE "
            "suelto no dice nada: la comparación honesta es contra «dentro de 30 minutos será "
            "igual que ahora», y un modelo que no le gana no justifica su existencia. El valor "
            "real se busca por tiempo, con 2.5 minutos de tolerancia, no por posición."
        ),
        consulta="04-desempeno-del-modelo.sql",
        tipo="table",
        formato="table",
        ancho=12,
        alto=9,
        porcentajes=("MARD %",),
    ),
    Panel(
        titulo="Alertas y falsas alarmas por versión",
        descripcion=(
            "La tasa de falsas alarmas es criterio de aceptación del proyecto: **≤ 15 %**. Se "
            "calcula solo sobre las alertas con desenlace conocido; contar las desconocidas "
            "como acertadas bajaría la tasa sin que nada hubiera mejorado."
        ),
        consulta="05-alertas-y-falsas-alarmas.sql",
        tipo="table",
        formato="table",
        ancho=12,
        alto=9,
        porcentajes=("% falsas (meta <= 15)",),
    ),
    Panel(
        titulo="Qué hay en la cuarentena",
        descripcion=(
            "RF-22 obliga a conservar lo rechazado con su motivo, y para esto sirve: un motivo "
            "que se repite mil veces es un error de la app, no mil datos malos. Nada se "
            "descarta en silencio."
        ),
        consulta="06a-cuarentena.sql",
        tipo="table",
        formato="table",
        ancho=12,
        alto=9,
    ),
    Panel(
        titulo="Salud de la cola hacia el Learning Record Store",
        descripcion=(
            "«Pendiente» es exactamente «sin enviar y sin rechazar» (C-12). Lo que hay que "
            "mirar no es el número de pendientes, que sube y baja, sino **la más antigua**: una "
            "cola que se vacía con tres días de retraso funciona y a la vez está mal, y es lo "
            "único que delata un LRS apagado desde el martes."
        ),
        consulta="06b-cola-del-lrs.sql",
        tipo="table",
        formato="table",
        ancho=12,
        alto=7,
    ),
    Panel(
        titulo="Sentencias xAPI por verbo",
        descripcion=(
            "Actividad registrada en el Learning Record Store. Tres de los seis verbos no están "
            "en el perfil de ADL y usan vocabulario propio o de Activity Streams; está dicho en "
            "`docs/fase6-paso-1-learning-record-store.md` y fijado con una prueba."
        ),
        consulta="07a-aprendizaje-por-verbo.sql",
        tipo="timeseries",
        formato="time_series",
        ancho=12,
        alto=9,
        min_y=0,
    ),
    Panel(
        titulo="Indicadores de aprendizaje",
        descripcion=(
            "Contar sentencias es actividad; lo que dice algo de autocuidado es la "
            "**proporción**: de los avisos que recibió, a cuántos respondió, y de los módulos "
            "que abrió, cuántos terminó. Esas dos son las que van al reporte."
        ),
        consulta="07b-indicadores-de-aprendizaje.sql",
        tipo="table",
        formato="table",
        ancho=12,
        alto=7,
        porcentajes=("% de respuesta", "% terminados"),
    ),
    Panel(
        titulo="Explicaciones: del modelo o de la plantilla",
        descripcion=(
            "La plantilla determinista no es un plan de emergencia: es el piso de la función "
            "(P-13), y este panel dice cada cuánto se pisa. La bitácora guarda cuál de las dos "
            "contestó y cuánto tardó, **no el texto de la explicación ni un solo valor de "
            "glucosa** (C-13)."
        ),
        consulta="08a-uso-del-modelo-de-lenguaje.sql",
        tipo="timeseries",
        formato="time_series",
        ancho=12,
        alto=9,
        min_y=0,
    ),
    Panel(
        titulo="Por qué salió la plantilla, y cuánto tarda cada camino",
        descripcion=(
            "Los motivos no son equivalentes. `sin_asistente` es la persona que lo apagó y está "
            "bien. `sin_respuesta` es Ollama apagado o pasado de los diez segundos. "
            "`cifra_inventada` y `patron_de_dosificacion` son el modelo portándose mal, y son "
            "los dos que hay que mirar: es la validación de la regla 7 haciendo su trabajo."
        ),
        consulta="08b-por-que-salio-la-plantilla.sql",
        tipo="table",
        formato="table",
        ancho=12,
        alto=9,
        unidad="ms",
        mapeos={"ms medios": "ms", "ms peor caso": "ms"},
    ),
]


def _consulta(nombre: str) -> str:
    texto = (CONSULTAS / nombre).read_text()
    if "$__timeFilter" not in texto and nombre != "00-personas-en-el-periodo.sql":
        raise SystemExit(f"{nombre}: sin $__timeFilter, el panel ignoraría el rango elegido")
    return texto.rstrip() + "\n"


def _anulaciones(panel: Panel) -> list[dict]:
    """Las unidades por columna. Sin esto una tasa se dibuja como «41.9» y no como «41.9 %»."""
    salida = []
    for columna in panel.porcentajes:
        salida.append(
            {
                "matcher": {"id": "byName", "options": columna},
                "properties": [{"id": "unit", "value": "percent"}],
            }
        )
    for columna, unidad in panel.mapeos.items():
        salida.append(
            {
                "matcher": {"id": "byName", "options": columna},
                "properties": [{"id": "unit", "value": unidad}],
            }
        )
    return salida


def _panel(panel: Panel, identificador: int, x: int, y: int) -> dict:
    personalizado: dict = {}
    if panel.tipo == "timeseries":
        personalizado = {"lineWidth": 2, "fillOpacity": 8, "showPoints": "never"}
    elif panel.tipo == "barchart":
        personalizado = {"fillOpacity": 80, "lineWidth": 1}

    campos: dict = {"custom": personalizado}
    if panel.unidad and not panel.mapeos:
        campos["unit"] = panel.unidad
    if panel.min_y is not None:
        campos["min"] = panel.min_y
    if panel.max_y is not None:
        campos["max"] = panel.max_y

    opciones: dict = {}
    if panel.tipo == "barchart":
        opciones = {
            "xField": panel.eje_x,
            "orientation": "vertical",
            "legend": {"showLegend": True},
        }
    elif panel.tipo == "stat":
        opciones = {
            "colorMode": "background",
            "graphMode": "none",
            "textMode": "value_and_name",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        }

    return {
        "id": identificador,
        "type": panel.tipo,
        "title": panel.titulo,
        "description": panel.descripcion,
        "datasource": ORIGEN,
        "gridPos": {"x": x, "y": y, "w": panel.ancho, "h": panel.alto},
        "fieldConfig": {"defaults": campos, "overrides": _anulaciones(panel)},
        "options": opciones,
        "targets": [
            {
                "refId": "A",
                "datasource": ORIGEN,
                "editorMode": "code",
                "rawQuery": True,
                "rawSql": _consulta(panel.consulta),
                "format": panel.formato,
            }
        ],
    }


def armar() -> dict:
    """El tablero completo. El panel de aviso va primero y no se puede quitar desde la interfaz."""
    paneles: list[dict] = [
        {
            "id": 1,
            "type": "text",
            "title": "Cómo se lee este tablero",
            "datasource": ORIGEN,
            "gridPos": {"x": 6, "y": 0, "w": 18, "h": 4},
            "options": {"mode": "markdown", "content": AVISO},
        }
    ]

    identificador = 2
    x = 0
    y = 0
    alto_de_la_fila = 0
    for panel in PANELES:
        if x + panel.ancho > 24:
            # `y` avanza lo que mida el panel más alto de la fila, no uno: Grafana reacomoda
            # los solapes por su cuenta y el resultado deja de parecerse a lo que dice aquí.
            x = 0
            y += alto_de_la_fila
            alto_de_la_fila = 0
        paneles.append(_panel(panel, identificador, x, y))
        identificador += 1
        x += panel.ancho
        alto_de_la_fila = max(alto_de_la_fila, panel.alto)
        if panel.titulo == "Personas en el periodo":
            x = 0
            y = 4
            alto_de_la_fila = 0

    return {
        "uid": "glucy-panel",
        "title": "Glucy — panel de seguimiento",
        "description": (
            "Los ocho paneles del Documento 2, §10. Datos seudonimizados: el servidor no sabe "
            "quién es nadie. Se aprovisiona desde el repositorio y no se edita desde la interfaz."
        ),
        "tags": ["glucy", "fase6"],
        # La zona del navegador: los agregados vienen agrupados por día local, y enseñarlos en
        # UTC los correría medio día respecto a lo que el teléfono ya le enseñó a la persona.
        "timezone": "browser",
        "editable": False,
        "schemaVersion": 39,
        "refresh": "5m",
        "time": {"from": "now-30d", "to": "now"},
        "panels": paneles,
    }


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--ver", action="store_true", help="solo comprobar que está al día")
    argumentos = analizador.parse_args()

    texto = json.dumps(armar(), indent=2, ensure_ascii=False) + "\n"
    if argumentos.ver:
        actual = SALIDA.read_text() if SALIDA.exists() else ""
        if actual != texto:
            print(f"{SALIDA} no está al día: correr `python grafana/armar_tablero.py`")
            return 1
        print(f"{SALIDA} al día")
        return 0

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(texto)
    print(f"{SALIDA}: {len(armar()['panels'])} paneles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
