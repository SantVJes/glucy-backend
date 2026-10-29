"""La respuesta del modelo de lenguaje se revisa **antes** de mostrarla.

Un modelo de lenguaje es la única pieza del sistema cuya salida no se puede predecir, y está
justo delante de una persona que puede estar en una hipoglucemia. Así que no se confía en que
el prompt baste: lo que no pasa estas dos comprobaciones no se corrige ni se recorta, **se
descarta**, y sale la plantilla determinista (P-13).

Se falla cerrado a propósito. Un falso positivo cuesta una frase menos natural; un falso
negativo es una app no certificada insinuando un tratamiento.
"""

import re
import unicodedata
from dataclasses import dataclass

# Verbos y expresiones con los que se le dice a alguien que haga algo con insulina o con
# comida. La frontera que importa no es la palabra «unidades» —decir cuánta insulina sigue
# activa es un hecho sobre el pasado— sino el verbo que convierte el hecho en una indicación.
INDICACIONES = (
    r"inyect\w*",
    r"\baplicate\b",
    r"\baplica\b",
    r"\bponte\b",
    r"\bpon\b",
    r"\badminist\w*",
    r"\bpinch\w*",
    r"\bcorrige\b",
    r"\bcorrig\w*",
    r"\bcorrecci[oó]n\b",
    r"\bbolo\b",
    r"\bbasal\b",
    # «sube» y «baja» solos no se pueden prohibir: la explicación habla justo de eso, de que
    # la glucosa sube o baja, y la plantilla determinista empieza con esa palabra. Lo que se
    # prohíbe es subir o bajar **una dosis**.
    r"\b(sube|baja|subele|bajale|aumenta|reduce)\s+(la|el|tu)?\s*(dosis|basal|insulina|ratio)",
    r"\bagrega\b",
    r"\bañade\b",
    r"\btoma\b",
    r"\btomate\b",
    r"\btomes\b",
    r"\bcome\b",
    r"\bcomete\b",
    r"\bcomas\b",
    r"\bingier\w*",
    r"\bmerienda\b",
    r"\bnecesitas\b",
    r"\bdebes\b",
    r"\btienes que\b",
    r"\bte conviene\s+\w*(tomar|comer|poner|inyectar)",
    r"\brecomiendo\b",
    r"\bte sugiero\b",
)

# «UI» y «U» como unidad de insulina no tienen por qué aparecer nunca en la superficie: la app
# le habla a la persona de «insulina que sigue activa», no de UI. Si aparecen, algo salió del
# vocabulario permitido.
UNIDADES_PROHIBIDAS = (
    r"\bui\b",
    r"\bu\.?i\.?\b",
    r"\bunidades? de insulina\b",
)

_NUMERO = re.compile(r"-?\d+(?:[.,]\d+)?")
_PATRONES = tuple(re.compile(p) for p in INDICACIONES + UNIDADES_PROHIBIDAS)

# Tolerancia al comparar cifras: el modelo puede escribir 112 donde el dato decía 112.0, o
# 2,5 con coma. Más allá de eso es una cifra distinta, y una cifra distinta es inventada.
TOLERANCIA = 0.05


@dataclass(frozen=True)
class Rechazo:
    """Por qué no se muestra la respuesta. El motivo se registra, no se le enseña a nadie."""

    motivo: str


def sin_acentos(texto: str) -> str:
    """Minúsculas y sin acentos, para que «aplícate» y «aplicate» se traten igual."""
    descompuesto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def numeros(texto: str) -> list[float]:
    """Las cifras del texto, con punto o coma decimal."""
    return [float(bruto.replace(",", ".")) for bruto in _NUMERO.findall(texto)]


def revisar(respuesta: str, numeros_permitidos: list[float]) -> Rechazo | None:
    """`None` si la respuesta se puede mostrar; un `Rechazo` con su motivo si no.

    Dos comprobaciones, en este orden:

    1. **Ninguna indicación de tratamiento.** Es la regla 7 y es la que puede lastimar a
       alguien, así que se revisa primero y sobre el texto sin acentos.
    2. **Ninguna cifra que no viniera en la petición.** Un modelo que redondea 112 a 110 ya
       cambió el dato; uno que menciona un 7.2 que nadie le dio se lo inventó.
    """
    plano = sin_acentos(respuesta)
    if not respuesta.strip():
        return Rechazo("respuesta vacía")
    for patron in _PATRONES:
        encontrado = patron.search(plano)
        if encontrado:
            return Rechazo(f"indicación de tratamiento: «{encontrado.group(0)}»")
    magnitudes = [abs(permitido) for permitido in numeros_permitidos]
    for valor in numeros(respuesta):
        # Se compara el **valor absoluto**: una contribución de −20 mg/dL se puede redactar
        # como «quita 20 mg/dL», y el signo lo llevan las palabras. Lo que no puede cambiar
        # es la magnitud, porque esa es el dato.
        if not any(abs(abs(valor) - magnitud) <= TOLERANCIA for magnitud in magnitudes):
            return Rechazo(f"cifra que no venía en la petición: {valor:g}")
    return None
