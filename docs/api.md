# API

Los siete endpoints de RF-21 más `POST /perfil`, el octavo, con ejemplos de petición y
respuesta, errores y límites. Sale del punto 14 del reporte y de la OpenAPI que genera FastAPI
en `/docs`.

| Endpoint | Método | Para qué | Estado |
| --- | --- | --- | --- |
| `/readings` | POST | lote de lecturas de glucosa | **fase 2, paso 1** |
| `/meals` | POST | lote de comidas | **fase 2, paso 2** |
| `/insulin` | POST | lote de dosis | **fase 2, paso 2** |
| `/perfil` | POST | los seis parámetros clínicos del perfil (el octavo, C-7) | **fase 2, paso 2** |
| `/predict` | GET | predicción a 30 y 60 min y con qué modo respondió | paso 5 |
| `/explain` | POST | explicación en lenguaje natural | **fase 2, paso 6** |
| `/stats` | GET | TIR, promedio, GMI, coeficiente de variación | **fase 2, paso 3** |
| `/history` | GET | histórico para el panel y la exportación | **fase 2, paso 3** |

**Son ocho, no siete, y es a propósito.** Los parámetros clínicos del perfil —los umbrales y la
duración de acción de la insulina, que el pipeline necesita para el IOB y para derivar la
alerta— no tenían por dónde llegar (C-7). Van en su propio endpoint, con solo esos seis campos,
en lugar de esconderse en `/readings`.

Además, `GET /salud`, que no es uno de los siete: es para el `healthcheck` del
`docker-compose.yml` del paso 4, devuelve `{"estado": "ok", "version": "…"}` y no toca la base
ni devuelve ningún dato de nadie.

La documentación interactiva vive en `/docs` y el esquema en `/openapi.json`. Es entregable del
punto 14 de la rúbrica (RF-21).

---

## Reglas comunes

### El contrato es snake_case, igual que las columnas

El campo en el JSON, la columna en la base y el atributo del modelo se llaman igual
(decisión 2.1 del paso 1): `uuid`, `mg_dl`, `ts_utc`, `zona_horaria`, `contexto_comida`,
`origen`, `carbs_g`, `tiempo_absorcion_min`, `codigo_barras`, `unidades`. Del lado
de iOS sale con `JSONEncoder.KeyEncodingStrategy.convertToSnakeCase`, con **una excepción**:
`LecturaGlucosaDato.contexto` en Swift tiene que llevar la clave explícita `contexto_comida`, o
el servidor lo manda a cuarentena por campo no permitido.

La carga de un renglón son **exactamente las columnas de su tabla destino**. Lo que no es
columna (`nota`, `confianza_ocr`, `atipica`, `sync_estado`…) se queda en el teléfono
(decisión 2.2).

### Autenticación

Todos los endpoints de datos exigen `Authorization: Bearer <jwt>`, firmado con HS256 y
`GLUCY_JWT_SECRET`, con `sub` y `exp` obligatorios. El `sub` es el `usuario_uuid`: el servidor
no sabe quién eres, solo conoce un UUID.

El `usuario_uuid` **sale del token, nunca del cuerpo** (decisión 2.9). Si el cuerpo trae uno
igual al del token, se ignora; si trae uno distinto, el renglón va a cuarentena.

En la fase 2 el servidor **verifica** el token pero todavía no lo emite. Para probar a mano:

```bash
TOKEN=$(python scripts/token-de-prueba.py 11111111-1111-1111-1111-111111111111)
```

Ese script no es un endpoint y no se despliega.

### Los códigos, y qué hace el teléfono con cada uno

| Código | Cuándo | Qué hace el teléfono |
| --- | --- | --- |
| `200` | el lote se procesó, **aunque haya renglones en cuarentena** | marca cada renglón según la lista en la que salió |
| `400` | el sobre no es usable: sin `items`, no es lista, vacío, más de 500 | no reintenta, marca el lote con el motivo |
| `401` | falta el token, no se verifica o está vencido | lo renueva y reintenta **una** vez |
| `5xx` | algo se rompió del lado del servidor | deja el lote en la cola para la siguiente ventana de wifi |

