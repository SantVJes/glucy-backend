"""La bitácora de las explicaciones. Todo su SQL vive aquí (C-13)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.tablas import Explicacion


def registrar(
    sesion: Session,
    *,
    ts_utc: datetime,
    usuario_uuid: UUID,
    origen: str,
    motivo: str | None,
    modelo: str | None,
    duracion_ms: int,
    horizonte_min: int | None,
    modo: str | None,
) -> None:
    """Una fila por explicación servida. Todos los argumentos son por nombre a propósito:
    nueve posicionales en el orden equivocado escribirían el motivo en la columna del modelo
    sin que nada falle."""
    sesion.add(
        Explicacion(
            ts_utc=ts_utc,
            usuario_uuid=usuario_uuid,
            origen=origen,
            motivo=motivo,
            modelo=modelo,
            duracion_ms=duracion_ms,
            horizonte_min=horizonte_min,
            modo=modo,
        )
    )
