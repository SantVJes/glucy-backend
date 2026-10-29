# Fase 6, paso 1 — el Learning Record Store con xAPI

Fecha: 29 de octubre de 2026 · Rama: `feature/learning-record-store` · RF-19, RF-33

---

## Qué cambia

**Antes:** la tabla `xapi_events` existía desde la migración `0001`, vacía, y el Documento 3
decía «por definir» en la columna de qué sube. No había endpoint, ni cliente del LRS, ni cola.
La fase 6 era la única que no dependía de los datos de OhioT1DM y no estaba empezada.

**Después:** `POST /xapi` recibe lotes de eventos de aprendizaje de la `ColaXapi` del teléfono y
`python -m app.lrs` los manda a Learning Locker. 43 pruebas nuevas, 347 en total.

## La decisión que sostiene el paso: el teléfono no manda una sentencia

La forma natural de leer las columnas de `xapi_events` —`actor`, `verbo`, `objeto`,
`resultado`, los cuatro en JSON— es aceptar la sentencia xAPI ya armada. Sería un error.

Con JSON libre en el cuerpo, **cualquier campo del teléfono puede viajar al LRS por esa
puerta**: una nota, un nombre, una cifra de glucosa. La regla 3 dice que eso nunca sale del
teléfono, y una regla que depende de que el cliente se porte bien no es una regla, es una
esperanza.

Así que el contrato es al revés. El teléfono manda:

| Campo | Qué es |
| --- | --- |
| `uuid`, `ts_utc` | los de siempre |
| `verbo` | uno de seis |
| `actividad` | una de seis |
| `exito`, `puntaje`, `duracion_s` | tres números opcionales |

Y el servidor arma el actor, el objeto y el resultado. **No hay ningún campo de texto libre que
aceptar**, así que no hay nada que filtrar: la propiedad se cumple por construcción y no por
vigilancia. De paso, el cliente no tiene que saber nada de xAPI, y cambiar de LRS mañana no toca
una línea de Swift.

## La otra: la sentencia no lleva ninguna cifra clínica

Dice que la persona registró una medición, **no cuánto marcó**. Que recibió un aviso de glucosa
baja, no de cuántos mg/dL.

Para los indicadores de autocuidado alcanza de sobra: lo que se quiere saber es si registra, si
responde a los avisos, si termina los módulos. Y le quita al LRS —que es un servidor de
terceros, con su propia base de datos y su propio respaldo— cualquier razón para contener datos
de salud. Un Learning Locker con glucosas dentro es un segundo sistema de salud que hay que
proteger, sin que nadie lo haya decidido.

Hay una prueba que busca `mg_dl`, `carbs` y `unidades` en la fila guardada y exige no
encontrarlos.

## El vocabulario, y lo que el reporte tiene que decir

El Documento 2 nombra seis verbos. Cotejados el 29/10/2026 contra `adl/adl.jsonld` de
`adlnet/xapi-authored-profiles`, que es el perfil que publica ADL:

| Verbo | IRI | ¿En el perfil de ADL? |
| --- | --- | --- |
| `experienced` | `http://adlnet.gov/expapi/verbs/experienced` | sí |
| `launched` | `http://adlnet.gov/expapi/verbs/launched` | sí |
| `answered` | `http://adlnet.gov/expapi/verbs/answered` | sí |
| `completed` | `http://adlnet.gov/expapi/verbs/completed` | **no** — está en el perfil cmi5, que es de ADL pero es otro documento |
| `responded` | `http://adlnet.gov/expapi/verbs/responded` | **no** — de uso corriente con ese IRI, y en ninguno de los dos perfiles |
| `received` | `http://activitystrea.ms/schema/1.0/receive` | **no** — no existe en ADL, así que se toma el de Activity Streams 1.0 |

Los tres que salen en falso son **válidos**: xAPI deja crear vocabulario, y es lo que hace
cualquier comunidad de práctica. Lo que no se puede es escribir «xAPI 1.0.3» en el reporte y
dejarlo pasar, porque quien sepa leerlo va a preguntar. Hay una prueba que fija el cotejo, así
que cambiar uno de los seis sin volver a cotejar hace fallar algo.

