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

### Quién escribe cada tabla

Flujo en un solo sentido por tipo de dato: nunca compiten dos autoridades por el mismo campo.

| Tabla | Autoridad | La escribe | Desde |
| --- | --- | --- | --- |
| `usuarios` | teléfono | el primer lote de cada `usuario_uuid` | paso 1 |
| `glucose_readings` | teléfono | `POST /readings` | paso 1 |
| `cuarentena` | backend | cualquier lote, con lo que no pasó la validación | paso 1 |
| `meals` | teléfono | `POST /meals` | paso 2 |
| `insulin_doses` | teléfono | `POST /insulin` | paso 2 |
| `context_events` | teléfono | por definir | — |
| `predictions` | backend | servicio de predicción | paso 5 |
| `alerts` | backend | derivadas de las predicciones | paso 5 |
| `modelos` | backend | el artefacto que deja `glucy-ml` | paso 5 |
| `agregados_horarios` | backend | pipeline | paso 4 |
| `agregados_diarios` | backend | pipeline | paso 4 |
| `xapi_events` | backend | registro para Learning Locker | por definir |

### Las que usa el paso 1

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
| `ts_alta` | fecha y hora | no | primer lote recibido |

**Sin nombre, sin apellidos, sin peso, sin correo.** No es un olvido (regla 3).

La fila nace en el primer lote que llega con ese UUID, con `uuid` y `ts_alta` y todo lo demás
nulo (decisión 2.7). Los seis parámetros clínicos no tienen todavía por dónde llegar: es la
contradicción **C-7**, que se resuelve en el paso 2 con una carga reducida del perfil.

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
| `tabla_destino` | texto | no | p. ej. `glucose_readings` |
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

### Las otras nueve

Creadas con las columnas que les da el Documento 3, todas nulas salvo las claves, hasta que su
paso las llene.

- **`meals`**: `uuid` (PK), `usuario_uuid` (FK), `ts_utc`, `zona_horaria`, `carbs_g`,
  `tiempo_absorcion_min`, `proteina_g`, `grasa_g`, `fibra_g`, `codigo_barras`, `porciones`,
  `origen`. **`proteina_g`, `grasa_g` y `fibra_g` siempre son nulas en la fase 2**: la app de la
  fase 1 no las captura (decisión 2.2). La columna existe porque el Documento 3 la fija, que es
  distinto de no tenerla.
- **`insulin_doses`**: `uuid` (PK), `usuario_uuid` (FK), `ts_utc`, `zona_horaria`, `unidades`,
  `tipo`, `motivo`. Guarda lo que la persona registró; el sistema **jamás calcula ni sugiere una
  dosis**.
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
