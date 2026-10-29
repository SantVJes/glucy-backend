# Fase 6, paso 2 — el panel de Grafana

Los ocho paneles del §10 del Documento 2, aprovisionados desde el repositorio. Con esto la fase
6 queda cerrada: el paso 1 fue el Learning Record Store
(`docs/fase6-paso-1-learning-record-store.md`) y este es el panel.

La guía de operación —cómo levantarlo, el túnel SSH, qué hay en cada panel— está en
`docs/panel.md`. Este documento es el de las decisiones.

## Qué cambia

- `grafana/consultas/*.sql` — las doce consultas, una por archivo, **comprobadas corriendo**.
- `grafana/armar_tablero.py` — genera `grafana/tableros/glucy.json` desde esas consultas.
- `grafana/provisioning/` — el origen de datos y el proveedor del tablero.
- `grafana/lector.sql` — el usuario de solo lectura de la base.
- `docker-compose.yml` — el servicio `panel`, en `127.0.0.1:3000`.
- `migrations/versions/0005_bitacora_de_explicaciones.py` — la tabla **catorce** (C-13).
- `app/repositories/bitacora.py`, `app/services/explicacion/servicio.py`, `app/routers/explain.py`
  — la bitácora que el panel 8 necesitaba.
- `tests/test_tablero.py` — doce pruebas, una de ellas contra PostgreSQL.

## Lo primero: el panel 8 no tenía de dónde leer

El paso 1 lo dejó dicho. De los ocho paneles pedidos, el de **uso del modelo de lenguaje**
—cuántas explicaciones salieron del modelo, cuántas de la plantilla, cada cuánto falla y cuánto
tarda— no tenía fuente: el servicio de explicación armaba la respuesta, la cacheaba en memoria y
no dejaba rastro. Las opciones eran dos: reportar el panel como no construido, o agregar una
tabla.

Se agregó la tabla, `explicaciones` (**C-13**, la catorce; la trece fue `serie_limpia`, C-9).
Nueve columnas: cuándo, de quién —el UUID seudónimo, lo único que identifica—, si contestó el
modelo o la plantilla, por qué si fue la plantilla, qué modelo, cuánto tardó, el horizonte y el
modo.

**Y lo que no guarda, que es la decisión entera: ni el prompt, ni el texto de la explicación, ni
un solo valor de glucosa, ni las contribuciones SHAP.** Guardar el texto convertiría una bitácora
de operación en un historial clínico, y un historial clínico en una tabla que mira un panel es
justo lo que la regla 3 no quiere. Hay una prueba que escribe una explicación con un 112 y un 74
dentro y comprueba que ninguno de los dos aparece en la fila.

La escritura **no puede tumbar la explicación**: `explicar_y_registrar` atrapa el error de base,
deshace la transacción y devuelve la explicación igual. Es una bitácora, no parte de la función.

### Un error que SQLite habría dejado pasar

`explicaciones.usuario_uuid` es llave foránea a `usuarios`, y la primera versión de
`explicar_y_registrar` no creaba al usuario. **Las pruebas pasaron**: SQLite no exige las llaves
foráneas si no se le enciende el `PRAGMA`. En PostgreSQL habría fallado, y como el servicio
atrapa el error de base para no tumbar la explicación, **lo habría tragado en silencio**: la
explicación saldría bien, el panel estaría siempre vacío, y nada en ningún registro diría por
qué. Se arregló con `asegurar_que_existe` antes de la bitácora, y queda escrito aquí porque la
forma del error —una prueba verde que oculta un fallo de producción— se repite.

## Las consultas se comprobaron corriendo, no leyendo

Doce archivos `.sql`, cada uno corrido contra un **PostgreSQL 16 de verdad** con una base
sembrada: 5 personas, 20 días de serie cada 5 minutos (28 800 filas), los dos agregados, dos
versiones de modelo con sus predicciones y alertas, la cola del LRS en sus tres estados, filas en
cuarentena y la bitácora de explicaciones. Las doce devuelven filas, y las doce se corrieron
**además con el usuario de solo lectura**, que es con el que las correrá Grafana.

Una consulta de panel que nunca se corrió no es una consulta: es una intención. Y un panel roto
no avisa —enseña un rectángulo vacío o un error diminuto en una esquina—, así que la primera vez
que alguien lo mira en serio es el día que lo necesita.

## El hallazgo: la hora del panel 1 estaba mal (C-14)

El panel 1 es «distribución de glucosa por hora del día», y la primera versión leía
`agregados_horarios`, que es lo barato y lo que ya está calculado.

Está mal. `agregados_horarios.periodo` guarda **el inicio de la hora local convertido a UTC**, y
la tabla **no tiene columna de zona**, así que la hora local no se puede recuperar de ahí:
`EXTRACT(HOUR FROM periodo)` devuelve la hora UTC. Para México son seis horas de corrimiento, y
la bajada de las 03:00 de la madrugada aparecería a las 09:00. En el panel cuya pregunta es «¿a
qué hora del día me baja?», y en un proyecto cuyo evento central es la hipoglucemia nocturna, eso
no es un detalle de presentación.

