"""Acceso a `glucose_readings`. Lo específico de SQLite vive aquí y en ningún otro sitio."""

from typing import Any
from uuid import UUID

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.models.tablas import LecturaGlucosa


def insertar_ignorando_duplicados(sesion: Session, filas: list[dict[str, Any]]) -> list[UUID]:
    """Inserta y devuelve solo los uuid que de verdad entraron.

    La idempotencia es una restricción de la base, no un SELECT previo: dos lotes iguales que
    llegan a la vez pasarían los dos el SELECT y duplicarían (RF-36c). `UNIQUE` sobre `uuid`
    más `ON CONFLICT DO NOTHING`, y la lista de los que entraron sale del `RETURNING`.

    En el paso 4 el import cambia a `sqlalchemy.dialects.postgresql` y no se toca ninguna otra
    capa.
    """
    if not filas:
        return []
    sentencia = (
        insert(LecturaGlucosa)
        .values(filas)
        .on_conflict_do_nothing(index_elements=["uuid"])
        .returning(LecturaGlucosa.uuid)
    )
    return list(sesion.scalars(sentencia))
