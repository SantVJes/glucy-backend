"""El cliente de Learning Locker. La única pieza del sistema que le habla al LRS.

Learning Locker es software de terceros: se instala y se consume, no se escribe aquí. Cambiarlo
por otro LRS que hable xAPI no toca nada fuera de este módulo.
"""

import os
from dataclasses import dataclass
from typing import Any

import httpx

from app.schemas.xapi import VERSION_XAPI

# La cabecera NO es opcional: sin ella Learning Locker contesta 400 a todo, y el error que
# llega no dice que falte una cabecera. Es el primer tropiezo de cualquiera que integre xAPI.
CABECERA_VERSION = "X-Experience-API-Version"

# Un lote más grande no ahorra nada y hace que un solo renglón malo tumbe más sentencias: el
# LRS valida el lote completo y contesta 400 por todo si una no pasa.
MAXIMO_POR_LOTE = 100


@dataclass(frozen=True)
class ConfiguracionLrs:
    """Dónde está el LRS y con qué credenciales. Vacía = no hay LRS, y no se manda nada.

    Es un tipo propio y no los `Ajustes` de la API a propósito: la orden que vacía la cola se
    corre desde `cron` y **no necesita el secreto del token**, que es lo único sin valor por
    omisión en los ajustes. Pedirle a la orden el secreto de la API para mandar sentencias de
    aprendizaje sería obligar a tener a mano una credencial que no usa.
    """

    url: str = ""
    usuario: str = ""
    secreto: str = ""
    timeout_s: float = 10.0

    @classmethod
    def del_entorno(cls) -> "ConfiguracionLrs":
        """Las mismas variables que lee la API, por si la orden corre sin ella."""
        return cls(
            url=os.environ.get("GLUCY_LRS_URL", ""),
            usuario=os.environ.get("GLUCY_LRS_USUARIO", ""),
            secreto=os.environ.get("GLUCY_LRS_SECRETO", ""),
            timeout_s=float(os.environ.get("GLUCY_LRS_TIMEOUT_S", "10")),
        )


class LrsNoDisponible(Exception):
    """No contestó, contestó un error, o no hay LRS a dónde mandar.

    Es la única excepción que sale de aquí: quien llama no distingue un tiempo agotado de un
    contenedor apagado, porque hace lo mismo con los dos, dejar las sentencias en la cola.
    """


class LoteRechazado(Exception):
    """El LRS entendió la petición y rechazó el lote (400 o 409).

    Es distinto de `LrsNoDisponible` y por eso es otra excepción: reintentar un lote que el LRS
    ya rechazó por su contenido lo rechazaría igual mañana, y la cola se quedaría atorada
    reintentando lo mismo para siempre. Un lote así se marca con su motivo y se saca del
    camino, igual que la cuarentena del paso 2.
    """


def enviar(configuracion: ConfiguracionLrs, sentencias: list[dict[str, Any]]) -> None:
    """Manda un lote de sentencias. Vuelve sin decir nada si el LRS las aceptó.

    El tope de tiempo cubre toda la llamada y no solo la conexión: lo que importa es cuánto
    tarda el envío, no cuánto tarda en abrirse el socket.
    """
    if not configuracion.url:
        raise LrsNoDisponible("sin GLUCY_LRS_URL: no hay Learning Record Store configurado")
    if not sentencias:
        return
    try:
        respuesta = httpx.post(
            f"{configuracion.url.rstrip('/')}/data/xAPI/statements",
            json=sentencias,
            headers={CABECERA_VERSION: VERSION_XAPI},
            auth=(configuracion.usuario, configuracion.secreto),
            timeout=configuracion.timeout_s,
        )
    except httpx.HTTPError as error:
        raise LrsNoDisponible(str(error)) from error

    if respuesta.status_code in (400, 409):
        # 409 en xAPI es «ese id ya existe con otro contenido». Como el id es el uuid del
        # teléfono, significa que la sentencia ya está en el LRS: reintentarla no la va a
        # cambiar, así que se trata como rechazo y no como caída.
        raise LoteRechazado(f"{respuesta.status_code}: {_motivo(respuesta)}")
    if respuesta.status_code in (401, 403):
        # Credenciales: no es culpa de las sentencias y reintentar con las mismas no sirve,
        # pero tampoco hay que marcarlas como rechazadas. Se deja la cola quieta y se avisa.
        raise LrsNoDisponible(f"{respuesta.status_code}: el LRS no aceptó las credenciales")
    if respuesta.status_code >= 500 or respuesta.status_code >= 300:
        raise LrsNoDisponible(f"{respuesta.status_code}: {_motivo(respuesta)}")


def _motivo(respuesta: httpx.Response) -> str:
    """Lo que el LRS dijo, acotado: su cuerpo de error puede traer la sentencia completa."""
    return respuesta.text[:200].strip() or "sin cuerpo"