`POST /perfil` cambia en una cosa: contesta **`400` también cuando el objeto no pasa las
reglas**, no solo cuando el cuerpo está roto, porque no hay más renglones que salvar. Ver su
apartado.

**El `409` no se usa en los lotes.** Un uuid repetido no es un conflicto: es un duplicado y
sale en su lista con un `200`. El `409` se reserva para un conflicto de verdad, si algún día el
teléfono intentara cambiar algo de lo que el backend es autoridad.

### El sobre y los renglones (decisión 2.5)

El **sobre** se valida por esquema: `{"items": [...]}` con entre 1 y 500 renglones. Si no es
usable es `400` y no se escribe nada en ninguna tabla.

**Cada renglón se valida por su cuenta.** Lo que falla va a `cuarentena` con su motivo y los
demás se aceptan. Un renglón al que le falta `mg_dl` es un renglón en cuarentena, no un `400`
de todo el lote: el teléfono necesita distinguir «no me entendiste» de «este dato no me gustó».

### La respuesta de los lotes

Siempre con las tres listas, y cada renglón enviado sale en **exactamente una**:

```json
{
  "aceptados": ["6f3a1b2c-0000-4000-8000-000000000001"],
  "duplicados": [],
  "cuarentena": [
    {"uuid": "6f3a1b2c-0000-4000-8000-000000000002",
     "motivo": "fuera del rango fisiológico 20-600 mg/dL"}
  ]
}
```

`cuarentena` lleva el **motivo**, no solo el uuid (RF-22). `uuid` es `null` cuando el renglón
ni siquiera traía un uuid legible.

---

## `POST /readings`

Sube un lote de lecturas de glucosa a `glucose_readings`.

### Petición

```http
POST /readings
Authorization: Bearer <jwt>
Content-Type: application/json

{ "items": [
    { "uuid": "6f3a1b2c-0000-4000-8000-000000000001",
      "ts_utc": "2026-10-13T14:32:00Z",
      "zona_horaria": "America/Monterrey",
      "mg_dl": 112,
      "origen": "foto_glucometro",
      "contexto_comida": "antes_de_comer" }
] }
```

| Campo | Tipo | Obligatorio | Regla |
| --- | --- | --- | --- |
| `uuid` | UUID | sí | lo genera el teléfono; es la llave de idempotencia (RF-36c) |
| `ts_utc` | ISO 8601 | sí | **con offset** (`Z` o `±hh:mm`) y no futura (decisión 2.10, RF-22) |
| `zona_horaria` | texto | sí | nombre IANA que se pueda resolver, p. ej. `America/Monterrey` |
| `mg_dl` | número | sí | 20–600, ambos inclusive (RF-05, RF-22) |
| `origen` | enum | sí | `sensor` · `manual` · `foto_glucometro` · `barcode` · `ocr_etiqueta` · `healthkit` |
| `contexto_comida` | enum | no | `en_ayunas` · `antes_de_comer` · `dos_horas_despues` · `antes_de_dormir` · `otro` |

Cualquier otro campo manda el renglón a cuarentena (`extra="forbid"`).

### Respuesta

`200` con las tres listas. Ejemplo real del mismo `curl` dos veces:

```json
{"aceptados":["6f3a1b2c-0000-4000-8000-000000000001"],"duplicados":[],"cuarentena":[]}
{"aceptados":[],"duplicados":["6f3a1b2c-0000-4000-8000-000000000001"],"cuarentena":[]}
```

### Qué va a cuarentena, y en qué orden se comprueba

1. El renglón no cumple el esquema: falta un campo, sobra uno (`nota`), `ts_utc` sin offset, un
   `origen` que no existe, un `uuid` ilegible.
