"""Verificación del token. Este paso solo lo comprueba; emitirlo y rotarlo llega después.

El `sub` del token es el `usuario_uuid` (decisión 2.7): el servidor no sabe quién eres, solo
conoce un UUID.
"""

from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import ajustes

ALGORITMO = "HS256"

# auto_error=False para que la falta de token sea un 401 y no el 403 que FastAPI da por
# omisión: para la app, 401 es «renueva y reintenta», y no hay otro código que entienda.
_esquema_bearer = HTTPBearer(auto_error=False)


def _no_autorizado(detalle: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detalle,
        headers={"WWW-Authenticate": "Bearer"},
    )


def usuario_del_token(
    credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(_esquema_bearer)],
) -> UUID:
    """Devuelve el `usuario_uuid` del `sub`, o levanta 401.

    Un 401 significa para la app «renueva el token y reintenta UNA vez» (RF-21), así que no se
    usa para nada más: un dato que no gusta es cuarentena, no 401.
    """
    if credenciales is None:
        raise _no_autorizado("falta el token")
    try:
        carga = jwt.decode(
            credenciales.credentials,
            ajustes().jwt_secret,
            algorithms=[ALGORITMO],
            options={"require": ["sub", "exp"]},
        )
        return UUID(carga["sub"])
    except jwt.ExpiredSignatureError as error:
        raise _no_autorizado("token vencido") from error
    except (jwt.InvalidTokenError, ValueError, TypeError) as error:
        raise _no_autorizado("token inválido") from error
