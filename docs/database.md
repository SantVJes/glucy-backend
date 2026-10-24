# Base de datos

Las tablas del teléfono y del servidor, y el grupo que nunca sale del
dispositivo. Sale del Documento 3 y del punto 9 del reporte.

## Grupo A, en el teléfono (SwiftData y HealthKit)

Diez tablas. Viven en `glucy-ios` y se documentan allá. El teléfono es el **dueño del dato**:
este servidor es una copia para analítica y para el modelo, nunca la fuente.

## Grupo B, en el backend

Doce tablas, creadas todas en la migración `0001` de Alembic aunque el paso 1 solo escriba en
tres (decisión 2.4). Los nombres están fijados en el Documento 3 y **no se traducen ni se
renombran**, aunque estén en dos idiomas.

### Motor

**SQLite** para arrancar (D-4), en el archivo `glucy.db`. PostgreSQL 16 con TimescaleDB llega
en el paso 4, cuando haya volumen y pipeline que justifiquen las series de tiempo. Hasta
entonces nada fuera de `app/repositories/` supone extensiones de Timescale, y lo específico de
SQLite (`ON CONFLICT DO NOTHING` con `RETURNING`) vive solo ahí.

```bash
rm -f glucy.db && alembic upgrade head    # crea las doce desde cero
```

Las marcas de tiempo se guardan en UTC. La zona local de cada registro viaja aparte, en
`zona_horaria`, porque la hora local es lo que alimenta `hora_sin` y `hora_cos` en la fase 3.

### Las fechas: `FechaUtc`

Las trece columnas de fecha de las doce tablas usan `FechaUtc`, un `TypeDecorator` propio en
`app/models/tipos.py` (decisión 2.1 del paso 2):

- **Al guardar**, convierte a UTC. Una fecha **sin zona no se guarda**: levanta un error en el
  código en lugar de suponer UTC, que acertaría casi siempre y desplazaría la serie el resto de
  las veces sin que nada falle.
- **Al leer**, devuelve el `datetime` **con `tzinfo` UTC**.

Hace falta porque SQLite devuelve las fechas sin zona aunque la columna sea
`DateTime(timezone=True)`, y comparar eso con `datetime.now(UTC)` levanta `TypeError`. No
rompía nada mientras solo se escribía; habría tronado en el primer `GET` del paso 3.

**No lleva migración**: el tipo solo cambia el procesado del lado de Python, y en SQLite el DDL
sigue siendo `DATETIME`. `alembic check` no detecta diferencias entre `0001` y los modelos.

### Quién escribe cada tabla

Flujo en un solo sentido por tipo de dato: nunca compiten dos autoridades por el mismo campo.

| Tabla | Autoridad | La escribe | Desde |
| --- | --- | --- | --- |
| `usuarios` | teléfono | nace con el primer lote de cada `usuario_uuid`; los seis parámetros clínicos, `POST /perfil` | pasos 1 y 2 |
| `glucose_readings` | teléfono | `POST /readings` | paso 1 |
| `cuarentena` | backend | cualquier lote o perfil, con lo que no pasó la validación | paso 1 |
| `meals` | teléfono | `POST /meals` | paso 2 |
| `insulin_doses` | teléfono | `POST /insulin` | paso 2 |
| `context_events` | teléfono | por definir | — |
| `predictions` | backend | servicio de predicción | paso 5 |
| `alerts` | backend | derivadas de las predicciones | paso 5 |
| `modelos` | backend | el artefacto que deja `glucy-ml` | paso 5 |
| `agregados_horarios` | backend | pipeline | paso 4 |
| `agregados_diarios` | backend | pipeline | paso 4 |
| `xapi_events` | backend | registro para Learning Locker | por definir |

### Las que usan los pasos 1 y 2

#### `usuarios`

| Columna | Tipo | Nula | Nota |
| --- | --- | --- | --- |
| `uuid` | UUID | no | PK. Es el `sub` del token |
| `tipo_usuario` | texto | sí | |
| `anio_nacimiento` | entero | sí | |
| `umbral_hipo` | real | sí | |
| `umbral_hiper` | real | sí | |
| `tipo_insulina_rapida` | texto | sí | |
| `duracion_accion_insulina` | real | sí | horas |
| `ts_alta` | fecha y hora | no | primer contacto, por lote o por perfil. No vuelve a cambiar |

