"""Inserción idempotente de los tres lotes. Lo específico de SQLite vive aquí y en ningún
otro sitio."""

from typing import Any
from uuid import UUID

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.models.tablas import Base


def insertar_ignorando_duplicados(
    sesion: Session, modelo: type[Base], filas: list[dict[str, Any]]
) -> list[UUID]:
    """Inserta y devuelve solo los uuid que de verdad entraron.

    El de `lecturas.py` del paso 1, con el modelo como parámetro. La idempotencia es una
    restricción de la base, no un SELECT previo: dos lotes iguales que llegan a la vez
    pasarían los dos el SELECT y duplicarían (RF-36c). `UNIQUE` sobre `uuid` más
    `ON CONFLICT DO NOTHING`, y la lista de los que entraron sale del `RETURNING`.

    Sirve para cualquier tabla cuya llave sea `uuid`: `glucose_readings`, `meals` e
    `insulin_doses`. En el paso 4 el import cambia a `sqlalchemy.dialects.postgresql` y no se
    toca ninguna otra capa.
    """
    if not filas:
        return []
    sentencia = (
        insert(modelo)
        .values(filas)
        .on_conflict_do_nothing(index_elements=["uuid"])
        .returning(modelo.uuid)
    )
    return list(sesion.scalars(sentencia))
