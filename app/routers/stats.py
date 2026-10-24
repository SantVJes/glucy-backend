"""`GET /stats`: los indicadores del periodo (RF-21, RF-16).

El router comprueba el token, valida los parámetros y le pasa la consulta al servicio. Ni una
consulta, ni una regla. El usuario sale del token: ningún parámetro lo cambia (decisión 2.1).
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.sesion import obtener_sesion
from app.schemas.consultas import Periodo, RespuestaStats
from app.seguridad import usuario_del_token
from app.services import estadisticas

router = APIRouter(tags=["consultas"])


@router.get(
    "/stats",
    response_model=RespuestaStats,
    summary="TIR, promedio, GMI y coeficiente de variación del periodo",
    responses={
        400: {
            "description": "Falta `desde` o `hasta`, una fecha viene sin offset, `desde` no es "
            "anterior a `hasta`, el periodo pasa de 90 días o llegó un parámetro desconocido."
        },
        401: {"description": "Falta el token, no se verifica o está vencido."},
    },
)
def consultar_stats(
    periodo: Annotated[Periodo, Query()],
    usuario_uuid: Annotated[UUID, Depends(usuario_del_token)],
    sesion: Annotated[Session, Depends(obtener_sesion)],
) -> RespuestaStats:
    """Con menos de tres días de lecturas `indicadores` es `null`; con menos de catorce, `gmi`
    es `null`. Nunca un cero en lugar de «faltan datos», y nunca un 404: un usuario sin datos
    recibe `dias_con_lecturas: 0` (decisión 2.9).
    """
    return estadisticas.calcular(sesion, usuario_uuid, periodo)
