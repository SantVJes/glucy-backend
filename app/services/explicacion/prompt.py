"""El prompt del servicio de explicación: sistema fijo y mensaje de usuario estructurado.

Es la única pieza del sistema que habla con un modelo de lenguaje. El prompt vive aquí, en un
módulo sin red y sin estado, para que se pueda leer completo en una pantalla y probar sin
levantar nada: lo que se le manda a un modelo que redacta en nombre de la app es tan parte del
producto como una validación.
"""

from app.schemas.explicacion import ExplicacionEntrada
from app.services.nombres import legibles

# El sistema es fijo y no se arma con datos: así no hay forma de que un valor del teléfono
# cambie las reglas. Las prohibiciones son la regla 7 escrita en el único lugar donde el texto
# no lo decide el programa.
SISTEMA = (
    "Eres el asistente de Glucy, una app para personas con diabetes. Explicas en español de "
    "México por qué la glucosa va a cambiar, en un máximo de tres frases cortas, hablándole a "
    "la persona de tú.\n"
    "Reglas que no puedes romper:\n"
    "- Nunca sugieras una dosis de insulina, ni unidades, ni gramos de carbohidratos, ni "
    "ningún medicamento.\n"
    "- Nunca digas a la persona qué hacer ni qué tomar: solo explicas.\n"
    "- Nunca diagnostiques.\n"
    "- Usa únicamente los datos que te doy. No inventes ninguna cifra, ni redondees a otra "
    "distinta, ni menciones números que no estén en los datos.\n"
    "- No uses tecnicismos: di «carbohidratos que siguen activos» en lugar de «COB» e "
    "«insulina que sigue activa» en lugar de «IOB».\n"
    "- Cierra recordando que es una estimación y que conviene confirmarla con una medición.\n"
    "Responde solo con las frases, sin listas, sin encabezados y sin repetir los datos."
)

_MODO_EN_PALABRAS = {
    "sensor": "con sensor conectado",
    "sin_sensor": "sin sensor, a partir de mediciones sueltas",
}


def mensaje_de_usuario(entrada: ExplicacionEntrada) -> str:
    """Los datos, estructurados y en el orden en que se explican.

    Las contribuciones van con su signo y su unidad, ordenadas de mayor a menor en valor
    absoluto: son el contenido de la explicación, y el modelo solo las redacta. Lo que no está
    aquí no existe para el modelo; en particular no está quién es la persona.

    Y van **con nombre en palabras**. El sistema le prohíbe al modelo usar tecnicismos; mandarle
    `rezago_30` y `derivada_2` lo obligaba a adivinar qué significan para poder obedecer, y un
    modelo que adivina sobre datos de salud es lo que este servicio existe para evitar.
    """
    contribuciones = legibles([(c.variable, c.mg_dl) for c in entrada.shap])
    lineas = [
        f"Glucosa ahora: {entrada.valor_actual:.0f} mg/dL",
        f"Glucosa estimada en {entrada.horizonte_min} minutos: {entrada.valor_predicho:.0f} mg/dL",
        f"Modo: {_MODO_EN_PALABRAS[entrada.modo]}",
        f"Umbral de glucosa baja de esta persona: {entrada.umbral_hipo:.0f} mg/dL",
        f"Umbral de glucosa alta de esta persona: {entrada.umbral_hiper:.0f} mg/dL",
        f"Carbohidratos que siguen activos: {entrada.cob_g:.0f} g",
        f"Insulina que sigue activa: {entrada.iob_ui:.1f} unidades",
        f"Hora local: {entrada.hora_local} h",
        "Lo que más empuja la estimación, de mayor a menor:",
    ]
    lineas += [f"- {nombre}: {mg_dl:+.0f} mg/dL" for nombre, mg_dl in contribuciones]
    return "\n".join(lineas)
