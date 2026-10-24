"""`POST /perfil`: los seis parámetros clínicos del perfil (C-7). Es el octavo endpoint.

Los siete de RF-21 no tenían por dónde subir los umbrales ni la duración de acción de la
insulina, que el pipeline necesita para el IOB y para derivar la alerta. Va aparte, y no
escondido en `/readings`, para que se vea que son ocho y por qué.

El router comprueba el token, le pasa el cuerpo al servicio y traduce el resultado a su
código. Ni una consulta, ni una regla.
"""

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.sesion import obtener_sesion
from app.schemas.perfil import PerfilEntrada, PerfilGuardado
from app.seguridad import usuario_del_token
from app.services.perfil import PerfilRechazado, guardar_perfil

router = APIRouter(tags=["perfil"])


def _esquema_en_linea(modelo: type[BaseModel]) -> dict[str, Any]:
    """El esquema JSON del modelo con sus `$defs` resueltos en su lugar.

    El cuerpo llega como `dict` para que un perfil inválido llegue al servicio y deje su
    rastro en `cuarentena` (un 422 de FastAPI no dejaría ninguno). Sin esto, `/docs` lo
    mostraría como un objeto cualquiera, y la OpenAPI es entregable del punto 14.
    """
    esquema = modelo.model_json_schema()
    definiciones = esquema.pop("$defs", {})

    def resolver(nodo: Any) -> Any:
        if isinstance(nodo, dict):
            if "$ref" in nodo:
                return resolver(definiciones[nodo["$ref"].rsplit("/", 1)[-1]])
            return {clave: resolver(valor) for clave, valor in nodo.items()}
        if isinstance(nodo, list):
            return [resolver(valor) for valor in nodo]
        return nodo

    return resolver(esquema)


@router.post(
    "/perfil",
    response_model=PerfilGuardado,
    summary="Guarda o actualiza los seis parámetros clínicos del perfil",
    responses={
        400: {
            "description": "El perfil no se guardó: falta un campo, sobra uno (`nombre`, "
            "`apellidos`, `peso_kg`, `nota`…) o un valor está fuera de rango. El motivo "
            "viene en `detail` y queda una fila en `cuarentena`."
        },
        401: {"description": "Falta el token, no se verifica o está vencido."},
    },
    openapi_extra={
        "requestBody": {
            "content": {"application/json": {"schema": _esquema_en_linea(PerfilEntrada)}}
        }
    },
)
def subir_perfil(
    cuerpo: Annotated[dict[str, Any], Body()],
    usuario_uuid: Annotated[UUID, Depends(usuario_del_token)],
    sesion: Annotated[Session, Depends(obtener_sesion)],
) -> PerfilGuardado:
    """Un *upsert*: el segundo envío actualiza en lugar de duplicar, porque el teléfono es la
    autoridad sobre su perfil. Responde con los seis valores tal como quedaron guardados.

    Un perfil que no pasa es `400` y no `200`: en un lote hay otros renglones que salvar, aquí
    no hay ninguno, y el teléfono tiene que saber que no reintente igual.
    """
    try:
        return guardar_perfil(sesion, usuario_uuid, cuerpo, datetime.now(UTC))
    except PerfilRechazado as rechazo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=rechazo.motivo
        ) from rechazo
