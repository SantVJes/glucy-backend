"""Inserción idempotente de los tres lotes. El `insert` de cada motor sale de `upsert.py`."""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.tablas import Base
from app.repositories.upsert import insertar


def insertar_ignorando_duplicados(
    sesion: Session, modelo: type[Base], filas: list[dict[str, Any]]
) -> list[UUID]:
    """Inserta y devuelve solo los uuid que de verdad entraron.

    El de `lecturas.py` del paso 1, con el modelo como parámetro. La idempotencia es una
    restricción de la base, no un SELECT previo: dos lotes iguales que llegan a la vez
    pasarían los dos el SELECT y duplicarían (RF-36c). `UNIQUE` sobre `uuid` más
    `ON CONFLICT DO NOTHING`, y la lista de los que entraron sale del `RETURNING`.

    Sirve para cualquier tabla cuya llave sea `uuid`: `glucose_readings`, `meals` e
    `insulin_doses`, en SQLite y en PostgreSQL: el dialecto lo elige `upsert.insertar`.
    """
    if not filas:
        return []
    sentencia = (
        insertar(sesion, modelo)
        .values(filas)
        .on_conflict_do_nothing(index_elements=["uuid"])
        .returning(modelo.uuid)
    )
    return list(sesion.scalars(sentencia))
