"""La cola del Learning Record Store: qué falta mandar y cómo se marca lo que salió.

Todo el SQL de `xapi_events` vive aquí y en ningún otro lado, igual que el resto de los
repositorios. El servicio de envío decide **qué** hacer; esta capa sabe **cómo** se consulta.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.tablas import EventoXapi


def pendientes(sesion: Session, limite: int) -> list[EventoXapi]:
    """Lo que falta mandar, lo más antiguo primero.

    «Pendiente» es exactamente «sin enviar y sin rechazar». El orden importa: un LRS que recibe
    las sentencias desordenadas calcula mal cualquier indicador que dependa de una secuencia,
    como responder a un aviso después de haberlo recibido.
    """
    sentencia = (
        select(EventoXapi)
        .where(EventoXapi.enviado_ts.is_(None), EventoXapi.motivo_rechazo.is_(None))
        .order_by(EventoXapi.ts_utc, EventoXapi.uuid)
        .limit(limite)
    )
    return list(sesion.scalars(sentencia))


def cuantas_pendientes(sesion: Session) -> int:
    """Para el panel y para que la orden diga cuánto queda sin recorrer la cola otra vez."""
    sentencia = select(EventoXapi.uuid).where(
        EventoXapi.enviado_ts.is_(None), EventoXapi.motivo_rechazo.is_(None)
    )
    return len(list(sesion.scalars(sentencia)))


def marcar_enviadas(sesion: Session, uuids: list[UUID], ahora: datetime) -> None:
    """Las que el LRS aceptó. Sale de la cola y queda cuándo salió."""
    if not uuids:
        return
    sesion.execute(
        update(EventoXapi)
        .where(EventoXapi.uuid.in_(uuids))
        .values(enviado_ts=ahora, intentos=EventoXapi.intentos + 1)
    )


def marcar_rechazadas(sesion: Session, uuids: list[UUID], motivo: str) -> None:
    """Las que el LRS rechazó por su contenido: salen de la cola con el motivo escrito.

    No se borran. Una sentencia rechazada sin rastro es una falla invisible, que es justo lo que
    RF-22 prohíbe para la cuarentena y vale igual aquí.
    """
    if not uuids:
        return
    sesion.execute(
        update(EventoXapi)
        .where(EventoXapi.uuid.in_(uuids))
        .values(motivo_rechazo=motivo[:500], intentos=EventoXapi.intentos + 1)
    )
