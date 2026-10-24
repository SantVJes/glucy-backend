"""Tipos de columna propios del backend."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class FechaUtc(TypeDecorator):
    """Guarda en UTC y devuelve con zona.

    SQLite devuelve `datetime` sin `tzinfo`, y comparar eso con `datetime.now(UTC)` levanta
    `TypeError` (reproducido el 24/10/2026, decisión 2.1 del paso 2). `DateTime(timezone=True)`
    no basta porque SQLite lo ignora.

    Solo cambia el procesado del lado de Python: el DDL sigue siendo `DATETIME`, así que no
    hace falta migración.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, valor: datetime | None, dialecto: Any) -> datetime | None:
        if valor is None:
            return None
        if valor.tzinfo is None:
            # Suponer UTC acertaría casi siempre y desplazaría la serie el resto de las
            # veces, sin que nada falle. Mejor que truene aquí, en el código, que en los datos.
            raise ValueError("una fecha sin zona no se guarda: conviértela con astimezone(UTC)")
        return valor.astimezone(UTC)

    def process_result_value(self, valor: datetime | None, dialecto: Any) -> datetime | None:
        if valor is None:
            return None
        return valor.replace(tzinfo=UTC) if valor.tzinfo is None else valor.astimezone(UTC)
