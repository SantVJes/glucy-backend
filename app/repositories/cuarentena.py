"""Acceso a `cuarentena`: lo que no pasó la validación, nunca descartado en silencio (RF-22)."""

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.tablas import Cuarentena


def guardar(
    sesion: Session,
    *,
    ts_recepcion: datetime,
    tabla_destino: str,
    carga_original: dict[str, Any],
    claves_descartadas: list[str],
    motivo_rechazo: str,
) -> None:
    """Guarda un renglón rechazado tal como se le entrega.

    Qué claves se conservan lo decide el servicio, no el repositorio (decisión 2.6).
    """
    sesion.add(
        Cuarentena(
            ts_recepcion=ts_recepcion,
            tabla_destino=tabla_destino,
            carga_original=carga_original,
            claves_descartadas=claves_descartadas,
            motivo_rechazo=motivo_rechazo,
        )
    )
