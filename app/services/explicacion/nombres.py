"""Los nombres de las características, en palabras que una persona entiende.

El modelo trabaja con `rezago_5`, `derivada_2` y `cob`. Esos nombres son el contrato con el
pipeline y con `glucy-ml`, y no se tocan. Pero **no pueden llegar a una pantalla**: la regla de
textos del proyecto dice «carbohidratos que siguen activos», no «COB», y hasta ahora las
contribuciones SHAP viajaban con su nombre crudo tanto a la plantilla determinista como al
prompt del modelo de lenguaje.

Lo segundo era lo peor de los dos. El sistema le pide al modelo que no use tecnicismos y acto
seguido le entrega los datos en tecnicismos: para obedecer, el modelo tiene que **adivinar** qué
significa `rezago_30`. Un modelo que adivina sobre datos de salud es exactamente lo que el
servicio de explicación existe para evitar.
"""

from collections.abc import Sequence

# Una entrada por cada nombre de `CARACTERISTICAS_DENSAS` y `CARACTERISTICAS_DISPERSAS`. Hay
# una prueba que falla si alguna se queda fuera: una característica nueva sin su nombre
# llegaría cruda a la pantalla y nadie lo notaría hasta leerla.
NOMBRES: dict[str, str] = {
    "mg_dl": "tu glucosa de ahora",
    "rezago_5": "tu glucosa de hace 5 minutos",
    "rezago_10": "tu glucosa de hace 10 minutos",
    "rezago_15": "tu glucosa de hace 15 minutos",
    "rezago_30": "tu glucosa de hace media hora",
    "rezago_60": "tu glucosa de hace una hora",
    "derivada_1": "qué tan rápido va cambiando",
    "derivada_2": "si el cambio se está acelerando o frenando",
    "media_30": "tu promedio de la última media hora",
    "media_60": "tu promedio de la última hora",
    "cob": "los carbohidratos que siguen activos",
    "iob": "la insulina que sigue activa",
    # Las dos mitades de la hora cíclica son una sola idea para quien lee. Comparten nombre a
    # propósito: `legibles` las suma, y sumarlas es correcto porque SHAP es aditivo.
    "hora_sin": "la hora del día",
    "hora_cos": "la hora del día",
    "dia_semana": "el día de la semana",
    "antiguedad_min": "qué tan vieja es tu última medición",
    "carbs_g": "lo que comiste",
    "dosis_ui": "la insulina que te aplicaste",
    "contexto_comida": "en qué momento del día mediste",
    "promedio_7d": "tu promedio de la última semana",
}


def legible(variable: str) -> str:
    """El nombre en palabras, o el crudo si no está en la tabla.

    Se devuelve el crudo en lugar de reventar: una explicación con un nombre feo es peor que
    una bonita, pero mucho mejor que ninguna. La prueba de cobertura es la que impide que eso
    pase en silencio.
    """
    return NOMBRES.get(variable, variable)


def legibles(contribuciones: Sequence[tuple[str, float]]) -> list[tuple[str, float]]:
    """Las contribuciones con nombre en palabras, sumando las que comparten nombre.

    Sumar es legítimo y no es un atajo de redacción: SHAP reparte el total de forma **aditiva**,
    así que la contribución de una idea compuesta por dos columnas es la suma de las dos. Sin
    esto, «la hora del día» aparecería dos veces con dos cifras distintas, que es justo lo que
    hace que una explicación deje de creerse.
    """
    sumadas: dict[str, float] = {}
    for variable, mg_dl in contribuciones:
        nombre = legible(variable)
        sumadas[nombre] = sumadas.get(nombre, 0.0) + mg_dl
    return sorted(sumadas.items(), key=lambda par: abs(par[1]), reverse=True)
