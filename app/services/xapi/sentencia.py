"""De una fila de `xapi_events` a una sentencia xAPI 1.0.3.

Aquí está la regla que hace que el LRS sea un registro de aprendizaje y no una segunda copia
de los datos de salud: **la sentencia no lleva ni una cifra clínica**. Dice que la persona
registró una medición, no cuánto marcó; que recibió un aviso de glucosa baja, no de cuántos
mg/dL. Para los indicadores de autocuidado eso alcanza —lo que se quiere saber es si registra y
si responde a los avisos—, y le quita al LRS, que es un servidor de terceros con su propia
base, cualquier razón para contener datos de salud.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.schemas.xapi import (
    ACTIVIDADES,
    BASE_IRI,
    IDIOMA,
    PAGINA_DE_LA_CUENTA,
    VERBOS,
    Actividad,
    Verbo,
)


def actor_de(usuario_uuid: UUID) -> dict[str, Any]:
    """El actor es una cuenta con el UUID seudónimo, y nada más.

    xAPI deja identificar al actor con `mbox`, y es lo primero que aparece en los ejemplos: un
    correo. Aquí sería la fuga completa, porque el servidor no sabe el correo de nadie y el LRS
    tampoco tiene por qué. Con `account` el identificador es el mismo UUID que ya usa todo el
    sistema: en el LRS no hay nombre, ni correo, ni nada que identifique a la persona.
    """
    return {
        "objectType": "Agent",
        "account": {"homePage": PAGINA_DE_LA_CUENTA, "name": str(usuario_uuid)},
    }


def objeto_de(actividad: Actividad) -> dict[str, Any]:
    """La actividad, con su IRI estable y su nombre en español."""
    definicion = ACTIVIDADES[actividad]
    return {
        "objectType": "Activity",
        "id": f"{BASE_IRI}/actividades/{actividad.value}",
        "definition": {
            "type": definicion.tipo,
            "name": {IDIOMA: definicion.nombre},
        },
    }


def resultado_de(
    exito: bool | None, puntaje: float | None, duracion_s: float | None
) -> dict[str, Any] | None:
    """El `result` de xAPI, o `None` cuando no hay nada que decir.

    Un `result` vacío (`{}`) es válido en la especificación pero no significa nada, y en el
    panel aparecería como un resultado que existe. Si los tres campos vienen vacíos, la
    sentencia sale sin `result`.
    """
    resultado: dict[str, Any] = {}
    if exito is not None:
        resultado["success"] = exito
    if puntaje is not None:
        resultado["score"] = {"scaled": puntaje}
    if duracion_s is not None:
        resultado["duration"] = duracion_iso(duracion_s)
    return resultado or None


def duracion_iso(segundos: float) -> str:
    """Los segundos como duración ISO 8601, que es lo que xAPI exige en `result.duration`.

    Un número suelto (`12.5`) hace que el LRS rechace la sentencia entera, y el rechazo llega
    como un 400 del que no se entiende nada mirando la cola.
    """
    return f"PT{segundos:.2f}S".replace(".00S", "S")


def armar(
    uuid: UUID,
    usuario_uuid: UUID,
    ts_utc: datetime,
    verbo: Verbo,
    actividad: Actividad,
    *,
    exito: bool | None = None,
    puntaje: float | None = None,
    duracion_s: float | None = None,
) -> dict[str, Any]:
    """La sentencia completa, lista para `POST {lrs}/data/xAPI/statements`.

    El `id` de la sentencia es el uuid que generó el teléfono, no uno nuevo: así reenviar la
    cola después de un corte no duplica nada en el LRS, que trata un `id` repetido como el
    mismo hecho. Es la misma idempotencia por UUID del resto del sistema (RF-36c).
    """
    datos = VERBOS[verbo]
    sentencia: dict[str, Any] = {
        "id": str(uuid),
        "actor": actor_de(usuario_uuid),
        "verb": {"id": datos.iri, "display": {IDIOMA: datos.display}},
        "object": objeto_de(actividad),
        "timestamp": ts_utc.isoformat(),
    }
    resultado = resultado_de(exito, puntaje, duracion_s)
    if resultado is not None:
        sentencia["result"] = resultado
    return sentencia
