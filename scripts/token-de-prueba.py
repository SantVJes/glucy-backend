"""Firma un token de prueba con el `sub` que se le pase (decisión 2.8).

Uso:  python scripts/token-de-prueba.py <usuario_uuid>

Es para las pruebas a mano con curl. NO es un endpoint, no emite tokens de verdad y no se
despliega. Lee el secreto de GLUCY_JWT_SECRET (o del .env), igual que la aplicación: ningún
secreto vive en el código.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import jwt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import ajustes  # noqa: E402 — después de poner la raíz en la ruta
from app.seguridad import ALGORITMO  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("uso: python scripts/token-de-prueba.py <usuario_uuid>")
    sub = str(UUID(sys.argv[1]))
    ahora = datetime.now(UTC)
    carga = {
        "sub": sub,
        "iat": ahora,
        "exp": ahora + timedelta(minutes=ajustes().jwt_minutos_vigencia),
    }
    print(jwt.encode(carga, ajustes().jwt_secret, algorithm=ALGORITMO))


if __name__ == "__main__":
    main()
