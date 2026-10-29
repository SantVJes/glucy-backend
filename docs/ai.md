# Modelos y explicación

Los modelos, sus características, las métricas alcanzadas y el
modelo de lenguaje con su licencia. Sale de los puntos 10 y 11 del reporte.

## Los tres modelos

M-1 glucosa a 30 min · M-2 glucosa a 60 min · M-3 pico postprandial.

## Metas

Clarke A+B ≥ 95 %, sensibilidad a hipoglucemia ≥ 85 %, falsas alarmas ≤ 15 %,
RMSE a 30 min ≤ 20 mg/dL.

## Modelo de lenguaje

Qwen3 8B (Apache 2.0) ejecutado con Ollama (MIT) en el servidor del
proyecto. No predice ni decide: redacta lo que XGBoost ya calculó.

_Pendiente de llenar._

## Qué queda registrado de cada explicación

Una fila en `explicaciones` (tabla catorce, C-13): si contestó el modelo o la plantilla, por qué
si fue la plantilla, cuánto tardó, el horizonte y el modo. **Nada del contenido**: ni el prompt,
ni el texto, ni un valor de glucosa, ni las contribuciones SHAP.

Es lo que lee el panel 8, y es la cifra que hace creíble al componente de IA generativa en el
reporte: la plantilla determinista no es un plan de emergencia, es el piso de la función, y sin
bitácora no hay forma de decir cada cuánto se pisa. Si la escritura falla, **la explicación se
devuelve igual**: es una bitácora, no parte de la función.
