"""El artefacto del modelo: se carga una vez, se queda en memoria y se comprueba al cargarlo.

`GET /predict` responde en menos de 200 ms **porque el artefacto ya está en memoria** (RF-21).
Cargarlo por petición costaría más que predecir.

La comprobación que hace este módulo es la más valiosa del paso. El modelo recibe un vector de
números en un orden; si `glucy-ml` entrenó con las columnas en otro orden o con otros nombres,
la predicción sale **plausible y equivocada**, y nada falla. Así que el manifiesto declara la
lista de características y aquí se compara contra la de `caracteristicas.py`, que es la
autoridad: si no coinciden, el artefacto **no se carga** y `/predict` contesta que no hay modelo
en lugar de inventar un número.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import xgboost

from app.services.pipeline.caracteristicas import (
    CARACTERISTICAS_DENSAS,
    CARACTERISTICAS_DISPERSAS,
)

registro = logging.getLogger(__name__)

JUEGOS: dict[str, tuple[str, ...]] = {
    "denso": CARACTERISTICAS_DENSAS,
    "disperso": CARACTERISTICAS_DISPERSAS,
}

# Cuántas contribuciones viajan en la respuesta y de ahí a `/explain`: las cinco más grandes.
CONTRIBUCIONES = 5

# Con qué datos se entrenó un modelo cuyas métricas **sí** pueden ir al documento final. Los
# otros valores que usa `glucy-ml` son «simulador» (reportable diciendo que es el simulador) y
# «sintetico» (series de juguete para probar el código, nunca reportable).
ORIGEN_REPORTABLE = "ohiot1dm"


class ArtefactoInvalido(Exception):
    """El manifiesto no describe un modelo que se pueda usar con este pipeline."""


@dataclass(frozen=True)
class Artefacto:
    """Un modelo cargado, con lo que hace falta para alimentarlo y para registrar qué predijo."""

    version: str
    horizonte_min: int
    juego: str
    caracteristicas: tuple[str, ...]
    booster: xgboost.Booster
    metricas: dict[str, float]
    # Con qué datos se entrenó, tal como lo declara el manifiesto. No viaja en la respuesta de
    # `/predict` —eso cambiaría el contrato con la app—, pero sin él un modelo entrenado con
    # series de juguete se sirve igual que uno de verdad y nada lo distingue.
    origen_datos: str = "sin decir"

    def predecir(self, fila: list[float]) -> tuple[float, list[tuple[str, float]]]:
        """El valor predicho y las contribuciones de cada característica, en mg/dL.

        Las contribuciones son **TreeSHAP exacto, del propio XGBoost** (`pred_contribs`), así
        que no hace falta la biblioteca `shap` en el servidor: una dependencia menos en la
        imagen y, sobre todo, los mismos números que reporta `glucy-ml`.

        El último valor que devuelve `pred_contribs` es el término base del modelo, no una
        característica, y por eso se recorta.
        """
        # Los nombres viajan en la matriz: si el artefacto los trae, XGBoost mismo rechaza la
        # fila cuando no coinciden. Es la segunda red, después de la de `cargar_uno`.
        matriz = xgboost.DMatrix(
            np.asarray([fila], dtype=float), feature_names=list(self.caracteristicas)
        )
        valor = float(self.booster.predict(matriz)[0])
        contribuciones = self.booster.predict(matriz, pred_contribs=True)[0]
        pares = list(zip(self.caracteristicas, contribuciones[:-1].tolist(), strict=True))
        pares.sort(key=lambda par: abs(par[1]), reverse=True)
        return valor, pares[:CONTRIBUCIONES]


def _leer_manifiesto(ruta: Path) -> dict[str, Any]:
    try:
        return json.loads(ruta.read_text())
    except (OSError, ValueError) as error:
        raise ArtefactoInvalido(f"{ruta.name}: no se pudo leer ({error})") from error


def cargar_uno(manifiesto: Path) -> Artefacto:
    """Carga el artefacto que describe un manifiesto, comprobando sus características.

    El manifiesto es el que `glucy-ml` deja junto al modelo, `artifacts/m1-v0.1.0.json`:

    ```json
    {"modelo": "m1", "version": "v0.1.0", "algoritmo": "xgboost", "horizonte_min": 30,
     "juego": "denso", "caracteristicas": ["mg_dl", "rezago_5", …],
     "metricas": {"rmse": 18.2, "clarke_ab": 96.1, "clarke_reparto": {…},
                  "sensibilidad_hipo": null}}
    ```

    Tres cosas que el manifiesto **no** trae y que aquí se resuelven, porque la primera versión
    de este cargador las daba por supuestas y con eso no cargaba nada de lo que sale del otro
    repositorio:

    - **No hay campo `archivo`.** El modelo es el hermano del manifiesto con la misma raíz y
      extensión `.ubj`, que es el formato binario de XGBoost. Se acepta `archivo` si viene,
      para un manifiesto escrito a mano.
    - **`modelo` y `version` vienen por separado** (`m1` y `v0.1.0`), y lo que se registra en
      `predictions.modelo_version` es la versión completa (RF-25), así que se componen.
    - **`metricas` trae valores que no son números**: `clarke_reparto` es un diccionario y
      `sensibilidad_hipo` puede ser nulo cuando el conjunto no traía hipoglucemias reales. Se
      toman solo los numéricos en lugar de reventar al convertir.
    """
    datos = _leer_manifiesto(manifiesto)
    faltan = {"version", "horizonte_min", "juego", "caracteristicas"} - set(datos)
    if faltan:
        raise ArtefactoInvalido(f"{manifiesto.name}: falta {sorted(faltan)}")

    juego = datos["juego"]
    if juego not in JUEGOS:
        raise ArtefactoInvalido(f"{manifiesto.name}: juego desconocido «{juego}»")

    declaradas = tuple(datos["caracteristicas"])
    if declaradas != JUEGOS[juego]:
        # El fallo más caro del proyecto si pasara desapercibido, así que se dice completo.
        raise ArtefactoInvalido(
            f"{manifiesto.name}: las características del modelo no son las del juego "
            f"«{juego}». El modelo espera {list(declaradas)} y el pipeline produce "
            f"{list(JUEGOS[juego])}. Reentrenar o corregir el manifiesto: alimentar el "
            "modelo con las columnas cambiadas de lugar da números plausibles y equivocados."
        )

    archivo = _archivo_del_modelo(manifiesto, datos)
    booster = xgboost.Booster()
    try:
        booster.load_model(str(archivo))
    except (xgboost.core.XGBoostError, OSError) as error:
        raise ArtefactoInvalido(f"{archivo.name}: no se pudo cargar ({error})") from error

    return Artefacto(
        version=_version_completa(datos),
        horizonte_min=int(datos["horizonte_min"]),
        juego=juego,
        caracteristicas=declaradas,
        booster=booster,
        metricas=_metricas_numericas(datos.get("metricas")),
        origen_datos=str(datos.get("origen_datos") or "sin decir"),
    )


def _archivo_del_modelo(manifiesto: Path, datos: dict[str, Any]) -> Path:
    """El archivo del modelo que acompaña al manifiesto.

    `archivo` manda si viene. Si no, es el hermano con la misma raíz: `.ubj` primero, que es lo
    que guarda `glucy-ml`, y `.json` después para un modelo guardado en el formato de texto.
    """
    if datos.get("archivo"):
        return manifiesto.parent / str(datos["archivo"])
    raiz = manifiesto.name.removesuffix(".manifiesto.json").removesuffix(".json")
    for extension in (".ubj", ".json"):
        candidato = manifiesto.parent / f"{raiz}{extension}"
        if candidato != manifiesto and candidato.exists():
            return candidato
    raise ArtefactoInvalido(
        f"{manifiesto.name}: no está el archivo del modelo. Se buscó «{raiz}.ubj» y "
        f"«{raiz}.json» junto al manifiesto, y el manifiesto no trae campo «archivo»."
    )


def _version_completa(datos: dict[str, Any]) -> str:
    """`m1-v0.1.0` a partir de `modelo` y `version`, que es como viaja en `predictions`.

    Sin `modelo`, la versión tal cual: así sigue cargando un manifiesto escrito a mano que ya
    traía la versión completa en un solo campo.
    """
    version = str(datos["version"])
    modelo = datos.get("modelo")
    return f"{modelo}-{version}" if modelo and not version.startswith(f"{modelo}-") else version


def _metricas_numericas(metricas: Any) -> dict[str, float]:
    """Solo las métricas que son un número.

    `clarke_reparto` es un diccionario y `sensibilidad_hipo` puede ser nulo —y **tiene que
    poder serlo**: `glucy-ml` lo deja en nulo cuando el conjunto no traía hipoglucemias reales,
    en lugar de reportar un 100 % que sería la cifra más engañosa del reporte—. Convertir todo
    con `float()` reventaba con el manifiesto de verdad. Los booleanos quedan fuera a propósito:
    `True` vale 1.0 en Python y una métrica que vale 1.0 por ser cierta no es una métrica.
    """
    if not isinstance(metricas, dict):
        return {}
    return {
        clave: float(valor)
        for clave, valor in metricas.items()
        if isinstance(valor, int | float) and not isinstance(valor, bool)
    }


# Las claves mínimas que hacen de un `.json` un manifiesto de artefacto. Son las que
# `cargar_uno` exige, y mirarlas antes permite distinguir «este archivo no es un manifiesto» de
# «este manifiesto está mal», que merecen registros muy distintos.
CLAVES_DEL_MANIFIESTO = frozenset({"version", "horizonte_min", "juego", "caracteristicas"})


def _leer_manifiesto_o_nada(ruta: Path) -> dict[str, Any] | None:
    """Los datos del manifiesto, o `None` si ese `.json` no es un manifiesto.

    Un archivo llamado `*.manifiesto.json` **siempre** cuenta como manifiesto, aunque esté
    corrupto: quien lo nombró así dijo lo que era, y saltárselo en silencio escondería el
    problema. Lo que se salta sin ruido es un `.json` que nunca pretendió ser un manifiesto.
    """
    se_declara_manifiesto = ruta.name.endswith(".manifiesto.json")
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {} if se_declara_manifiesto else None
    if not isinstance(datos, dict):
        return {} if se_declara_manifiesto else None
    if CLAVES_DEL_MANIFIESTO <= set(datos) or se_declara_manifiesto:
        return datos
    return None


def cargar(ruta: str | None) -> dict[tuple[str, int], Artefacto]:
    """Todos los artefactos de una carpeta, por `(juego, horizonte_min)`.

    Sin carpeta, o con una carpeta vacía, devuelve `{}` y **la API arranca igual**: `/predict`
    contesta `503` con el motivo. Un servidor que no arranca porque falta el modelo dejaría sin
    `/readings` a una app que no necesita el modelo para nada (regla 1).

    Un manifiesto inválido se registra y se salta: que uno esté mal no tira los demás.

    **Se buscan todos los `.json` y no un nombre fijo.** La primera versión buscaba
    `*.manifiesto.json` y `glucy-ml` escribe `m1-v0.1.0.json`, así que no encontraba nada: la
    carpeta quedaba vacía, `/predict` contestaba 503 para siempre y **ni un solo registro decía
    por qué**, porque un glob que no encuentra nada no es un error. Era la peor forma posible de
    fallar, y por eso ahora un `.json` que no parece manifiesto se salta en `debug` mientras uno
    que sí lo parece y está mal se registra como error.
    """
    if not ruta:
        return {}
    carpeta = Path(ruta)
    if not carpeta.is_dir():
        registro.warning("la ruta del artefacto no es una carpeta: %s", carpeta)
        return {}

    cargados: dict[tuple[str, int], Artefacto] = {}
    for manifiesto in sorted(carpeta.glob("*.json")):
        datos = _leer_manifiesto_o_nada(manifiesto)
        if datos is None:
            # Un modelo de XGBoost guardado en texto, el informe de la conversión a Core ML o
            # cualquier otro JSON que comparte carpeta. No es un fallo.
            registro.debug("no parece un manifiesto, se salta: %s", manifiesto.name)
            continue
        try:
            artefacto = cargar_uno(manifiesto)
        except ArtefactoInvalido as error:
            registro.error("artefacto descartado: %s", error)
            continue
        cargados[(artefacto.juego, artefacto.horizonte_min)] = artefacto
        if artefacto.origen_datos != ORIGEN_REPORTABLE:
            # Que esto salga en el arranque es la diferencia entre «el modelo de juguete se
            # quedó puesto» y descubrirlo al comparar las métricas del reporte con la realidad.
            registro.warning(
                "el artefacto %s se entrenó con datos «%s», no con %s: sus métricas NO van al "
                "documento final",
                artefacto.version,
                artefacto.origen_datos,
                ORIGEN_REPORTABLE,
            )
        registro.info(
            "artefacto cargado: %s (%s, %s min)",
            artefacto.version,
            artefacto.juego,
            artefacto.horizonte_min,
        )
    return cargados