El panel lee `serie_limpia` con `ts_utc AT TIME ZONE zona_horaria`, que es exacto, aguanta zonas
mezcladas y aguanta las de media hora. Queda anotado como **C-14**: cerrarlo del todo pide una
columna `zona_horaria` en los dos agregados, y de paso arreglaría el panel 2, donde con zonas
distintas un mismo día de calendario aparece como puntos separados.

Lo que **no** se hizo: calcular el TIR en SQL. El promedio, el mínimo y el máximo no son reglas
clínicas —lo dice el propio `agregados.py`—, así que sacarlos de la serie no implementa nada de
nuevo. El TIR sí lo es, y el panel 2 lo lee ya calculado: rehacerlo en SQL sería una **cuarta**
implementación de las reglas clínicas, sin nada que la compare con la referencia.

## Las decisiones de cada consulta que no se ven en el SQL

**Un episodio de hipoglucemia es una racha, no una lectura** (panel 3). Dos rachas separadas por
menos de 15 minutos son el mismo episodio, los mismos 15 minutos que usa el pipeline para
interpolar. Sin eso, una glucosa que oscila alrededor de 70 cuenta como seis episodios y el panel
dice que la noche fue seis veces peor de lo que fue. Y no entran las filas **interpoladas**: una
hipoglucemia inventada por una interpolación es el dato que más alarma de todo el tablero.

**El RMSE del modelo y el de la persistencia salen de las mismas predicciones** (panel 4). Un
RMSE suelto no dice nada: 18 mg/dL es bueno o malo según con qué se compare, y la comparación
honesta es «dentro de 30 minutos será igual que ahora». El valor real se busca **por tiempo**,
con 2.5 minutos de tolerancia, nunca por posición: la serie trae huecos (RF-06b), y «la fila más
cercana que haya» compara contra otro momento sin que nada falle. Es la misma regla que fija
`glucy-ml`.

**La tasa de falsas alarmas se calcula solo sobre las alertas con desenlace conocido** (panel 5).
Contar las desconocidas como acertadas bajaría la tasa sin que nada hubiera mejorado, y esa tasa
es criterio de aceptación del proyecto: ≤ 15 %.

**De la cola del LRS, lo que hay que mirar es la pendiente más antigua** (panel 6b), no el número
de pendientes, que sube y baja. Una cola que se vacía con tres días de retraso funciona y a la
vez está mal, y la fecha de la más antigua es lo único que delata un LRS apagado desde el martes.

**Del LRS interesan proporciones, no cuentas** (panel 7b). Contar sentencias por verbo es un
número de actividad; lo que dice algo de autocuidado es: de los avisos que recibió, a cuántos
respondió, y de los módulos que abrió, cuántos terminó. Esas dos son las que van al reporte.

**Los motivos de la plantilla se desglosan porque no son equivalentes** (panel 8b).
`sin_asistente` es la persona que lo apagó y está bien. `sin_respuesta` es Ollama apagado o
pasado de los diez segundos. `cifra_inventada` y `patron_de_dosificacion` son el modelo
portándose mal, y son los dos que hay que mirar: es la validación de la regla 7 haciendo su
trabajo.

## El tablero es código generado, no JSON escrito a mano

`armar_tablero.py` lee los `.sql` y escribe el JSON. El JSON de Grafana es largo y lleno de
campos que no significan nada, y la consulta es lo único que importa de cada panel: en un archivo
`.sql` se lee, se corre contra la base y se revisa en un pull request; pegada dentro del JSON con
los saltos de línea escapados, no se puede hacer ninguna de las tres cosas.

`allowUiUpdates: false` y `editable: false` a propósito: un tablero editado en la interfaz se
pierde con el contenedor y nadie se acuerda de qué decía el panel.

Y una prueba corre `armar_tablero.py --ver`, así que **cambiar un `.sql` sin regenerar el JSON
pone la integración continua en rojo** en lugar de dejar un panel enseñando una consulta vieja.

## Seguridad: las tres que importan, y por qué cada una

1. **`ports: ["127.0.0.1:3000:3000"]`, nunca `"3000:3000"`.** Con lo segundo Docker abre el
   puerto en todas las interfaces y **además atraviesa el cortafuegos del anfitrión sin avisar**,
   porque escribe sus reglas antes que las de `ufw`. El panel quedaría en internet abierto, que
   es justo lo que el Documento 2 prohíbe. Para verlo de fuera, un túnel por SSH.
