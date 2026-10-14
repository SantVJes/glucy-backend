# API

Los siete endpoints con ejemplos de petición y respuesta, errores y límites.
Sale del punto 14 del reporte y de la OpenAPI que genera FastAPI en `/docs`.

| Endpoint | Método | Para qué | Estado |
| --- | --- | --- | --- |
| `/readings` | POST | lote de lecturas de glucosa | **fase 2, paso 1** |
| `/meals` | POST | lote de comidas | paso 2 |
| `/insulin` | POST | lote de dosis | paso 2 |
| `/predict` | GET | predicción a 30 y 60 min y con qué modo respondió | paso 5 |
| `/explain` | POST | explicación en lenguaje natural | paso 6 |
| `/stats` | GET | TIR, promedio, GMI, coeficiente de variación | paso 3 |
| `/history` | GET | histórico para el panel y la exportación | paso 3 |

Además, `GET /salud`, que no es uno de los siete: es para el `healthcheck` del
`docker-compose.yml` del paso 4, devuelve `{"estado": "ok", "version": "…"}` y no toca la base
ni devuelve ningún dato de nadie.

La documentación interactiva vive en `/docs` y el esquema en `/openapi.json`. Es entregable del
punto 14 de la rúbrica (RF-21).

---

## Reglas comunes

### El contrato es snake_case, igual que las columnas

El campo en el JSON, la columna en la base y el atributo del modelo se llaman igual
(decisión 2.1): `uuid`, `mg_dl`, `ts_utc`, `zona_horaria`, `contexto_comida`, `origen`. Del lado
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
