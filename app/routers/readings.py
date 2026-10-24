"""`POST /readings`: un lote de lecturas de glucosa (RF-21).

El router hace tres cosas y ninguna más: comprueba el token, valida el sobre y le pasa el lote
al servicio. Ni una consulta, ni una regla.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.sesion import obtener_sesion
from app.schemas.lotes import LoteCrudo, RespuestaLote
from app.seguridad import usuario_del_token
from app.services.ingesta import LOTE_LECTURAS, ingerir

router = APIRouter(tags=["lotes"])


@router.post(
    "/readings",
    response_model=RespuestaLote,
    summary="Sube un lote de lecturas de glucosa",
    responses={
        400: {"description": "El sobre no es usable: sin `items`, vacío o con más de 500."},
        401: {"description": "Falta el token, no se verifica o está vencido."},
    },
)
def subir_lecturas(
    lote: LoteCrudo,
    usuario_uuid: Annotated[UUID, Depends(usuario_del_token)],
    sesion: Annotated[Session, Depends(obtener_sesion)],
) -> RespuestaLote:
    """Responde 200 aunque haya renglones en cuarentena: el lote se procesó, y lo que pasó con
    cada renglón está en las tres listas. Un uuid repetido no es 409, es un duplicado.
    """
    resultado = ingerir(sesion, usuario_uuid, lote.items, datetime.now(UTC), LOTE_LECTURAS)
    return RespuestaLote(
        aceptados=resultado.aceptados,
        duplicados=resultado.duplicados,
        cuarentena=resultado.cuarentena,
    )