2. Trae un `usuario_uuid` distinto del token.
3. `zona_horaria` no se puede resolver.
4. `validar_lectura` de `referencia/reglas_clinicas.py` lo rechaza: fuera de 20–600 mg/dL o con
   marca de tiempo futura. La validación **se importa de la referencia**, no se reimplementa
   (decisión 2.3).

Lo que sobrevive se inserta; los uuid que ya existían salen en `duplicados`. La idempotencia es
una restricción de la base (`UNIQUE` + `ON CONFLICT DO NOTHING` + `RETURNING`), no un `SELECT`
previo.

**Limitación conocida (C-8):** `glucose_readings` no guarda si la persona confirmó un valor
leído por OCR, así que el servidor no puede volver a comprobarlo y llama a `validar_lectura` con
`confirmada_por_usuario=True`. La garantía de P-01 vive en el teléfono, donde nada se guarda sin
confirmar.

### Límites

- A lo más **500** renglones por lote.
- El primer lote de un `usuario_uuid` crea su fila en `usuarios`, con `uuid` y `ts_alta` y nada
  más (decisión 2.7).
- Este endpoint guarda lo que llega; no limpia la señal ni calcula nada. Eso es el pipeline del
  paso 4.

### Prueba a mano

```bash
rm -f glucy.db && alembic upgrade head
export GLUCY_JWT_SECRET=…            # el que esté en tu .env, nunca en el repositorio
uvicorn app.main:app --reload
TOKEN=$(python scripts/token-de-prueba.py 11111111-1111-1111-1111-111111111111)
curl -s -X POST http://127.0.0.1:8000/readings \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"items":[{"uuid":"6f3a1b2c-0000-4000-8000-000000000001",
                 "ts_utc":"2026-10-13T14:32:00Z","zona_horaria":"America/Monterrey",
                 "mg_dl":112,"origen":"manual"}]}'
```

La primera vez contesta `aceptados`; la segunda, el mismo comando, `duplicados`, sin crear una
segunda fila.

---

## `POST /meals`

Sube un lote de comidas a `meals`. Mismo sobre, mismas tres listas y mismos códigos que
`/readings`; el reparto es la misma función (`ingerir`) con otro descriptor de lote.

### Petición

```http
POST /meals
Authorization: Bearer <jwt>
Content-Type: application/json

{ "items": [
    { "uuid": "…", "ts_utc": "2026-10-24T13:10:00Z",
      "zona_horaria": "America/Monterrey", "carbs_g": 60,
      "tiempo_absorcion_min": 180, "porciones": 1,
      "codigo_barras": "7501055300014", "origen": "barcode" }
] }
```

| Campo | Tipo | Obligatorio | Regla |
| --- | --- | --- | --- |
| `uuid` | UUID | sí | lo genera el teléfono; llave de idempotencia |
| `ts_utc` | ISO 8601 | sí | con offset y no futura |
| `zona_horaria` | texto | sí | nombre IANA que se pueda resolver |
| `carbs_g` | número | sí | 0–300 g, ambos inclusive. **Gramos totales, ya multiplicados por las porciones** |
| `origen` | enum | sí | los mismos seis de `/readings`; en la práctica `manual`, `barcode` u `ocr_etiqueta` |
| `tiempo_absorcion_min` | entero | no | 30–300; si falta, **180** (D-8) |
| `porciones` | número | no | mayor que cero; si falta, **1**. Solo informativo |
| `codigo_barras` | texto | no | |
| `proteina_g`, `grasa_g`, `fibra_g` | número | no | se aceptan, pero **en la fase 2 siempre llegan nulas**: la app no las captura |

**`carbs_g` ya es el total.** En la app, `Carbohidratos` lo calcula como
`carbsPor100g / 100 × porcionG × porciones`, y `porciones` viaja aparte solo como información.
Si el servidor volviera a multiplicar, el COB del pipeline saldría al doble o al triple.

