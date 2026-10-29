"""La ventana de envío al Learning Record Store: vaciar la cola sin que nada dependa de ella.

La propiedad que sostiene el requisito es la de abajo, y conviene leerla antes del código: si el
LRS no contesta, **no se toca ninguna fila** y la ventana se detiene diciendo por qué. Las
sentencias siguen pendientes, una caída de una semana no gasta nada, y ninguna función de la
app se enteró (RF-19, RF-33).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.tablas import EventoXapi
from app.repositories import xapi as repo
from app.schemas.xapi import IDIOMA, VERBOS, Verbo
from app.services.xapi.lrs import (
    MAXIMO_POR_LOTE,
    ConfiguracionLrs,
    LoteRechazado,
    LrsNoDisponible,
    enviar,
)

# Tope de lotes por ventana. Sin tope, la primera corrida contra una base con ocho semanas de
# eventos se quedaría horas y nadie sabría si avanzó. Con tope, la ventana termina, dice cuánto
# queda y la siguiente sigue donde se quedó.
MAXIMO_LOTES_POR_VENTANA = 20


@dataclass(frozen=True)
class ResumenEnvio:
    """Lo que pasó en una ventana. `detenida_por` es el motivo si el LRS no estaba."""

    enviadas: int
    rechazadas: int
    pendientes: int
    detenida_por: str | None = None

    @property
    def el_lrs_contesto(self) -> bool:
        return self.detenida_por is None


def enviar_pendientes(
    sesion: Session, configuracion: ConfiguracionLrs, ahora: datetime
) -> ResumenEnvio:
    """Manda lo que falta, por lotes y lo más antiguo primero."""
    if not configuracion.url:
        # Ni se consulta la base: sin LRS configurado no hay nada que decidir, y el panel ya
        # sabe cuántas esperan. Es el mismo piso que la explicación sin Ollama (P-13).
        return ResumenEnvio(
            enviadas=0,
            rechazadas=0,
            pendientes=repo.cuantas_pendientes(sesion),
            detenida_por="sin GLUCY_LRS_URL: no hay Learning Record Store configurado",
        )

    enviadas = rechazadas = 0
    detenida_por: str | None = None

    for _ in range(MAXIMO_LOTES_POR_VENTANA):
        filas = repo.pendientes(sesion, MAXIMO_POR_LOTE)
        if not filas:
            break

        sentencias: list[dict[str, Any]] = []
        legibles: list[EventoXapi] = []
        for fila in filas:
            sentencia = _sentencia_de(fila)
            if isinstance(sentencia, str):
                # Una fila que no se puede convertir en sentencia no puede quedarse al frente
                # de la cola: taparía todo lo que viene detrás, igual que la fila sin endpoint
                # de la cola del teléfono. Sale con su motivo.
                repo.marcar_rechazadas(sesion, [fila.uuid], sentencia)
                rechazadas += 1
                continue
            sentencias.append(sentencia)
            legibles.append(fila)

        if not sentencias:
            sesion.commit()
            continue

        try:
            enviar(configuracion, sentencias)
        except LrsNoDisponible as error:
            sesion.commit()  # las rechazadas de este lote, si hubo; ninguna otra fila se tocó
            detenida_por = str(error)
            break
        except LoteRechazado:
            # xAPI valida el lote completo: una sentencia mala hace que el LRS conteste 400 por
            # las cien. Reintentarlas de una en una es la única forma de no tirar las noventa y
            # nueve buenas por una, y pasa poco: un rechazo es un error de programación nuestro.
            uno = _enviar_una_por_una(sesion, configuracion, legibles, sentencias, ahora)
            if uno is None:
                sesion.commit()
                detenida_por = "el LRS dejó de contestar mientras se reintentaba una por una"
                break
            enviadas += uno[0]
            rechazadas += uno[1]
            sesion.commit()
            continue

        repo.marcar_enviadas(sesion, [f.uuid for f in legibles], ahora)
        enviadas += len(legibles)
        sesion.commit()

    return ResumenEnvio(
        enviadas=enviadas,
        rechazadas=rechazadas,
        pendientes=repo.cuantas_pendientes(sesion),
        detenida_por=detenida_por,
    )


def _enviar_una_por_una(
    sesion: Session,
    configuracion: ConfiguracionLrs,
    filas: list[EventoXapi],
    sentencias: list[dict[str, Any]],
    ahora: datetime,
) -> tuple[int, int] | None:
    """Cuántas salieron y cuántas se rechazaron, o `None` si el LRS se cayó a la mitad."""
    enviadas = rechazadas = 0
    for fila, sentencia in zip(filas, sentencias, strict=True):
        try:
            enviar(configuracion, [sentencia])
        except LoteRechazado as error:
            repo.marcar_rechazadas(sesion, [fila.uuid], str(error))
            rechazadas += 1
        except LrsNoDisponible:
            return None
        else:
            repo.marcar_enviadas(sesion, [fila.uuid], ahora)
            enviadas += 1
    return enviadas, rechazadas


def _sentencia_de(fila: EventoXapi) -> dict[str, Any] | str:
    """La sentencia que se guardó, otra vez entera, o el motivo por el que no se puede armar.

    El IRI del verbo no está en la fila: sale de la tabla `VERBOS` a partir del nombre corto que
    sí se guardó. Guardarlo en la fila habría dejado dos copias que divergen cuando el
    vocabulario cambia, y la fila es el rastro de lo que se mandó, no su definición.
    """
    if fila.ts_utc is None:
        return "fila sin marca de tiempo: xAPI exige `timestamp`"
    if not isinstance(fila.actor, dict) or not isinstance(fila.objeto, dict):
        return "fila sin actor o sin objeto: no se puede armar la sentencia"
    try:
        datos = VERBOS[Verbo(fila.verbo)]
    except ValueError:
        return f"verbo que este servicio no conoce: {fila.verbo!r}"

    sentencia: dict[str, Any] = {
        "id": str(fila.uuid),
        "actor": fila.actor,
        "verb": {"id": datos.iri, "display": {IDIOMA: datos.display}},
        "object": fila.objeto,
        "timestamp": fila.ts_utc.isoformat(),
    }
    if fila.resultado:
        sentencia["result"] = fila.resultado
    return sentencia
