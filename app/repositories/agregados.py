"""Acceso a `agregados_horarios` y `agregados_diarios`. Siempre filtrado por dueño.

Aquí no se calcula nada: las cifras llegan ya hechas por `indicadores()` de la referencia. Ni
*continuous aggregates* ni SQL clínico (decisión 2.6 del paso 4).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models.tablas import AgregadoDiario, AgregadoHorario
from app.repositories.upsert import insertar

Agregado = type[AgregadoHorario] | type[AgregadoDiario]
_COLUMNAS_DE_VALOR = ("promedio", "minimo", "maximo", "desviacion", "tir", "tbr", "tar", "gmi")


def reemplazar(
    sesion: Session,
    usuario_uuid: UUID,
    modelo: Agregado,
    desde: datetime,
    hasta: datetime,
    filas: list[dict[str, Any]],
) -> int:
    """Deja los agregados del usuario con `periodo` en `[desde, hasta)` exactamente así.

    Borrar primero quita un periodo que ya no tiene datos; el `ON CONFLICT DO UPDATE` sobre
    `(usuario_uuid, periodo)` hace que correrlo dos veces no duplique (decisión 2.11).
    """
    sesion.execute(
        delete(modelo).where(
            modelo.usuario_uuid == usuario_uuid,
            modelo.periodo >= desde,
            modelo.periodo < hasta,
        )
    )
    if not filas:
        return 0
    sentencia = insertar(sesion, modelo).values(
        [{**fila, "usuario_uuid": usuario_uuid} for fila in filas]
    )
    sesion.execute(
        sentencia.on_conflict_do_update(
            index_elements=["usuario_uuid", "periodo"],
            set_={columna: sentencia.excluded[columna] for columna in _COLUMNAS_DE_VALOR},
        )
    )
    return len(filas)