`descripcion`, `nombre_producto`, `porcion_g`, `confirmada_por_usuario`,
`escrita_en_health_kit` y `nota` **no suben**: mandan el renglón a cuarentena y de ellos solo
queda el nombre de la clave en `claves_descartadas`.

### Qué va a cuarentena, y en qué orden

Los mismos pasos que `/readings` (esquema, `usuario_uuid` ajeno, zona horaria) y después
`validar_comida` de la referencia, que comprueba en el orden del Swift:

1. `carbs_g` fuera de 0–300 g.
2. `tiempo_absorcion_min` fuera de 30–300 min.
3. `porciones` no mayor que cero.
4. Marca de tiempo futura.

---

## `POST /insulin`

Sube un lote de dosis a `insulin_doses`. Son dosis que la persona **dice haberse aplicado**: se
registran y nunca se calcula ni se sugiere una (regla 7, RF-14).

### Petición

```http
POST /insulin
Authorization: Bearer <jwt>
Content-Type: application/json

{ "items": [
    { "uuid": "…", "ts_utc": "2026-10-24T13:12:00Z",
      "zona_horaria": "America/Monterrey", "unidades": 6.5,
      "tipo": "bolo", "motivo": "comida" }
] }
```

| Campo | Tipo | Obligatorio | Regla |
| --- | --- | --- | --- |
| `uuid` | UUID | sí | lo genera el teléfono; llave de idempotencia |
| `ts_utc` | ISO 8601 | sí | con offset y no futura |
| `zona_horaria` | texto | sí | nombre IANA que se pueda resolver |
| `unidades` | número | sí | mayor que 0, a lo más 50 UI, múltiplo de 0.5 |
| `tipo` | enum | sí | `bolo` · `basal`. Nunca «rápida»: es una etiqueta de la interfaz (C-4) |
| `motivo` | enum | no | `comida` · `correccion` · `programada`. Nulo si la persona no lo dijo; no se adivina |

**No existe ningún campo de relación insulina/carbohidratos ni de factor de sensibilidad**, ni
aquí ni en ningún otro endpoint (regla 7, C-2). Si llegara uno, el renglón va a cuarentena.

### Qué va a cuarentena, y en qué orden

Los mismos pasos que `/readings` y después `validar_dosis` de la referencia, en el orden del
Swift:

1. `unidades` no mayor que cero: cero no es una dosis, es un campo sin llenar.
2. `unidades` por encima de 50 UI.
3. `unidades` que no son múltiplo de 0.5, la resolución de la pluma (2.3 no pasa, 2.5 sí).
4. Marca de tiempo futura.

Se valida que la dosis sea **anotable**, no que sea la adecuada: eso sería dosificar.

---

## `POST /perfil`

El octavo endpoint. Guarda en `usuarios` los seis parámetros clínicos que el pipeline necesita.
**No es un lote**: es un solo objeto, y es un *upsert*.

### Petición

```http
POST /perfil
Authorization: Bearer <jwt>
Content-Type: application/json

{ "tipo_usuario": "tipo1", "anio_nacimiento": 2001, "umbral_hipo": 70,
  "umbral_hiper": 180, "tipo_insulina_rapida": "lispro",
  "duracion_accion_insulina": 5 }
```

| Campo | Tipo | Obligatorio | Regla |
| --- | --- | --- | --- |
| `tipo_usuario` | enum | sí | `tipo1` · `tipo2_insulinodependiente` · `prediabetes` · `resistencia_insulina` (los cuatro, C-3) |
| `anio_nacimiento` | entero | sí | el año solo; da una edad de 15 a 120 años |
| `umbral_hipo` | número | sí | 50–90 mg/dL |
| `umbral_hiper` | número | sí | 140–300 mg/dL |
| `tipo_insulina_rapida` | texto | no | a lo más 40 caracteres; nulo en quien no se aplica insulina |
| `duracion_accion_insulina` | número | sí | 2–8 h |

