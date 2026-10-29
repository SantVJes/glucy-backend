"""`GET /predict`: la predicción a 30 y 60 minutos, y con qué modo respondió (RF-21).

El router comprueba el token, le pide la predicción al servicio y traduce el resultado a su
código. Ni una consulta, ni una regla.

El artefacto se carga **al arrancar** y vive en el estado de la aplicación: por eso la respuesta
entra en los 200 ms. Si no hay artefacto, la API arranca igual y este endpoint contesta `503`,
porque una app que solo quiere subir sus lecturas no necesita el modelo para nada (regla 1).
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.sesion import obtener_sesion
from app.repositories import predicciones as repo_predicciones
from app.schemas.prediccion import RespuestaPredecir
from app.seguridad import usuario_del_token
from app.services.prediccion.artefacto import Artefacto
from app.services.prediccion.servicio import SinModelo, predecir

router = APIRouter(tags=["prediccion"])


def artefactos_cargados(peticion: Request) -> dict[tuple[str, int], Artefacto]:
    """Los artefactos que se cargaron al arrancar. Como dependencia, para poder sustituirlos."""
    return peticion.app.state.artefactos


@router.get(
    "/predict",
    response_model=RespuestaPredecir,
    summary="Predicción a 30 y 60 minutos, con el modo con el que respondió",
    responses={
        401: {"description": "Falta el token, no se verifica o está vencido."},
        503: {
            "description": "No hay artefacto del modelo cargado. No se devuelve ningún número "
            "de respaldo: una línea base no es una predicción validada."
        },
    },
)
def predecir_ahora(
    usuario_uuid: Annotated[UUID, Depends(usuario_del_token)],
    sesion: Annotated[Session, Depends(obtener_sesion)],
    artefactos: Annotated[dict[tuple[str, int], Artefacto], Depends(artefactos_cargados)],
) -> RespuestaPredecir:
    """En modo sin sensor responde `200` **sin predicciones** y con el aviso de que no puede
    anticipar una glucosa baja (RF-10b, P-04). No es un error: es el modo en el que la app tiene
    derecho a estar cuando la última lectura del sensor ya pasó los 15 minutos (P-03).

    Cada predicción que sale queda registrada en `predictions` con la versión del modelo que la
    calculó (RF-25), para poder comparar después contra lo que de verdad pasó.
    """
    ahora = datetime.now(UTC)
    try:
        respuesta = predecir(sesion, usuario_uuid, ahora, artefactos)
    except SinModelo as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error

    repo_predicciones.registrar(
        sesion,
        usuario_uuid,
        ahora,
        [
            {
                "horizonte_min": p.horizonte_min,
                "valor_predicho": p.valor_predicho,
                "modo": respuesta.modo,
                "modelo_version": p.modelo_version,
            }
            for p in respuesta.predicciones
        ],
    )
    return respuesta
