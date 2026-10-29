"""El cliente del modelo de lenguaje. La única pieza del sistema que habla con Ollama.

La app no sabe qué modelo hay del otro lado: cambiarlo mañana no toca ni una línea de Swift, y
tampoco toca nada fuera de este módulo.

Ollama es software de terceros (gris en el C4): se instala y se consume, no se escribe aquí.
"""

import httpx

from app.services.explicacion.prompt import SISTEMA

# La misma predicción tiene que producir siempre la misma explicación: con temperatura 0 y
# semilla fija, dos personas que miran la misma pantalla leen lo mismo, y una explicación que
# cambia sola no se puede revisar ni citar en el reporte.
TEMPERATURA = 0.0
SEMILLA = 7
# Tres frases cortas caben de sobra en 160 fichas. El tope también acota lo que hay que
# revisar: una respuesta larga es una respuesta que se fue por su cuenta.
MAXIMO_FICHAS = 160


class SinRespuesta(Exception):
    """No contestó a tiempo, contestó un error, o no hay Ollama a dónde preguntar.

    Es la única excepción que este módulo deja salir: quien llama no tiene que distinguir un
    tiempo agotado de una computadora apagada, porque la salida es la misma (P-13).
    """


def pedir_explicacion(url: str, modelo: str, mensaje: str, timeout_s: float) -> str:
    """El texto que devolvió el modelo, tal cual, sin revisar. Revisarlo es de `validacion`.

    `timeout_s` cubre **toda** la llamada, no solo la conexión: los 10 segundos del requisito
    son el tiempo que la persona espera, no el que tarda en abrirse el socket.
    """
    try:
        respuesta = httpx.post(
            f"{url.rstrip('/')}/api/chat",
            json={
                "model": modelo,
                "stream": False,
                "messages": [
                    {"role": "system", "content": SISTEMA},
                    {"role": "user", "content": mensaje},
                ],
                "options": {
                    "temperature": TEMPERATURA,
                    "seed": SEMILLA,
                    "num_predict": MAXIMO_FICHAS,
                },
            },
            timeout=timeout_s,
        )
        respuesta.raise_for_status()
        contenido = respuesta.json()["message"]["content"]
    except (httpx.HTTPError, KeyError, ValueError) as error:
        raise SinRespuesta(str(error)) from error
    if not isinstance(contenido, str):
        raise SinRespuesta("la respuesta no trae texto")
    return contenido.strip()
