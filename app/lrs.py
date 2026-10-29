"""La orden que vacía la cola hacia el Learning Record Store: `python -m app.lrs`.

    python -m app.lrs                 # manda lo que esté pendiente
    python -m app.lrs --cuantas       # solo dice cuántas esperan, sin mandar nada

No se corre dentro de `POST /xapi`: el teléfono sube su lote en una ventana de wifi y no tiene
por qué esperar a que un servidor de terceros conteste. Programarla con `cron` es lo mismo que
se hace con el pipeline.

La base sale de `GLUCY_DATABASE_URL` y las credenciales del LRS de `GLUCY_LRS_*`, igual que en
la API. **Esta orden no necesita el secreto del token**, así que no lee los ajustes de la API.

Si el LRS no está, la orden termina bien, no toca ninguna fila y dice por qué no mandó nada: una
caída del LRS no es una falla del sistema, y por eso no devuelve un código de error que un
`cron` reportaría todas las noches.
"""

import argparse
import os
import sys
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.db.sesion import crear_motor
from app.repositories import xapi as repo
from app.services.xapi.envio import enviar_pendientes
from app.services.xapi.lrs import ConfiguracionLrs
from app.services.xapi.reloj import ahora_utc


def main(argumentos: Sequence[str] | None = None) -> int:
    opciones = _analizador().parse_args(argumentos)
    motor = crear_motor(os.environ.get("GLUCY_DATABASE_URL") or "sqlite:///./glucy.db")
    try:
        with Session(motor) as sesion:
            if opciones.cuantas:
                print(f"{repo.cuantas_pendientes(sesion)} sentencias esperan en la cola")
                return 0
            resumen = enviar_pendientes(sesion, ConfiguracionLrs.del_entorno(), ahora_utc())
            print(
                f"{resumen.enviadas} enviadas, {resumen.rechazadas} rechazadas, "
                f"{resumen.pendientes} siguen en la cola"
            )
            if resumen.detenida_por is not None:
                print(f"la ventana se detuvo: {resumen.detenida_por}", file=sys.stderr)
    finally:
        motor.dispose()
    return 0


def _analizador() -> argparse.ArgumentParser:
    analizador = argparse.ArgumentParser(
        prog="python -m app.lrs",
        description="Manda al Learning Record Store las sentencias xAPI que esperan en la cola.",
    )
    analizador.add_argument(
        "--cuantas", action="store_true", help="solo contar las pendientes, sin mandar nada"
    )
    return analizador


if __name__ == "__main__":
    sys.exit(main())
