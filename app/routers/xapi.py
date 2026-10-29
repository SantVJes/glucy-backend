"""`POST /xapi`: un lote de eventos de aprendizaje de la `ColaXapi` del teléfono (RF-19, RF-33).

El router hace tres cosas y ninguna más: comprueba el token, valida el sobre y le pasa el lote
al servicio.

La respuesta **no dice nada del Learning Record Store**, y es a propósito. Un renglón sale de la
cola del teléfono cuando este servidor lo acepta, igual que una lectura de glucosa; mandarlo al
LRS es cosa del servidor y pasa después, en su propia ventana. Si la respuesta dependiera de que
el LRS contestara, una caída del LRS dejaría al teléfono reintentando y la regla de que ninguna
función depende de él se habría roto en el primer endpoint.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.sesion import obtener_sesion
from app.schemas.lotes import LoteCrudo, RespuestaLote
from app.seguridad import usuario_del_token
from app.services.xapi.ingesta import ingerir_eventos

router = APIRouter(tags=["lotes"])


@router.post(
    "/xapi",
    response_model=RespuestaLote,
    summary="Sube un lote de eventos de aprendizaje (xAPI)",
    responses={
        400: {"description": "El sobre no es usable: sin `items`, vacío o con más de 500."},
        401: {"description": "Falta el token, no se verifica o está vencido."},
    },
)
def subir_eventos(
    lote: LoteCrudo,
    usuario_uuid: Annotated[UUID, Depends(usuario_del_token)],
    sesion: Annotated[Session, Depends(obtener_sesion)],
) -> RespuestaLote:
    """Responde 200 aunque haya renglones en cuarentena, igual que los tres lotes clínicos.

    El teléfono manda un verbo, una actividad y hasta tres números. El actor, el objeto y el
    resultado de la sentencia los arma el servidor, así que no hay ningún campo de texto libre
    que pueda llegar al LRS (regla 3).
    """
    resultado = ingerir_eventos(sesion, usuario_uuid, lote.items, datetime.now(UTC))
    return RespuestaLote(
        aceptados=resultado.aceptados,
        duplicados=resultado.duplicados,
        cuarentena=resultado.cuarentena,
    )