**Lo interesante es lo que no acepta.** `nombre`, `apellidos`, `peso_kg`, `nota` o cualquier
otro campo son un `400` con un motivo legible, no un campo que se ignora en silencio
(`extra="forbid"`). La regla 3 deja de depender de que la app se porte bien.

La validación es `validar_perfil` de la referencia, en el orden del Swift: año de nacimiento
(no futuro, edad mínima, edad máxima), umbral de hipo, umbral de hiper, largo del tipo de
insulina, duración de acción. La firma de `validar_perfil` no tiene parámetros para nombre,
apellidos ni peso.

### Respuesta

`200` con los seis valores **tal como quedaron guardados**, leídos de la base, para que el
teléfono confirme contra lo que mandó y no contra lo que creía haber mandado:

```json
{"tipo_usuario":"tipo1","anio_nacimiento":2001,"umbral_hipo":70.0,"umbral_hiper":180.0,
 "tipo_insulina_rapida":"lispro","duracion_accion_insulina":5.0}
```

El segundo envío **actualiza**, no duplica ni contesta `duplicados`: el teléfono es la
autoridad sobre su perfil. `ts_alta` no cambia nunca, tampoco si el usuario nació antes en un
lote.

### Cuando no pasa: `400` y cuarentena

```json
400 {"detail": "nombre: no se acepta en el perfil: lo que identifica a la persona no sube (regla 3)"}
400 {"detail": "umbral de hipoglucemia fuera del rango 50-90 mg/dL"}
```

En un lote, un renglón malo va a cuarentena y los demás se aceptan, así que `200` es lo
correcto. Aquí **no hay «los demás»**: si el único objeto no pasa, no se guardó nada, y el
teléfono tiene que saber que no reintente igual. Por eso `400`.

Y además queda una fila en `cuarentena` con `tabla_destino = "usuarios"`, porque un `400` solo
vive en el teléfono y RF-22 dice que nada se descarta en silencio. La carga se filtra por las
columnas de `usuarios`: un `nombre` que llegue por error deja **el nombre de la clave** en
`claves_descartadas` y su contenido en ninguna parte de la base.

### Prueba a mano

```bash
TOKEN=$(python scripts/token-de-prueba.py 11111111-1111-1111-1111-111111111111)
curl -s -X POST localhost:8000/perfil -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"tipo_usuario":"tipo1","anio_nacimiento":2001,"umbral_hipo":70,"umbral_hiper":180,
       "tipo_insulina_rapida":"lispro","duracion_accion_insulina":5}'
# con "nombre":"…" en el cuerpo, el mismo comando contesta 400
```

---

## Las consultas: reglas comunes de `GET /history` y `GET /stats`

### Nadie ve la serie de otra persona

Toda consulta se filtra por el `usuario_uuid` **del token**, en el repositorio, como primer
parámetro obligatorio de cada función (decisión 2.1 del paso 3). **Ningún endpoint de lectura
acepta un `usuario_uuid`** ni otro parámetro que cambie de quién son los datos: cualquier
parámetro desconocido, `usuario_uuid` incluido, es un `400`.

### El periodo

| Parámetro | Obligatorio | Regla |
| --- | --- | --- |
| `desde` | sí | ISO 8601 **con offset**. Entra en el periodo |
| `hasta` | sí | ISO 8601 **con offset**. No entra: el periodo es `[desde, hasta)` |

- `desde` tiene que ser anterior a `hasta`, y el periodo no puede pasar de **90 días** (la app
  pide 7, 14 y 30).
- Un `hasta` en el futuro se acepta y no devuelve nada de más.
- En una URL, el `+` de un offset se lee como espacio: usa `Z`, o escribe el `+` como `%2B`.

### Los códigos

