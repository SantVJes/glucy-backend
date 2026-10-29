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

## Los nombres que ve la persona, y los que ve el modelo

El modelo trabaja con `rezago_30`, `derivada_2` y `cob`. Esos nombres son el contrato con el
pipeline y con `glucy-ml` y no se tocan nunca, pero **no salen de ahí**:
`app/services/explicacion/nombres.py` los traduce antes de la plantilla y antes del prompt.

Dos motivos, y el segundo pesa más:

1. La regla de textos del proyecto: «carbohidratos que siguen activos», no «COB».
2. El sistema del prompt le prohíbe al modelo usar tecnicismos, y luego le entregaba los datos
   **en tecnicismos**. Para obedecer, el modelo tenía que adivinar qué significa `rezago_30`.
   Un modelo que adivina sobre datos de salud es exactamente lo que este servicio existe para
   evitar.

`hora_sin` y `hora_cos` comparten nombre —«la hora del día»— y sus contribuciones **se suman**.
Sumarlas es correcto, no un atajo de redacción: SHAP reparte el total de forma aditiva, así que
la contribución de una idea compuesta por dos columnas es la suma de las dos. Sin esto, «la hora
del día» salía dos veces con dos cifras distintas, que es justo lo que hace que una explicación
deje de creerse.

Hay una prueba que falla si una característica nueva se queda sin nombre.

## C-15: la plantilla ya no se contradice

Así salía antes:

> «**Sube** sobre todo por tu glucosa de ahora (**−29** mg/dL).»

No es un descuido de redacción. La dirección compara el valor predicho con el actual; una
contribución SHAP se mide contra el **valor base del modelo**, no contra el de ahora. Son dos
referencias distintas, y la palabra «por» unía dos cosas que no se pueden unir.

Ahora la dirección y el peso van por separado:

> «Vas a subir. Lo que más pesa en la estimación: tu glucosa de ahora (−29 mg/dL) y los
> carbohidratos que siguen activos (+14 mg/dL). Es una estimación: conviene confirmar con una
> medición antes de actuar.»

Importa porque esta plantilla es el **piso** de la función de explicación: lo único que el
reporte promete que funciona con el modelo de lenguaje apagado, con la computadora apagada y sin
internet. Un piso que se contradice no sostiene nada.

El cambio está en `referencia/reglas_clinicas.py`, que es la referencia compartida por los tres
repositorios: si alguna vez se escribe esta plantilla en Swift, tiene que decir lo mismo.
