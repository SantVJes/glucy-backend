"""Acceso a `serie_limpia`, la tabla trece (C-9). Siempre filtrado por dueño."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.tablas import SerieLimpia
from app.repositories.upsert import insertar

_COLUMNAS_DE_VALOR = ("zona_horaria", "mg_dl", "origen", "atipica", "interpolada")


def del_periodo(
    sesion: Session, usuario_uuid: UUID, desde: datetime, hasta: datetime
) -> list[SerieLimpia]:
    """Las filas del usuario en `[desde, hasta)`, ordenadas por tiempo."""
    return list(
        sesion.scalars(
            select(SerieLimpia)
            .where(
                SerieLimpia.usuario_uuid == usuario_uuid,
                SerieLimpia.ts_utc >= desde,
                SerieLimpia.ts_utc < hasta,
            )
            .order_by(SerieLimpia.ts_utc)
        )
    )


def reemplazar(
    sesion: Session,
    usuario_uuid: UUID,
    desde: datetime,
    hasta: datetime,
    filas: list[dict[str, Any]],
) -> int:
    """Deja en `[desde, hasta)` exactamente estas filas. Devuelve cuántas quedaron.

    Primero borra lo que había en el periodo —si llegó una lectura nueva, una fila interpolada
    de la corrida anterior puede ya no corresponder— y después inserta con
    `ON CONFLICT (usuario_uuid, ts_utc) DO UPDATE`. Correrlo dos veces deja la misma tabla
    (decisión 2.11).
    """
    sesion.execute(
        delete(SerieLimpia).where(
            SerieLimpia.usuario_uuid == usuario_uuid,
            SerieLimpia.ts_utc >= desde,
            SerieLimpia.ts_utc < hasta,
        )
    )
    if not filas:
        return 0
    sentencia = insertar(sesion, SerieLimpia).values(
        [{**fila, "usuario_uuid": usuario_uuid} for fila in filas]
    )
    sesion.execute(
        sentencia.on_conflict_do_update(
            index_elements=["usuario_uuid", "ts_utc"],
            set_={columna: sentencia.excluded[columna] for columna in _COLUMNAS_DE_VALOR},
        )
    )
    return len(filas)
