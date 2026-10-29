"""`POST /xapi`: el reparto de un lote de eventos de aprendizaje en las tres listas.

No reusa `services.ingesta.ingerir`, y vale decir por qué: ese reparto es el de los tres lotes
clínicos, que comparten forma —todos traen `zona_horaria`, y todos sus campos de entrada son
columnas de su tabla—. Aquí ninguna de las dos cosas es cierta: un evento de aprendizaje no
tiene hora local que importe, y de sus seis campos solo dos son columnas, porque `actor`,
`verbo`, `objeto` y `resultado` los arma el servidor. Meter dos interruptores en la función
genérica para doblarla a este caso habría tocado el camino por el que pasan las lecturas de
glucosa, que es el que no conviene mover. Lo que sí se reusa son las piezas: la cuarentena, los
motivos legibles y la inserción idempotente.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models.tablas import EventoXapi
from app.repositories import lotes as repo_lotes
from app.repositories import usuarios as repo_usuarios
from app.schemas.lotes import RenglonEnCuarentena
from app.schemas.xapi import (
    COLUMNAS_XAPI_EVENTS,
    COMBINACIONES,
    EventoXapiEntrada,
    Verbo,
)
from app.services.ingesta import a_cuarentena, motivo_de_validacion
from app.services.xapi.sentencia import actor_de, objeto_de, resultado_de

TABLA = "xapi_events"

# Un puntaje solo significa algo donde hay algo que puntuar. Un `puntaje` en «registró una
# medición de glucosa» no es un dato raro: es la señal de que el teléfono está mandando otra
# cosa de la que cree, y el panel de indicadores de aprendizaje acabaría promediando basura.
VERBOS_CON_PUNTAJE = frozenset({Verbo.ANSWERED, Verbo.COMPLETED})

_MOTIVOS_PROPIOS = {
    "extra_forbidden": (
        "no es campo de un evento de aprendizaje: el actor, el objeto y el resultado los arma "
        "el servidor, y nada de texto libre sale del teléfono (regla 3)"
    ),
}


@dataclass(frozen=True)
class Resultado:
    aceptados: list[UUID]
    duplicados: list[UUID]
    cuarentena: list[RenglonEnCuarentena]


def ingerir_eventos(
    sesion: Session, usuario_uuid: UUID, renglones: list[dict[str, Any]], ahora: datetime
) -> Resultado:
    """Reparte el lote. Cada renglón sale en exactamente una de las tres listas (RF-22).

    `ahora` entra como parámetro para que una prueba de marca de tiempo futura pueda fijar el
    presente, igual que en los tres lotes clínicos.
    """
    repo_usuarios.asegurar_que_existe(sesion, usuario_uuid, ts_alta=ahora)

    cuarentena: list[RenglonEnCuarentena] = []
    sobrevivientes: list[EventoXapiEntrada] = []

    for renglon in renglones:
        validado = _validar(renglon, usuario_uuid, ahora)
        if isinstance(validado, str):
            a_cuarentena(sesion, renglon, validado, ahora, TABLA, COLUMNAS_XAPI_EVENTS)
            cuarentena.append(RenglonEnCuarentena(uuid=_uuid_legible(renglon), motivo=validado))
        else:
            sobrevivientes.append(validado)

    entraron = set(
        repo_lotes.insertar_ignorando_duplicados(
            sesion, EventoXapi, [_fila(e, usuario_uuid) for e in sobrevivientes]
        )
    )
    aceptados: list[UUID] = []
    duplicados: list[UUID] = []
    for entrada in sobrevivientes:
        if entrada.uuid in entraron:
            entraron.discard(entrada.uuid)
            aceptados.append(entrada.uuid)
        else:
            duplicados.append(entrada.uuid)

    sesion.commit()
    return Resultado(aceptados=aceptados, duplicados=duplicados, cuarentena=cuarentena)


def _validar(
    renglon: dict[str, Any], usuario_uuid: UUID, ahora: datetime
) -> EventoXapiEntrada | str:
    """El evento validado, o el motivo por el que va a cuarentena."""
    sin_usuario = {k: v for k, v in renglon.items() if k != "usuario_uuid"}
    try:
        entrada = EventoXapiEntrada.model_validate(sin_usuario)
    except ValidationError as error:
        return motivo_de_validacion(error, _MOTIVOS_PROPIOS)

    if "usuario_uuid" in renglon and str(renglon["usuario_uuid"]).lower() != str(usuario_uuid):
        return "usuario_uuid del cuerpo distinto del token: solo se escribe en la serie propia"

    if entrada.ts_utc > ahora:
        return "marca de tiempo futura: un hecho de aprendizaje no puede no haber ocurrido"

    if entrada.actividad not in COMBINACIONES[entrada.verbo]:
        permitidas = ", ".join(sorted(a.value for a in COMBINACIONES[entrada.verbo]))
        return (
            f"el verbo {entrada.verbo.value!r} no va con la actividad "
            f"{entrada.actividad.value!r}: solo con {permitidas}"
        )

    if entrada.puntaje is not None and entrada.verbo not in VERBOS_CON_PUNTAJE:
        con_puntaje = ", ".join(sorted(v.value for v in VERBOS_CON_PUNTAJE))
        return f"puntaje en un verbo que no puntúa nada: solo lo llevan {con_puntaje}"

    return entrada


def _fila(entrada: EventoXapiEntrada, usuario_uuid: UUID) -> dict[str, Any]:
    """La fila de `xapi_events`: ya con el actor, el objeto y el resultado armados.

    Se guardan armados y no en crudo porque la fila tiene que ser **lo que se le mandó al LRS**.
    Si se guardaran los seis campos de entrada y la sentencia se armara al enviar, dos
    versiones del servicio mandarían sentencias distintas desde la misma fila y no quedaría
    rastro de cuál salió. Lo único que no se guarda es el IRI del verbo, porque sale de la
    tabla `VERBOS` y guardarlo dos veces los dejaría divergir.
    """
    return {
        "uuid": entrada.uuid,
        "usuario_uuid": usuario_uuid,
        "ts_utc": entrada.ts_utc,
        "actor": actor_de(usuario_uuid),
        "verbo": entrada.verbo.value,
        "objeto": objeto_de(entrada.actividad),
        "resultado": resultado_de(entrada.exito, entrada.puntaje, entrada.duracion_s),
    }


def _uuid_legible(renglon: dict[str, Any]) -> UUID | None:
    try:
        return UUID(str(renglon["uuid"]))
    except (KeyError, ValueError):
        return None
