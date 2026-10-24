"""Acceso al perfil clínico en `usuarios`. Lo específico de SQLite vive aquí."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.models.tablas import Usuario


def guardar(
    sesion: Session, usuario_uuid: UUID, campos: dict[str, Any], ahora: datetime
) -> dict[str, Any]:
    """Upsert del perfil: `ON CONFLICT (uuid) DO UPDATE` sobre los seis campos.

    El teléfono es la autoridad sobre su perfil, así que el segundo envío actualiza. No se
    toca `ts_alta`: se puso la primera vez —aquí o en el primer lote— y no vuelve a cambiar.

    Devuelve los campos tal como quedaron en la base, leídos del `RETURNING` y no copiados de
    la entrada.
    """
    sentencia = (
        insert(Usuario)
        .values(uuid=usuario_uuid, ts_alta=ahora, **campos)
        .on_conflict_do_update(index_elements=["uuid"], set_=campos)
        .returning(*(getattr(Usuario, campo) for campo in campos))
    )
    return dict(sesion.execute(sentencia).mappings().one())
