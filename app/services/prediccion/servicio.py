"""`GET /predict`: el modo, el vector, la predicción y la alerta derivada (RF-21, RF-26).

Tres decisiones que conviene leer antes del código:

1. **La serie se limpia al vuelo**, sobre la última ventana, con la misma `limpiar()` del
   pipeline. Leer `serie_limpia` sería más rápido pero dejaría la predicción colgada de que la
   corrida por lotes hubiera pasado después de la última subida: en un endpoint en vivo eso es
   predecir con datos viejos. Son unas pocas docenas de filas y entra de sobra en el
   presupuesto de 200 ms.
2. **El modo lo decide la referencia**, `modo_actual`, con el umbral de frescura de 15 minutos.
   Si la última lectura del sensor ya no sirve, se degrada a modo sin sensor **y se dice**
   (P-03), en lugar de proyectar con datos viejos.
3. **La alerta se deriva del valor**, comparándolo con el umbral del perfil. El modelo predice
   un número y no una clase, así que la persona ve la curva y entiende por qué se disparó la
   alerta. Y en modo sin sensor **no hay alerta anticipada de hipoglucemia** (RF-10b, P-04).
"""

import math
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.repositories import consultas as repo_consultas
from app.schemas.prediccion import (
    AVISO_SIN_SENSOR,
    ContribucionShap,
    PrediccionHorizonte,
    RespuestaPredecir,
)
from app.services.pipeline.caracteristicas import CARACTERISTICAS_DENSAS, como_fila, vector_denso
from app.services.pipeline.limpieza import limpiar
from app.services.prediccion.artefacto import Artefacto
from referencia.reglas_clinicas import (
    UMBRAL_HIPER_DEFECTO,
    UMBRAL_HIPO_DEFECTO,
    Modo,
    Origen,
    modo_actual,
    puede_alertar_hipoglucemia,
)

# La ventana que se lee para predecir. El rezago más largo del juego denso es de 60 min y la
# media móvil también, así que con tres horas sobra incluso con huecos; y son ~36 filas.
VENTANA_MIN = 180
# Para el COB y el IOB hace falta mirar más atrás: una comida de absorción lenta dura 300 min y
# la insulina hasta 8 h.
VENTANA_CONTEXTO_MIN = 8 * 60

HORIZONTES = (30, 60)


class SinModelo(Exception):
    """No hay artefacto para el horizonte pedido, así que no hay nada que responder.

    No se devuelve un número de respaldo a propósito. Una línea base de persistencia —«dentro
    de 30 minutos será igual que ahora»— es una herramienta de evaluación, y presentarla como
    una predicción sería enseñar una cifra que nadie validó.
    """


def predecir(
    sesion: Session,
    usuario_uuid: UUID,
    ahora: datetime,
    artefactos: dict[tuple[str, int], Artefacto],
) -> RespuestaPredecir:
    """Las predicciones a 30 y 60 minutos, o el modo sin sensor con su aviso."""
    lecturas = repo_consultas.lecturas_del_periodo(
        sesion, usuario_uuid, ahora - timedelta(minutes=VENTANA_MIN), ahora
    )
    contexto_desde = ahora - timedelta(minutes=VENTANA_CONTEXTO_MIN)
    comidas = repo_consultas.comidas_del_periodo(sesion, usuario_uuid, contexto_desde, ahora)
    dosis = repo_consultas.dosis_del_periodo(sesion, usuario_uuid, contexto_desde, ahora)
    perfil = repo_consultas.perfil(sesion, usuario_uuid)

    umbral_hipo = getattr(perfil, "umbral_hipo", None) or UMBRAL_HIPO_DEFECTO
    umbral_hiper = getattr(perfil, "umbral_hiper", None) or UMBRAL_HIPER_DEFECTO

    serie = limpiar(lecturas) if lecturas else []
    del_sensor = [p for p in serie if p.origen is Origen.SENSOR and not p.atipica]
    ts_ultima_sensor = del_sensor[-1].ts_utc if del_sensor else None
    modo = modo_actual(bool(del_sensor), ts_ultima_sensor, ahora)

    ultima = serie[-1] if serie else None
    base = {
        "ts_utc": ahora,
        "modo": modo.value,
        # Redondeado: es el valor ya suavizado por `limpiar()`, y el suavizado deja una
        # cola de decimales que no significan nada en mg/dL.
        "valor_actual": round(ultima.mg_dl, 1) if ultima else None,
        "antiguedad_min": (
            round((ahora - ultima.ts_utc).total_seconds() / 60, 1) if ultima else None
        ),
        "puede_alertar_hipoglucemia": puede_alertar_hipoglucemia(modo),
        "umbral_hipo": umbral_hipo,
        "umbral_hiper": umbral_hiper,
    }

    if modo is not Modo.SENSOR:
        # RF-10b: se declara, no se rellena con algo que parezca una predicción.
        return RespuestaPredecir(**base, predicciones=[], aviso=AVISO_SIN_SENSOR)

    vector = vector_denso(ahora, serie, comidas, dosis, perfil)
    fila = como_fila(vector, CARACTERISTICAS_DENSAS)

    predicciones = []
    for horizonte in HORIZONTES:
        artefacto = artefactos.get(("denso", horizonte))
        if artefacto is None:
            raise SinModelo(f"no hay modelo cargado para {horizonte} minutos")
        valor, contribuciones = artefacto.predecir(fila)
        predicciones.append(
            PrediccionHorizonte(
                horizonte_min=horizonte,
                valor_predicho=round(valor, 1),
                modelo_version=artefacto.version,
                alerta=alerta_de(valor, umbral_hipo, umbral_hiper),
                shap=[
                    ContribucionShap(variable=nombre, mg_dl=round(aporte, 1))
                    for nombre, aporte in contribuciones
                ],
            )
        )
    return RespuestaPredecir(**base, predicciones=predicciones)


def alerta_de(valor: float, umbral_hipo: float, umbral_hiper: float) -> str | None:
    """La alerta sale del valor y del umbral del perfil, no de una clase que prediga el modelo."""
    if math.isnan(valor):
        return None
    if valor < umbral_hipo:
        return "hipoglucemia"
    if valor > umbral_hiper:
        return "hiperglucemia"
    return None
