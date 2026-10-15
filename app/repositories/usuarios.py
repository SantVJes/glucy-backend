"""Acceso a `usuarios`."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.models.tablas import Usuario


def asegurar_que_existe(sesion: Session, usuario_uuid: UUID, ts_alta: datetime) -> None:
    """Crea la fila con `uuid` y `ts_alta` si no existe; si existe, no la toca (decisión 2.7).

    También con `ON CONFLICT DO NOTHING`: dos primeros lotes del mismo usuario que llegan a la
    vez no deben chocar.
    """
    sesion.execute(
        insert(Usuario)
        .values(uuid=usuario_uuid, ts_alta=ts_alta)
        .on_conflict_do_nothing(index_elements=["uuid"])
    )
