"""La orden del pipeline: `python -m app.pipeline` (decisión 2.11 del paso 4).

    python -m app.pipeline --usuario <uuid> --desde 2026-10-01 --hasta 2026-10-26
    python -m app.pipeline --todos --ultimos-dias 7

No se corre dentro de `POST /readings`: el teléfono sube un lote en una ventana de wifi y no
tiene por qué esperar a que se recalculen semanas de serie. Programarla es de la fase 6.

La base sale de `GLUCY_DATABASE_URL`, igual que en las migraciones, y no de los ajustes de la
API: el pipeline no necesita el secreto del token.

Una fecha sin hora (`2026-10-01`) es la medianoche **UTC** de ese día, y `--hasta` no entra en
el periodo. Para otra frontera, pásala en ISO 8601 con offset.
"""

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.sesion import crear_motor
from app.repositories import usuarios as repo_usuarios
from app.services.pipeline.corrida import correr


def main(argumentos: Sequence[str] | None = None) -> int:
    analizador = _analizador()
    opciones = analizador.parse_args(argumentos)
    if (opciones.desde is None) == (opciones.ultimos_dias is None):
        analizador.error("hace falta exactamente uno de --desde y --ultimos-dias")
    hasta = opciones.hasta or datetime.now(UTC)
    desde = opciones.desde or hasta - timedelta(days=opciones.ultimos_dias)
    if desde >= hasta:
        print("error: --desde tiene que ser anterior a --hasta", file=sys.stderr)
        return 2

    motor = crear_motor(os.environ.get("GLUCY_DATABASE_URL") or "sqlite:///./glucy.db")
    try:
        with Session(motor) as sesion:
            usuarios = [opciones.usuario] if opciones.usuario else repo_usuarios.todos(sesion)
            for usuario in usuarios:
                r = correr(sesion, usuario, desde, hasta)
                print(
                    f"{usuario}: {r.lecturas} lecturas → {r.serie} filas en serie_limpia "
                    f"({r.interpoladas} interpoladas, {r.atipicas} atípicas); "
                    f"{r.horarios} agregados horarios, {r.diarios} diarios"
                )
    finally:
        motor.dispose()
    return 0


def _analizador() -> argparse.ArgumentParser:
    analizador = argparse.ArgumentParser(
        prog="python -m app.pipeline",
        description="Limpia la serie del sensor y recalcula los agregados de un periodo.",
    )
    quien = analizador.add_mutually_exclusive_group(required=True)
    quien.add_argument("--usuario", type=UUID, help="el usuario_uuid a procesar")
    quien.add_argument("--todos", action="store_true", help="todos los usuarios")
    analizador.add_argument("--desde", type=_fecha, help="inicio del periodo (entra)")
    analizador.add_argument(
        "--hasta", type=_fecha, help="fin del periodo (no entra); por omisión, ahora"
    )
    analizador.add_argument(
        "--ultimos-dias", type=int, help="en lugar de --desde: los últimos N días"
    )
    return analizador


def _fecha(texto: str) -> datetime:
    """`AAAA-MM-DD` es la medianoche UTC de ese día; si trae hora, tiene que traer offset."""
    try:
        valor = datetime.fromisoformat(texto)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"fecha ilegible: {texto!r}") from error
    if len(texto) == 10:
        return valor.replace(tzinfo=UTC)
    if valor.tzinfo is None:
        raise argparse.ArgumentTypeError(f"una fecha con hora tiene que traer offset: {texto!r}")
    return valor


if __name__ == "__main__":
    sys.exit(main())
