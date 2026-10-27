"""Acceso a `usuarios`."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tablas import Usuario
from app.repositories.upsert import insertar


def asegurar_que_existe(sesion: Session, usuario_uuid: UUID, ts_alta: datetime) -> None:
    """Crea la fila con `uuid` y `ts_alta` si no existe; si existe, no la toca (decisión 2.7).

    También con `ON CONFLICT DO NOTHING`: dos primeros lotes del mismo usuario que llegan a la
    vez no deben chocar.
    """
    sesion.execute(
        insertar(sesion, Usuario)
        .values(uuid=usuario_uuid, ts_alta=ts_alta)
        .on_conflict_do_nothing(index_elements=["uuid"])
    )


def todos(sesion: Session) -> list[UUID]:
    """Los `uuid` de todos los usuarios, para `python -m app.pipeline --todos`.

    Solo la usa el pipeline. Ningún endpoint lista usuarios: el servidor no sabe quién eres.
    """
    return list(sesion.scalars(select(Usuario.uuid).order_by(Usuario.uuid)))