| Código | Cuándo |
| --- | --- |
| `200` | siempre que la consulta se entendió, **también si no hay ningún dato** |
| `400` | falta `desde` o `hasta`, una fecha sin offset, `desde >= hasta`, más de 90 días, un `limite` fuera de 1–1000, un `que` o un `cursor` que no se entienden, o un parámetro desconocido |
| `401` | falta el token, no se verifica o está vencido |

**No hay `404`** (decisión 2.9). Un usuario sin datos, o que no existe, recibe series vacías e
`indicadores: null`: para quien consulta, «no tengo datos tuyos» y «no existes» son lo mismo, y
distinguirlas le diría a un tercero con un token válido si un UUID está dado de alta.

**Los `GET` no escriben nada**: no crean el usuario, no tocan `cuarentena` y no leen ni llenan
las tablas de agregados, que siguen vacías hasta el paso 4.

---

## `GET /stats`

Los indicadores del periodo: TIR, TBR, TAR, promedio, desviación, coeficiente de variación y
GMI. **Los calcula `indicadores()` de `referencia/reglas_clinicas.py`**; el servidor no calcula
ninguno por su cuenta.

```http
GET /stats?desde=2026-10-01T00:00:00Z&hasta=2026-10-24T00:00:00Z
Authorization: Bearer <jwt>
```

```json
{ "desde": "2026-10-01T00:00:00Z", "hasta": "2026-10-24T00:00:00Z",
  "dias_con_lecturas": 21,
  "indicadores": { "n": 1843, "promedio": 142.7, "desviacion": 48.2,
                   "coeficiente_variacion": 33.8, "tir": 68.4, "tbr": 3.1,
                   "tar": 28.5, "gmi": 6.72 },
  "umbrales_del_perfil": true, "umbral_hipo": 70.0, "umbral_hiper": 180.0 }
```

### Cuándo se enseña cada cifra

| Días con lecturas | `indicadores` | `gmi` |
| --- | --- | --- |
| menos de 3 | `null`: faltan datos, **no un cero** | — |
| de 3 a 13 | todos | `null` |
| 14 o más | todos | el valor |

Las dos puertas son `hay_suficientes_dias` y `gmi_es_fiable` de la referencia, con los mismos
valores que `ConfiguracionDominio.diasMinimosIndicadores` y `.diasMinimosGmi` en Swift.

**Los días se cuentan por el día local de cada lectura**, con la `zona_horaria` guardada en su
propia fila, igual que `DiaTipico.diaLocal` en el teléfono. Una lectura de las 19:00 en
Monterrey es la 01:00 UTC del día siguiente; contada en UTC caería en otro día, y como los días
deciden si las cifras se enseñan, el teléfono y el panel dirían cosas distintas con la misma
base. Una zona ilegible se cuenta en UTC, como hace el Swift.

### Los umbrales

El TIR es siempre sobre 70–180. El TBR y el TAR usan los umbrales del perfil
(`POST /perfil`). Si el perfil no ha llegado se usan los de omisión, 70 y 180, **y se dice**:
`umbrales_del_perfil: false`. Sin ese campo, un TBR calculado con 70 cuando la persona tiene su
umbral en 80 se vería idéntico a uno correcto.

---

## `GET /history`

Las lecturas, comidas y dosis del periodo, paginadas por cursor.

```http
GET /history?desde=2026-10-01T00:00:00Z&hasta=2026-10-24T00:00:00Z&que=lecturas,dosis&limite=200
Authorization: Bearer <jwt>
```

| Parámetro | Obligatorio | Regla |
| --- | --- | --- |
| `desde`, `hasta` | sí | ver arriba |
| `que` | no | `lecturas`, `comidas`, `dosis`, o varias separadas por coma. Por omisión, las tres |
| `limite` | no | renglones por página, contando las tres series: 1–1000, por omisión 200 |
| `cursor` | no | el `siguiente` de la página anterior, **tal cual** |