2. **`GF_SNAPSHOTS_EXTERNAL_ENABLED: "false"`.** Una «instantánea» de Grafana se publica **por
   omisión en un servidor de Grafana Labs**, fuera de este servidor y sin autenticación. Son
   datos de salud aunque estén seudonimizados. Más `GF_AUTH_ANONYMOUS_ENABLED: "false"` y
   `GF_USERS_ALLOW_SIGN_UP: "false"`.
3. **El panel lee con un usuario de solo lectura** (`grafana/lector.sql`), no con el de la
   aplicación. Grafana acepta consultas escritas a mano en su interfaz, y con un usuario que
   puede escribir un `DELETE FROM glucose_readings` queda a una pulsación. Comprobado corriendo:
   el `SELECT` pasa, el `DELETE` da «permission denied for table» y el `CREATE TABLE` da
   «permission denied for schema public».

De `lector.sql`, la parte que se olvida es `ALTER DEFAULT PRIVILEGES`: sin ella, la tabla que
cree la próxima migración no se puede leer y el panel se rompe un mes después, cuando ya nadie
recuerda este archivo.

Ninguna credencial vive en el repositorio: el aprovisionamiento usa `${GLUCY_GRAFANA_DB_...}` y
hay una prueba que recorre los `.yml` y falla si un valor de usuario o contraseña no empieza por
`${`.

## La regla de lectura, dentro del tablero

El Documento 2 pide que **todo panel con pocos usuarios detrás se marque no concluyente**. Está
escrito en un panel de texto arriba del tablero, en grande, y hay una prueba que lo fija: con
pocas personas, lo que se ve describe a quien está usando Glucy, no a quien tiene diabetes
(riesgo R-2). Abajo, el aviso de que Glucy no es un dispositivo médico certificado.

## Pruebas

Doce en `tests/test_tablero.py`, y la mayoría atrapan algo que de otro modo nadie notaría:

- **El JSON está al día** respecto a los `.sql`.
- **Están los ocho paneles** y el aviso de cómo leerlos, y el aviso va arriba (`y == 0`): al
  final nadie lo leería.
- **Ningún panel tapa a otro** en la rejilla. Grafana reacomoda los solapes por su cuenta y el
  tablero deja de parecerse al código.
- **Cada consulta tiene `$__timeFilter`**: sin él el panel ignora el selector de tiempo y lee la
  tabla completa.
- **Ninguna consulta escribe.** El usuario de solo lectura ya lo impediría; esto lo atrapa en la
  revisión, donde cuesta un minuto en lugar de un incidente.
- **Ninguna consulta menciona `nombre`, `peso`, `notas`, `foto` ni `mbox`**, y deja dicho por qué
  no puede: esas columnas no existen en este servidor.
- **El puerto, la autenticación anónima y las instantáneas externas**, los tres sobre el
  `docker-compose.yml`.
- **No sobra ningún `.sql` ni falta ninguno**: el conjunto de consultas en disco es exactamente
  el del tablero.
- Y la marcada **`postgres`: las doce consultas corren contra PostgreSQL migrado**. Basta el
  esquema vacío, porque el motor valida los nombres al planear: es la prueba que atrapa la
  columna renombrada por una migración futura, que es lo que de verdad rompe un panel.

Más cinco en `tests/test_explicacion.py` para la bitácora. Total del repositorio: **363 pruebas
y 6 saltadas**, las de PostgreSQL.

## Una trampa de este repositorio, por si vuelve a morder

**`ruff format .` toca archivos que no debe.** Reformatea los comentarios alineados a mano de
`referencia/reglas_clinicas.py` —que es la referencia compartida con los otros dos
repositorios— y los bloques de código Python dentro de los `.md`. La integración continua solo
corre `ruff check`, así que eso no la pone en rojo, pero mete en el diff seis archivos que no
tienen nada que ver con el cambio. Se formatean los archivos tocados, no el repositorio:
`ruff format app/ tests/ grafana/`.

## Lo que queda de la fase 6, dicho con honestidad

- **Learning Locker no está instalado.** Es software de terceros y se instala en el servidor; el
  código ya habla con él y las pruebas lo hacen contra un servidor HTTP falso que responde como
  Learning Locker. Hasta que exista, las sentencias esperan en la cola, que es el comportamiento
  diseñado y no una falla.
- **El tablero no se ha visto corriendo en Grafana.** Las consultas sí, contra PostgreSQL y con
  el usuario del panel; el JSON se valida con pruebas. Levantar el contenedor y mirarlo con
  datos reales es trabajo de la máquina donde corra el servidor.
- Los paneles 4 y 5 **no tendrán nada que enseñar hasta que haya un modelo entrenado**, que es la
  fase 3 y depende de los datos de OhioT1DM.

## Órdenes para comprobar este paso

```bash
pytest -q                                  # 363 pruebas y 6 saltadas
ruff check .
alembic upgrade head                       # llega a la 0005
python grafana/armar_tablero.py --ver      # el JSON está al día
docker compose up -d panel                 # y http://127.0.0.1:3000
```