**Sin nombre, sin apellidos, sin peso, sin correo.** No es un olvido (regla 3).

La fila nace en el primer contacto con ese UUID (decisión 2.7 del paso 1). Si es un lote, nace
con `uuid` y `ts_alta` y todo lo demás nulo. Los seis parámetros clínicos llegan por
`POST /perfil` (paso 2, **C-7 cerrado**), que es un *upsert*: el segundo envío actualiza los
seis y no toca `ts_alta`.

`tipo_usuario` admite `tipo1`, `tipo2_insulinodependiente`, `prediabetes` y
`resistencia_insulina` (C-3). No hay columna ni campo de relación insulina/carbohidratos ni de
factor de sensibilidad (regla 7).

#### `glucose_readings`

| Columna | Tipo | Nula | Nota |
| --- | --- | --- | --- |
| `uuid` | UUID | no | PK, y por eso `UNIQUE`: la llave de idempotencia (RF-36c). La genera el teléfono |
| `usuario_uuid` | UUID | no | FK a `usuarios.uuid`, con índice. Sale del token, nunca del cuerpo |
| `ts_utc` | fecha y hora | no | en UTC, con índice |
| `zona_horaria` | texto | no | nombre IANA que se pudo resolver |
| `mg_dl` | real | no | 20–600 |
| `contexto_comida` | texto | sí | `en_ayunas` · `antes_de_comer` · `dos_horas_despues` · `antes_de_dormir` · `otro` |
| `origen` | texto | no | `sensor` · `manual` · `foto_glucometro` · `barcode` · `ocr_etiqueta` · `healthkit` |

Sin la nota (regla 3). Tampoco suben `confianza_ocr`, `atipica`, `fue_corregido`,
`confirmada_por_usuario` ni `sync_estado`: la carga de un lote son exactamente las columnas de
su tabla (decisión 2.2). `atipica` la recalcula el pipeline del paso 4.

#### `cuarentena`

| Columna | Tipo | Nula | Nota |
| --- | --- | --- | --- |
| `id` | entero | no | PK autoincremental |
| `ts_recepcion` | fecha y hora | no | cuándo llegó el renglón |
| `tabla_destino` | texto | no | `glucose_readings`, `meals`, `insulin_doses` o `usuarios` |
| `carga_original` | JSON | no | el renglón tal como llegó, **solo con las claves que son columnas** |
| `claves_descartadas` | JSON | no | **añadido, no está en el Documento 3**; ver abajo |
| `motivo_rechazo` | texto | no | por qué no pasó |

Lo que no pasa la validación **nunca se descarta en silencio**: va aquí con su motivo y su
carga (RF-22, P-05, P-06).

**`claves_descartadas` es la única columna que no está en el Documento 3**, y entra por la
decisión 2.6. Si una versión de la app manda una `nota` por error, guardar el renglón entero
metería texto libre en el servidor por la puerta de atrás de una tabla de diagnóstico, que es
justo lo que la regla 3 prohíbe. Así que `carga_original` se filtra por los nombres de las
columnas de la tabla destino, y de lo que se descartó solo se guarda **el nombre** de la clave:
da el diagnóstico («llegó una `nota`, arréglalo en la app») sin guardar el contenido.

Un perfil rechazado también deja aquí su fila, con `tabla_destino = "usuarios"` y la carga
filtrada por las columnas de `usuarios`: un `nombre` enviado por error deja el nombre de la
clave y no su contenido (decisión 2.8 del paso 2).

#### `meals`