```json
{ "lecturas": [ { "uuid": "…", "ts_utc": "2026-10-23T22:00:00Z",
                  "zona_horaria": "America/Monterrey", "mg_dl": 112.0,
                  "origen": "sensor", "contexto_comida": "antes_de_comer" } ],
  "comidas": [],
  "dosis": [ { "uuid": "…", "ts_utc": "2026-10-23T22:05:00Z",
               "zona_horaria": "America/Monterrey", "unidades": 6.5,
               "tipo": "bolo", "motivo": "comida" } ],
  "siguiente": "eyJ0cyI6…" }
```

**Cada renglón tiene exactamente los campos que se aceptaron al subir**, con los mismos
nombres: los de `POST /readings`, `POST /meals` y `POST /insulin`. Ni `usuario_uuid`, ni nota,
ni nombre, ni foto: el servidor no los tiene, y un campo de más sería un dato inventado. No
incluye `cuarentena`: lo rechazado se consulta en el panel del paso 4.

Las fechas salen en ISO 8601 con `Z`, y cada renglón trae su `zona_horaria` original.

Las series que no se piden en `que` vienen vacías y **no se consultan**.

### La paginación

Por **cursor**, no por `offset` (decisión 2.6): mientras alguien pagina el teléfono sigue
subiendo lotes, y con `offset` eso repite o se salta renglones sin que nadie lo note.

- Las series pedidas se mezclan en un solo orden, `ts_utc` ascendente con `uuid` para
  desempatar, y `limite` cuenta el total de renglones de la página.
- `siguiente` es el `(ts_utc, uuid)` del último renglón devuelto, codificado. Es opaco: se
  manda de vuelta tal cual como `cursor`, con los mismos `desde`, `hasta` y `que`.
- **`siguiente: null` es el fin.** No lo es «vino menos de `limite`»: con un límite exacto la
  última página trae `limite` renglones legítimamente.
- Una lectura que llega a la mitad con una hora anterior al cursor no aparece en las páginas
  siguientes y no desplaza nada; sale en la próxima consulta desde el principio.

### Prueba a mano: el token B no ve nada de A

```bash
A=$(python scripts/token-de-prueba.py 11111111-1111-1111-1111-111111111111)
B=$(python scripts/token-de-prueba.py 22222222-2222-2222-2222-222222222222)
# sube una lectura con A, y después:
curl -s "localhost:8000/history?desde=2026-10-01T00:00:00Z&hasta=2026-11-01T00:00:00Z" \
  -H "Authorization: Bearer $B"
# {"lecturas":[],"comidas":[],"dosis":[],"siguiente":null}
```

---

## `POST /explain`

La explicación en lenguaje natural de una predicción (RF-28, punto 11 de la rúbrica). Es la
**única** pieza del sistema que habla con un modelo de lenguaje, y la app no sabe qué modelo hay
del otro lado: cambiarlo no toca ni una línea de Swift.

**Siempre responde `200` con una explicación.** Si el modelo de lenguaje no contesta en 10
segundos, si inventa una cifra, si insinúa un tratamiento o si la persona apagó el asistente,
sale la **plantilla determinista** y `origen` lo dice (P-13). La función no depende de que una
computadora ajena esté encendida.

### Petición

El cuerpo lleva la predicción y sus valores SHAP, porque `predictions` no tiene columna para las
contribuciones: el teléfono manda lo que `/predict` le devolvió.

```json
{
  "valor_actual": 112,
  "valor_predicho": 74,
  "horizonte_min": 30,
  "modo": "sensor",
  "umbral_hipo": 70,
  "umbral_hiper": 180,
  "cob_g": 12,
  "iob_ui": 2.5,
  "hora_local": 3,
  "shap": [
    {"variable": "insulina que sigue activa", "mg_dl": -20},
    {"variable": "tendencia de la última media hora", "mg_dl": -10},
    {"variable": "carbohidratos que siguen activos", "mg_dl": -8}
  ],
  "asistente_activo": true
}
```