Y hay una tabla de combinaciones permitidas, verbo por actividad. Sin ella, «contestó una
medición de glucosa» entraría al LRS como una sentencia válida y el panel de indicadores
saldría con basura dentro que nadie podría explicar después.

## El actor: una cuenta, nunca un correo

```json
{"objectType": "Agent",
 "account": {"homePage": "https://github.com/SantVJes/glucy-backend/xapi/usuarios",
             "name": "11111111-1111-1111-1111-111111111111"}}
```

`mbox` —un correo— es lo primero que aparece en los ejemplos de xAPI, y aquí sería la fuga
completa. El servidor no sabe el correo de nadie y el LRS tampoco tiene por qué: el actor es el
mismo UUID seudónimo que ya usa todo el sistema.

Como no hay dominio propio y xAPI identifica con IRI, los de Glucy cuelgan del repositorio, que
es el identificador estable que sí existe. Vive en una constante, `BASE_IRI`: si algún día hay
dominio, es el único lugar que cambia.

## La cola, y por qué hicieron falta tres columnas (C-12)

El Documento 3 fija siete columnas para `xapi_events`. Con esas siete la tabla es un registro de
hechos y **no hay forma de saber qué falta mandar**: un reenvío tendría que mandar todo otra vez
o nada. El requisito dice que si el LRS no responde las sentencias se encolan y se reenvían
después, y una cola necesita saber qué salió.

La migración `0004` agrega `enviado_ts`, `motivo_rechazo` e `intentos`, y queda anotado como
**C-12** para el reporte, igual que la tabla trece del paso 4 (C-9).

La regla entera es una línea: **una sentencia está en la cola cuando `enviado_ts` y
`motivo_rechazo` son nulas.** De ahí salen las tres propiedades que importan:

- **Con el LRS caído no se toca ninguna fila.** La ventana se detiene diciendo por qué. Una
  caída de una semana no gasta reintentos y no tira ninguna sentencia, que es exactamente lo que
  pide el requisito. `intentos` se queda en cero, y hay una prueba que lo comprueba.
- **Un rechazo por contenido saca la sentencia de la cola, con su motivo escrito.** Reintentar
  lo mismo da lo mismo. No se borra: una sentencia rechazada sin rastro es una falla invisible,
  que es lo que RF-22 prohíbe para la cuarentena y vale igual aquí.
- **Las credenciales malas no son culpa de las sentencias.** Un 401 o un 403 deja la cola quieta
  y avisa, en lugar de marcar cien sentencias como rechazadas por un secreto mal copiado.

## Un lote rechazado se reintenta de una en una

xAPI valida el lote completo: si una sentencia de cien no pasa, Learning Locker contesta 400 por
las cien. Marcarlas todas sacaría de la cola a las noventa y nueve buenas por culpa de una.

Así que un 400 dispara el reintento individual, y solo la mala sale con su motivo. Cuesta cien
peticiones y pasa poco —un rechazo es un error de programación nuestro, no del teléfono—, y es
la diferencia entre perder una sentencia y perder un lote.

## Lo que no se reusó, y por qué

`services/ingesta.ingerir` reparte los tres lotes clínicos en las tres listas, y la tentación
era usarlo aquí también. No se hizo: ese reparto supone que todo renglón trae `zona_horaria` y
que sus campos de entrada son las columnas de su tabla. Aquí ninguna de las dos es cierta —un
hecho de aprendizaje no tiene hora local que importe, y de sus seis campos solo dos son
columnas—, y doblarlo con dos interruptores habría tocado el camino por el que pasan las
lecturas de glucosa, que es el que no conviene mover.

Lo que sí se reusa son las piezas: la cuarentena, los motivos legibles y la inserción idempotente
con `ON CONFLICT DO NOTHING`. El `uuid` del teléfono es también el `id` de la sentencia en el
LRS, así que reenviar la cola después de un corte no duplica nada ni aquí ni allá (RF-36c).

