"""`GET /history`: el histórico para el panel y la exportación (RF-21).

El router comprueba el token, valida los parámetros y le pasa la consulta al servicio. Ni una
consulta, ni una regla. El usuario sale del token: ningún parámetro lo cambia (decisión 2.1).
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.sesion import obtener_sesion
from app.schemas.consultas import ConsultaHistorial, RespuestaHistorial
from app.seguridad import usuario_del_token
from app.services import historial

router = APIRouter(tags=["consultas"])


@router.get(
    "/history",
    response_model=RespuestaHistorial,
    summary="Lecturas, comidas y dosis del periodo, paginadas por cursor",
    responses={
        400: {
            "description": "Falta `desde` o `hasta`, una fecha viene sin offset, `desde` no es "
            "anterior a `hasta`, el periodo pasa de 90 días, `limite` pasa de 1000, `que` o "
            "`cursor` no se entienden, o llegó un parámetro desconocido."
        },
        401: {"description": "Falta el token, no se verifica o está vencido."},
    },
)
def consultar_history(
    consulta: Annotated[ConsultaHistorial, Query()],
    usuario_uuid: Annotated[UUID, Depends(usuario_del_token)],
    sesion: Annotated[Session, Depends(obtener_sesion)],
) -> RespuestaHistorial:
    """Para la siguiente página se manda `siguiente` como `cursor`, tal cual, con los mismos
    `desde`, `hasta` y `que`. `siguiente: null` es el fin. Un usuario sin datos recibe las
    tres series vacías, no un 404 (decisión 2.9).
    """
    return historial.consultar(sesion, usuario_uuid, consulta)
