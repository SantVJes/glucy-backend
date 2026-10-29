"""`POST /explain`: la explicación en lenguaje natural de una predicción (RF-28).

El router comprueba el token, valida el cuerpo y le pasa la petición al servicio. Ni una
consulta, ni una regla, ni una línea de prompt.

**No lee nada.** Escribe una sola fila, la de la bitácora de la fase 6 (C-13): de dónde salió
la explicación y cuánto tardó, para que el panel pueda decir cuántas veces contestó el modelo de
lenguaje y cuántas salió la plantilla. Ni el prompt ni el texto de la explicación se guardan.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import Ajustes, ajustes
from app.db.sesion import obtener_sesion
from app.schemas.explicacion import ExplicacionEntrada, RespuestaExplicacion
from app.seguridad import usuario_del_token
from app.services.explicacion.servicio import explicar_y_registrar

router = APIRouter(tags=["explicacion"])


def configuracion() -> Ajustes:
    """Los ajustes como dependencia, no como llamada suelta.

    Así una prueba puede apuntar el cliente a un Ollama de mentiras y bajar el tope de tiempo
    sin tocar el entorno del proceso ni vaciar cachés de `lru_cache`.
    """
    return ajustes()


@router.post(
    "/explain",
    response_model=RespuestaExplicacion,
    summary="Explica una predicción en lenguaje natural, o devuelve la plantilla",
    responses={
        400: {
            "description": "El cuerpo no sirve: falta un campo, sobra uno (`nombre`, `nota`, "
            "`usuario_uuid`…) o `shap` trae más de cinco contribuciones."
        },
        401: {"description": "Falta el token, no se verifica o está vencido."},
    },
)
def explicar_prediccion(
    entrada: ExplicacionEntrada,
    usuario_uuid: Annotated[UUID, Depends(usuario_del_token)],
    config: Annotated[Ajustes, Depends(configuracion)],
    sesion: Annotated[Session, Depends(obtener_sesion)],
) -> RespuestaExplicacion:
    """Tarda de 1 a 3 segundos con el modelo de lenguaje, y responde en milisegundos cuando
    sale la plantilla. Por eso la app la pide en segundo plano y nunca bloquea la pantalla.

    **Siempre responde `200` con una explicación.** Si el modelo no contesta en 10 segundos, si
    inventa una cifra, si insinúa un tratamiento o si la persona apagó el asistente, sale la
    plantilla determinista y `origen` lo dice (P-13).

    El token se exige para que el endpoint no quede abierto, pero el `usuario_uuid` **no entra
    al prompt**: el modelo de lenguaje nunca sabe de quién son los datos.
    """
    return explicar_y_registrar(
        sesion,
        entrada,
        config.ollama_url or None,
        config.ollama_modelo,
        config.explicacion_timeout_s,
        usuario_uuid,
        datetime.now(UTC),
    )