| Columna | Tipo | Nula | Nota |
| --- | --- | --- | --- |
| `uuid` | UUID | no | PK, llave de idempotencia. La genera el teléfono |
| `usuario_uuid` | UUID | no | FK a `usuarios.uuid`, con índice. Sale del token |
| `ts_utc` | fecha y hora | sí\* | en UTC, con índice |
| `zona_horaria` | texto | sí\* | nombre IANA que se pudo resolver |
| `carbs_g` | real | sí\* | 0–300. **Gramos totales**, ya multiplicados por las porciones |
| `tiempo_absorcion_min` | entero | sí\* | 30–300; 180 si el teléfono no lo manda (D-8) |
| `proteina_g` | real | sí | **siempre nula en la fase 2** |
| `grasa_g` | real | sí | **siempre nula en la fase 2** |
| `fibra_g` | real | sí | **siempre nula en la fase 2** |
| `codigo_barras` | texto | sí | |
| `porciones` | real | sí\* | mayor que cero; 1 si no se manda. Solo informativo: no se multiplica |
| `origen` | texto | sí\* | los mismos valores que en `glucose_readings` |

\* La columna admite nulos desde la migración `0001`, pero `POST /meals` siempre la llena:
el esquema de entrada la exige o le pone su valor por omisión.

`proteina_g`, `grasa_g` y `fibra_g` existen porque el Documento 3 las fija, y la app de la
fase 1 no las captura (decisión 2.2 del paso 1). Se aceptan igual en la entrada, para que el día
que la app las capture el servidor no cambie. Que la columna exista y esté nula es distinto de
no tenerla.

No suben `descripcion`, `nombre_producto`, `porcion_g`, `confirmada_por_usuario`,
`escrita_en_health_kit` ni `nota`.

#### `insulin_doses`

| Columna | Tipo | Nula | Nota |
| --- | --- | --- | --- |
| `uuid` | UUID | no | PK, llave de idempotencia. La genera el teléfono |
| `usuario_uuid` | UUID | no | FK a `usuarios.uuid`, con índice. Sale del token |
| `ts_utc` | fecha y hora | sí\* | en UTC, con índice |
| `zona_horaria` | texto | sí\* | nombre IANA que se pudo resolver |
| `unidades` | real | sí\* | mayor que 0, a lo más 50, múltiplo de 0.5 |
| `tipo` | texto | sí\* | `bolo` · `basal` (C-4) |
| `motivo` | texto | sí | `comida` · `correccion` · `programada`, o nulo si la persona no lo dijo |

\* Igual que en `meals`: nula en el DDL, siempre llena por `POST /insulin`.

Guarda lo que la persona registró. El sistema **jamás calcula ni sugiere una dosis**, y no hay
columna de relación insulina/carbohidratos ni de factor de sensibilidad.

### Las otras siete

Creadas con las columnas que les da el Documento 3, todas nulas salvo las claves, hasta que su
paso las llene.

- **`context_events`**: `uuid` (PK), `usuario_uuid` (FK), `ts_inicio`, `ts_fin`, `clase`,
  `intensidad`, `calidad`, `origen`.
- **`predictions`**: `uuid` (PK), `usuario_uuid` (FK), `ts_utc`, `horizonte_min`,
  `valor_predicho`, `modo`, `modelo_version`, `confianza`.
- **`alerts`**: `uuid` (PK), `usuario_uuid` (FK), `prediccion_uuid` (FK a `predictions`),
  `ts_emision`, `tipo`, `ts_respuesta`, `accion`, `resulto_real`.
- **`modelos`**: `version` (PK), `algoritmo`, `horizonte`, `fecha_entrenamiento`, `rmse`, `mae`,
  `mard`, `clarke_ab`, `ruta_artefacto`.
- **`agregados_horarios`** y **`agregados_diarios`**: `usuario_uuid` y `periodo` (PK compuesta),
  `promedio`, `minimo`, `maximo`, `desviacion`, `tir`, `tbr`, `tar`, `gmi`. Sobre SQLite son
  tablas normales y vacías; en el paso 4 pasan a *continuous aggregates* de TimescaleDB.
- **`xapi_events`**: `uuid` (PK), `usuario_uuid` (FK), `ts_utc`, `actor`, `verbo`, `objeto`,
  `resultado` (los tres últimos en JSON, como los define xAPI 1.0.3).

## Grupo C, lo que nunca sale del teléfono

Nombre y apellidos, peso, notas de texto libre, fotografías y la caché de productos. Ninguna
tabla del grupo B tiene columna para ellos, y un renglón que los traiga va a cuarentena sin
que su contenido se guarde (decisión 2.6).