**Qué se envía y qué no.** Eso es todo lo que el modelo de lenguaje ve: glucosa actual y
predicha, horizonte y modo, umbrales, COB e IOB del momento, hora del día y las cinco
contribuciones más grandes. **Nunca** el nombre, los apellidos, el `usuario_uuid`, las notas,
las fotografías, el peso, el año de nacimiento, la ubicación ni el historial. Con
`extra="forbid"`, si la app mandara uno de esos campos la respuesta es `400` con el motivo, no
un campo que se ignora en silencio y acaba en el prompt.

`asistente_activo` lo manda el teléfono en cada petición porque la preferencia es del teléfono
(regla 1): el servidor no guarda si la persona apagó el asistente.

### Respuesta

```json
{
  "explicacion": "Vas a bajar en la próxima media hora, sobre todo porque la insulina que te aplicaste sigue activa. Es una estimación: conviene confirmarla con una medición.",
  "origen": "modelo",
  "motivo": null,
  "modelo": "qwen3:8b"
}
```

Con la plantilla:

```json
{
  "explicacion": "Baja sobre todo por insulina que sigue activa (-20 mg/dL) y por tendencia de la última media hora (-10 mg/dL). Es una estimación: conviene confirmar con una medición antes de actuar.",
  "origen": "plantilla",
  "motivo": "sin_respuesta",
  "modelo": null
}
```

`motivo` es uno de tres: `sin_asistente` (apagado, o sin Ollama configurado), `sin_respuesta`
(se pasó del tope o contestó un error) y `no_paso_validacion`.

### Cómo se revisa la respuesta antes de mostrarla

Lo que no pasa estas dos comprobaciones **se descarta**; no se corrige ni se recorta.

1. **Ninguna indicación de tratamiento.** Es la regla 7, y se revisa primero porque es la que
   puede lastimar a alguien: cualquier «ponte», «aplícate», «toma», «come», «corrige», «bolo»,
   «basal», «debes», «necesitas», «UI» o «unidades de insulina» bloquea la respuesta. «Sube» y
   «baja» **no** bloquean —la explicación habla justo de eso— pero «sube la dosis» sí.
2. **Ninguna cifra que no viniera en la petición.** Se comparan las magnitudes, porque una
   contribución de −20 mg/dL se puede redactar como «quita 20 mg/dL» y el signo lo llevan las
   palabras. Un 68 que nadie dio, o un 112 redondeado a 110, bloquean la respuesta.

Se falla cerrado a propósito: un falso positivo cuesta una frase menos natural, y un falso
negativo es una app no certificada insinuando un tratamiento.

### Determinismo y caché

Temperatura 0, semilla fija y tope de 160 fichas: la misma predicción produce siempre la misma
explicación, así que se puede revisar y citar. La caché es en memoria del proceso, con tope de
512 entradas, y su llave son los valores redondeados **sin nada de quién preguntó**: dos
personas con los mismos números comparten entrada, y la caché no guarda nada de nadie.

### Configuración

```
GLUCY_OLLAMA_URL=            # vacío = siempre la plantilla, y la app funciona igual
GLUCY_OLLAMA_MODELO=qwen3:8b
GLUCY_EXPLICACION_TIMEOUT_S=10
```

### Prueba a mano, sin Ollama

```bash
# Sin GLUCY_OLLAMA_URL, el endpoint contesta con la plantilla y nunca sale a la red.
T=$(python scripts/token-de-prueba.py 11111111-1111-1111-1111-111111111111)
curl -s localhost:8000/explain -H "Authorization: Bearer $T" \
  -H 'Content-Type: application/json' -d '{
    "valor_actual": 112, "valor_predicho": 74, "horizonte_min": 30, "modo": "sensor",
    "umbral_hipo": 70, "umbral_hiper": 180, "cob_g": 12, "iob_ui": 2.5, "hora_local": 3,
    "shap": [{"variable": "insulina que sigue activa", "mg_dl": -20}]}'
```