## La cuarentena de este endpoint es más estricta

De un renglón rechazado se guardan el `uuid` y la hora, y de lo demás **solo el nombre de la
clave**. En los lotes clínicos se guarda la carga filtrada por columnas, porque ahí son números
y enums; aquí cualquier campo podría traer texto, y la tabla de diagnóstico no debe ser la
puerta de atrás por la que entra una nota.

Se pierde detalle para diagnosticar —el motivo dice qué campo y qué tiene de malo, no el valor— y
se gana que no haya una sola forma de que texto libre del teléfono acabe en el servidor. Hay una
prueba que manda una nota y exige que su contenido no aparezca en ninguna parte de la fila de
cuarentena, y que el nombre de la clave sí, para poder arreglarlo.

## La orden, y por qué no lee los ajustes de la API

```bash
python -m app.lrs              # manda lo que esté pendiente
python -m app.lrs --cuantas    # solo dice cuántas esperan
```

Se programa con `cron`, igual que el pipeline, y **no se corre dentro de `POST /xapi`**: el
teléfono sube su lote en una ventana de wifi y no tiene por qué esperar a que un servidor de
terceros conteste.

La configuración del LRS es un tipo propio, `ConfiguracionLrs`, y no los `Ajustes` de la API.
Los ajustes exigen `GLUCY_JWT_SECRET`, que es lo único sin valor por omisión; pedirle a una orden
que manda sentencias de aprendizaje el secreto que firma los tokens de la API sería obligar a
tener a mano una credencial que no usa.

La orden **termina en 0 aunque el LRS esté caído**. Un `cron` que reporta un error todas las
noches porque un servidor de analítica está apagado es un `cron` que se acaba silenciando, y
entonces no avisa el día que sí importa.

## Pruebas

43 nuevas, de la 305 a la 347, y las 304 anteriores no se tocaron.

El Learning Locker de las pruebas es un **servidor HTTP de verdad** en un puerto libre, no un
parche sobre `httpx.post`. Con un parche, el tope de tiempo nunca se agota y la cabecera
`X-Experience-API-Version` nunca se comprueba, que son las dos cosas que más fallan al integrar
xAPI: sin esa cabecera Learning Locker contesta 400 a todo y el error no dice que falte una
cabecera.

Lo que cubren, por grupos: las tres listas y la idempotencia; los nueve motivos de cuarentena;
que la fila guardada sea la sentencia que se va a mandar, con su actor sin `mbox`, su objeto con
IRI y su `result.duration` en ISO 8601; el cotejo del vocabulario; y la ventana de envío entera
—la ruta, la cabecera, el Basic, el orden de lo más antiguo a lo más reciente, que no se remande
lo que ya salió, el LRS caído, el 401, el 403, el 500, el 503, el lote rechazado que se
reintenta uno por uno, y la fila de otra versión que no tapa la cola—.

## Lo que falta de la fase 6

**El panel de Grafana**, que es el paso 2. Son ocho paneles sobre los agregados ya
precalculados, detrás de autenticación y sin publicarse en internet abierto.

Hay que decir una cosa de entrada: de los ocho, el de **uso del modelo de lenguaje**
—explicaciones, fallos, uso de la plantilla y tiempo medio— **no tiene de dónde leer**. El
servicio de explicación cachea en memoria y no deja rastro en la base, así que ese panel necesita
primero una tabla, o se reporta como no construido. Se decide en el paso 2, con los otros siete
escritos.

## Órdenes para comprobar este paso

```bash
pytest -q                                  # 347 pruebas y 5 saltadas (las de PostgreSQL)
ruff check .
alembic upgrade head                       # llega a la 0004
python -m app.lrs --cuantas                # 0 sentencias esperan en la cola
python -m app.lrs                          # sin GLUCY_LRS_URL: no manda nada y lo dice
```
