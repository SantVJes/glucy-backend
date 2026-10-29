"""`POST /explain`: arma el prompt, pregunta, revisa y cachea (RF-28, punto 11 de la rúbrica).

El orden es el que importa:

1. Si el asistente está apagado o no hay Ollama configurado → plantilla, sin llamar a nada.
2. Si la respuesta está en caché → esa.
3. Se pregunta con 10 s de tope.
4. Si no contesta → plantilla (P-13).
5. Si contesta pero no pasa la validación → plantilla, y se registra el motivo.
6. Si pasa → se cachea y se devuelve.

**La plantilla determinista no es un plan de emergencia, es el piso.** La función nunca depende
de que una computadora ajena esté encendida, y por eso se puede prometer en el reporte.
"""

import logging
from collections import OrderedDict

from app.schemas.explicacion import ExplicacionEntrada, RespuestaExplicacion
from app.services.explicacion import ollama
from app.services.explicacion.prompt import mensaje_de_usuario
from app.services.explicacion.validacion import numeros, revisar
from referencia.reglas_clinicas import plantilla_explicacion

registro = logging.getLogger(__name__)

# Caché en memoria del proceso, con tope. No es una tabla a propósito: una explicación es
# texto derivado de datos que ya están en otra parte, y la llave no lleva nada de quién
# preguntó, así que dos personas con los mismos números comparten entrada y la caché no guarda
# nada de nadie. Si el proceso se reinicia se vuelve a preguntar, que es lo barato.
MAXIMO_EN_CACHE = 512
_cache: OrderedDict[tuple, RespuestaExplicacion] = OrderedDict()


def llave(entrada: ExplicacionEntrada) -> tuple:
    """La llave de caché: los valores que de verdad cambian la explicación, redondeados.

    Redondear es lo que hace que la caché sirva: una glucosa de 112.3 y otra de 112.4 producen
    la misma explicación, y pedir dos veces lo mismo no tiene por qué costar dos llamadas.
    """
    return (
        round(entrada.valor_actual),
        round(entrada.valor_predicho),
        entrada.horizonte_min,
        entrada.modo,
        round(entrada.umbral_hipo),
        round(entrada.umbral_hiper),
        round(entrada.cob_g),
        round(entrada.iob_ui, 1),
        entrada.hora_local,
        tuple(sorted((c.variable, round(c.mg_dl)) for c in entrada.shap)),
    )


def _plantilla(entrada: ExplicacionEntrada, motivo: str) -> RespuestaExplicacion:
    """La explicación armada por programa con los mismos valores SHAP, desde la referencia."""
    texto = plantilla_explicacion(
        entrada.valor_actual,
        entrada.valor_predicho,
        [(c.variable, c.mg_dl) for c in entrada.shap],
    )
    return RespuestaExplicacion(explicacion=texto, origen="plantilla", motivo=motivo)


def explicar(
    entrada: ExplicacionEntrada,
    url_ollama: str | None,
    modelo: str,
    timeout_s: float,
) -> RespuestaExplicacion:
    """La explicación de una predicción, del modelo de lenguaje o de la plantilla."""
    if not entrada.asistente_activo or not url_ollama:
        return _plantilla(entrada, "sin_asistente")

    mensaje = mensaje_de_usuario(entrada)
    en_cache = _cache.get(llave(entrada))
    if en_cache is not None:
        _cache.move_to_end(llave(entrada))
        return en_cache

    try:
        texto = ollama.pedir_explicacion(url_ollama, modelo, mensaje, timeout_s)
    except ollama.SinRespuesta as error:
        # No se registra el contenido de la petición: lleva datos de salud.
        registro.warning("el modelo de lenguaje no contestó: %s", error)
        return _plantilla(entrada, "sin_respuesta")

    rechazo = revisar(texto, numeros(mensaje))
    if rechazo is not None:
        registro.warning("respuesta descartada, %s", rechazo.motivo)
        return _plantilla(entrada, "no_paso_validacion")

    respuesta = RespuestaExplicacion(explicacion=texto, origen="modelo", modelo=modelo)
    _cache[llave(entrada)] = respuesta
    while len(_cache) > MAXIMO_EN_CACHE:
        _cache.popitem(last=False)
    return respuesta


def vaciar_cache() -> None:
    """Para las pruebas: una caché compartida entre pruebas las vuelve dependientes del orden."""
    _cache.clear()
