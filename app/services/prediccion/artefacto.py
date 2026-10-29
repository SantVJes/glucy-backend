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

    El manifiesto es lo que `glucy-ml` deja junto al modelo:

    ```json
    {"version": "m1-v0.1.0", "algoritmo": "xgboost", "horizonte_min": 30,
     "juego": "denso", "caracteristicas": ["mg_dl", "rezago_5", …],
     "archivo": "m1-v0.1.0.json", "metricas": {"rmse": 18.2, "clarke_ab": 96.1}}
    ```
    """
    datos = _leer_manifiesto(manifiesto)
    faltan = {"version", "horizonte_min", "juego", "caracteristicas", "archivo"} - set(datos)
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

    archivo = manifiesto.parent / datos["archivo"]
    booster = xgboost.Booster()
    try:
        booster.load_model(str(archivo))
    except (xgboost.core.XGBoostError, OSError) as error:
        raise ArtefactoInvalido(f"{archivo.name}: no se pudo cargar ({error})") from error

    return Artefacto(
        version=str(datos["version"]),
        horizonte_min=int(datos["horizonte_min"]),
        juego=juego,
        caracteristicas=declaradas,
        booster=booster,
        metricas={k: float(v) for k, v in (datos.get("metricas") or {}).items()},
    )


def cargar(ruta: str | None) -> dict[tuple[str, int], Artefacto]:
    """Todos los artefactos de una carpeta, por `(juego, horizonte_min)`.

    Sin carpeta, o con una carpeta vacía, devuelve `{}` y **la API arranca igual**: `/predict`
    contesta `503` con el motivo. Un servidor que no arranca porque falta el modelo dejaría sin
    `/readings` a una app que no necesita el modelo para nada (regla 1).

    Un manifiesto inválido se registra y se salta: que uno esté mal no tira los demás.
    """
    if not ruta:
        return {}
    carpeta = Path(ruta)
    if not carpeta.is_dir():
        registro.warning("la ruta del artefacto no es una carpeta: %s", carpeta)
        return {}

    cargados: dict[tuple[str, int], Artefacto] = {}
    for manifiesto in sorted(carpeta.glob("*.manifiesto.json")):
        try:
            artefacto = cargar_uno(manifiesto)
        except ArtefactoInvalido as error:
            registro.error("artefacto descartado: %s", error)
            continue
        cargados[(artefacto.juego, artefacto.horizonte_min)] = artefacto
        registro.info(
            "artefacto cargado: %s (%s, %s min)",
            artefacto.version,
            artefacto.juego,
            artefacto.horizonte_min,
        )
    return cargados
