"""El sobre de los lotes y la respuesta en tres listas, comunes a los tres POST de lote."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

MAX_RENGLONES_POR_LOTE = 500


class LoteCrudo(BaseModel):
    """El sobre, y solo el sobre. Los renglones llegan como dict y se validan uno por uno
    dentro del servicio, para que un renglón malo no tire el lote entero (decisión 2.5).
    """

    items: list[dict[str, Any]] = Field(min_length=1, max_length=MAX_RENGLONES_POR_LOTE)


class RenglonEnCuarentena(BaseModel):
    """Lleva el motivo y no solo el uuid: RF-22 obliga a conservarlo, y sin él el teléfono
    tendría que preguntar qué pasó con un dato que él mismo mandó.
    """

    uuid: UUID | None  # None cuando el renglón ni siquiera traía un uuid legible
    motivo: str


class RespuestaLote(BaseModel):
    """Cada renglón del lote sale en exactamente una de las tres listas."""

    aceptados: list[UUID]
    duplicados: list[UUID]
    cuarentena: list[RenglonEnCuarentena]
