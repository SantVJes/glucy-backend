# Paso 1 de la fase 2 — La base de datos y el primer endpoint

Escrito el 13 de octubre de 2026, el mismo día en que `main` de `glucy-ios` quedó en `v0.1.0`
con la app funcionando sola. Este es el primer paso de la fase 2.

Lee antes `CLAUDE.md` de este repositorio y `referencia/reglas_clinicas.py`. Son los dos
archivos que mandan sobre todo lo que sigue.

---

## 0. Antes de abrir Claude Code

### 0.1 La rama, antes que nada

```bash
cd glucy-backend
git checkout develop
git pull origin develop
git checkout -b feature/base-de-datos-y-readings
```

**La rama sale de `develop` y el pull request va contra `develop`.** No contra `main`.

### 0.2 Qué hay ya en el repositorio, para no volver a escribirlo

La fase 0 dejó esto, y funciona:

- `referencia/reglas_clinicas.py` con **379 líneas** y `tests/test_reglas_clinicas.py` con
  **30 pruebas pasando**. Ahí viven la validación, COB, IOB, los indicadores, las zonas de
  Clarke y la plantilla de explicación.
- `.github/workflows/ci.yml`, que corre `ruff check .` y `pytest` en cada pull request.
- `.env.example` con los **nombres** de las variables y ningún valor.
- `pyproject.toml` con ruff (línea de 100) y pytest (`pythonpath = ["."]`, `testpaths = ["tests"]`).
- `docs/` con seis archivos de la fase 0, casi vacíos y marcados «pendiente de llenar».
- `.github/pull_request_template.md`, que es el que hay que llenar.

### 0.3 Lo que hace falta instalar, y lo que no

Hace falta: `fastapi`, `uvicorn`, `pydantic-settings`, `sqlalchemy`, `alembic`.

**No hace falta Docker ni PostgreSQL todavía.** D-4 dice SQLite para arrancar, y este paso
corre entero con un archivo `glucy.db` y nada más. PostgreSQL con TimescaleDB y
`docker-compose.yml` llegan en el paso 4, cuando haya volumen y pipeline que justifiquen las
series de tiempo. Arrancar con Docker hoy es media tarde de configuración para un repositorio
que todavía no tiene ni un endpoint.

---

## 1. El orden de la fase 2, y por qué este paso va primero

Siete pasos, en este orden. Cada uno es un pull request.

| Paso | Qué construye | Por qué va ahí |
| --- | --- | --- |
| **1** | **esqueleto de `app/`, las doce tablas, el token y `POST /readings` completo** | la glucosa es el dato del que dependen todos los demás, y el patrón de validación, cuarentena e idempotencia que inventa este paso lo copian los otros dos lotes |
| 2 | `POST /meals`, `POST /insulin` y la carga reducida del perfil | el mismo patrón, dos veces más, sin inventar nada |
| 3 | `GET /history` y `GET /stats` | ya hay datos que leer, y los indicadores salen de la referencia |
| 4 | PostgreSQL con TimescaleDB, `docker-compose.yml` y el pipeline de limpieza y características (RF-23, RF-24) | aquí sí hacen falta las series de tiempo, y el pipeline necesita datos acumulados |
| 5 | `GET /predict` con el artefacto en memoria y su latencia < 200 ms | depende de que la fase 3 haya producido un artefacto |
| 6 | `POST /explain` con Ollama y la plantilla determinista | depende de que haya predicciones con valores SHAP |
| 7 | la cola de sincronización del teléfono contra el backend de verdad | va en `glucy-ios`, no aquí, y cierra la fase |

Este paso va primero porque **todo lo demás lo hereda**: el reparto en tres listas, la tabla
`cuarentena`, la forma del token y la decisión de cómo viajan los nombres de los campos.
Equivocarse aquí se paga tres veces.

## 1 bis. Los requisitos, pegados

No los resumo. Esto es lo que dicen.

### RF-21, los siete endpoints

> `/readings` POST sube un lote de lecturas de glucosa · `/meals` POST sube un lote de
> comidas · `/insulin` POST sube un lote de dosis · `/predict` GET predicción a 30 y 60 min
> **y con qué modo respondió** · `/explain` POST explicación en lenguaje natural de una
> predicción · `/stats` GET TIR, promedio, GMI, coeficiente de variación del periodo ·
> `/history` GET histórico para el panel y la exportación.
>
> Documentación **OpenAPI** generada por FastAPI, publicada en `/docs`. Es entregable del
> punto 14 de la rúbrica.

### RF-22, validación y cuarentena

> Las mismas reglas que en el teléfono, otra vez aquí, **porque un servidor nunca debe confiar
> en lo que le mandan**: rango 20–600 mg/dL, marcas de tiempo en UTC y no futuras, unicidad
> por UUID, carbohidratos 0–300 g, insulina 0–50 UI, absorción 30–300 min.
>
> Lo que no pasa **va a `cuarentena` con su motivo y su carga original. Nunca se descarta en
> silencio**: un dato rechazado sin dejar rastro es una falla invisible (casos P-06 y P-05).

### La idempotencia, y de quién es el UUID (RF-36c)

> **Idempotencia:** el UUID lo genera el teléfono. El mismo UUID dos veces no duplica: se
> devuelve en `duplicados` y la app lo marca como confirmado (RF-36c). Un `UNIQUE` sobre
> `uuid` más `ON CONFLICT DO NOTHING` es suficiente; lo importante es la respuesta.

### Los códigos de error, y qué hace la app con cada uno

> `400` esquema inválido, el lote no se reintenta y queda marcado con el motivo · `401` token
> vencido, la app lo renueva y reintenta **una** vez · `409` conflicto, se trata como
> duplicado · `5xx` o red caída, el lote se queda en la cola y se reintenta en la siguiente
> ventana de wifi.

### La regla que ordena todo lo demás

> **El teléfono es el dueño del dato. Este servidor es una copia para analítica y para el
> modelo, nunca la fuente.** Y una cuarta que es de seguridad: **el servidor no sabe quién
> eres.** Solo conoce un UUID. Sin nombre, sin apellidos, sin peso, sin correo, sin notas, sin
> fotografías.

---

## 2. Las diez decisiones del paso 1

Cada una resuelve algo que el documento de especificación deja abierto o se contradice. Están
aquí para que no se vuelvan a discutir en el paso 2.

### 2.1 El contrato de la red es snake_case, idéntico al nombre de las columnas

El documento de especificación tiene un ejemplo de petición que **no coincide con su propia
tabla**:

```http
POST /readings
{ "items": [ { "id": "6f3a…", "valor_mgdl": 112, "timestamp": "2026-09-18T14:32:00Z", … } ] }
```

La tabla `glucose_readings` del Documento 3, en cambio, tiene `uuid`, `mg_dl`, `ts_utc`,
`zona_horaria`, `contexto_comida`, `origen` y `usuario_uuid`.

**Gana la tabla.** Los nombres de las tablas y de sus columnas están fijados en el Documento 3
y no se traducen ni se renombran; el ejemplo es ilustrativo y se escribió antes. Así que
`id` → `uuid`, `valor_mgdl` → `mg_dl`, `timestamp` → `ts_utc`, y `confianza_ocr` desaparece
(ver 2.2).

La ventaja práctica es grande: **el campo en el JSON, la columna en la base y el atributo del
modelo se llaman igual**, así que no hay tres vocabularios que mantener sincronizados. Y del
lado de iOS sale casi gratis: los `Dato` de Swift son camelCase (`mgDl`, `tsUtc`,
`zonaHoraria`, `carbsG`, `tiempoAbsorcionMin`, `codigoBarras`) y
`JSONEncoder.KeyEncodingStrategy.convertToSnakeCase` los convierte exactamente en `mg_dl`,
`ts_utc`, `zona_horaria`, `carbs_g`, `tiempo_absorcion_min` y `codigo_barras`. Un solo ajuste
del codificador y no hay que escribir ni un `CodingKeys`.

**Con una excepción, y conviene verla ahora y no en el paso 7:** en Swift el campo se llama
`LecturaGlucosaDato.contexto`, a secas, y la columna es `contexto_comida`. La conversión
automática lo dejaría en `contexto` y el servidor lo rechazaría por `extra="forbid"` sin que
nada más falle. **Ese es el único campo de los tres lotes que necesita una clave explícita**,
y el paso 7 tiene que ponerla. Del lado del servidor no se cambia nada: la columna del
Documento 3 es `contexto_comida` y así se queda.

Los valores de los enums **ya coinciden** y no hay que tocarlos: en Swift `Origen` es
`sensor · manual · foto_glucometro · barcode · ocr_etiqueta · healthkit` y `ContextoComida` es
`en_ayunas · antes_de_comer · dos_horas_despues · antes_de_dormir · otro`. Son las mismas
cadenas que la `StrEnum Origen` de `referencia/reglas_clinicas.py`. **No se inventen variantes
en inglés.**

### 2.2 Lo que sube es exactamente las columnas de la tabla, y nada más

El `LecturaGlucosaDato` del teléfono tiene dieciséis campos. La tabla del servidor tiene
siete. Los nueve que faltan **no suben**, y hay una regla para no volver a decidirlo caso por
caso:

> **La carga de un lote son exactamente las columnas de su tabla destino. Lo que no es columna
> se queda en el teléfono.**

Se queda, entonces: `nota` (lo prohíbe la regla 3), `valor_leido_ocr`, `fue_corregido`,
`confianza_ocr`, `atipica`, `confirmada_por_usuario`, `escrita_en_health_kit`, `sync_estado`,
`descripcion` y `nombre_producto` de las comidas.

Por qué está bien que se queden:

- `confianza_ocr` **no decide nada** (D-11), así que no es un dato del que el modelo pueda
  aprender; y `origen = foto_glucometro` ya dice todo lo que la fase 3 necesita para desglosar
  el error por origen, que es el desglose que de verdad importa (riesgo R-2).
- `atipica` lo **recalcula** el pipeline con `es_atipica_por_tasa`, y una marca que viene de
  fuera y no se puede comprobar es peor que ninguna.
- `sync_estado` es del teléfono por definición: es su memoria de qué ya mandó.
- `escrita_en_health_kit` solo le sirve al teléfono para no reescribir lo del sensor (RF-15b).

Y las columnas que el teléfono **no puede llenar** viajan nulas, sin dejar de existir:
`meals` tiene `proteina_g`, `grasa_g` y `fibra_g`, que la app de la fase 1 no captura. La
columna se queda (el Documento 3 la fija) y se documenta que en la fase 2 siempre es nula. Eso
es distinto de borrarla, y la diferencia importa cuando alguien lea el esquema en el reporte.

### 2.3 La validación no se reimplementa: se importa de la referencia

`referencia/reglas_clinicas.py` ya tiene `validar_lectura(mg_dl, ts_utc, ahora, origen,
confirmada_por_usuario) -> Rechazo | None`, con 30 pruebas pasando. El servicio de ingesta
**la importa**:

```python
from referencia.reglas_clinicas import Origen, Rechazo, validar_lectura
```

No se copia ni se traduce. El CLAUDE.md dice que el pipeline tiene que dar los mismos números
que esa referencia; **importarla lo vuelve cierto por construcción en lugar de cierto por
prueba**, y una prueba que compara dos copias de la misma lógica solo demuestra que se
copiaron bien el día que se escribió.

El riesgo de importarla hay que decirlo: si la referencia tiene un error, lo tienen las dos.
Lo que lo compensa es que **la app de iOS es una tercera implementación independiente** —
`Validacion.swift`, escrita en Swift sin mirar el Python — y las tres tienen que coincidir. Un
error en la referencia se vería como un desacuerdo con Swift, que es exactamente la alarma que
el CLAUDE.md pide vigilar.

### 2.4 Las doce tablas se crean de una vez, y sobre SQLite

Las doce, en la migración `0001`, aunque este paso solo escriba en tres. El esquema está
especificado completo en el Documento 3, es DDL y no cuesta nada; lo que sí cuesta es una
migración por paso y siete oportunidades de que dos de ellas no se puedan aplicar en orden.
Es lo mismo que se hizo en iOS, donde el paso 1 creó los diez `@Model` de golpe.

`agregados_horarios` y `agregados_diarios` se crean como **tablas normales**. En PostgreSQL
van a ser *continuous aggregates* de TimescaleDB, pero eso es del paso 4; mientras tanto son
tablas vacías, y el CLAUDE.md ya manda que nada fuera de `repositories/` suponga que existen
extensiones de Timescale.

### 2.5 El esquema es del sobre; las reglas son de cada renglón

Esta es la decisión que más cambia el comportamiento, así que va con su historia de fallo.

Si `items` se declara como `list[LecturaEntrada]`, Pydantic valida el lote entero antes de que
corra una sola línea del servicio: **un renglón con un campo mal escrito tira las quinientas
lecturas con un 422**, y el teléfono marca el lote como fallido y no reintenta (es un `400` de
los suyos). Una semana de glucosa perdida por un campo.

Así que el reparto es:

- **El sobre se valida por esquema.** `{"items": [...]}` con una lista no vacía y a lo más 500
  elementos. Si el sobre no es usable —falta `items`, no es una lista, viene vacía, trae más de
  500— es **`400`** y no se escribe nada en ninguna tabla.
- **Cada renglón se valida por su cuenta**, dentro del servicio, a partir de un `dict`. Lo que
  falla va a `cuarentena` con su motivo, **y los demás renglones se aceptan**. El código de la
  respuesta es `200` aunque haya renglones en cuarentena: el lote se procesó, y lo que pasó con
  cada renglón está en las tres listas.

Un renglón al que le falta `mg_dl` es entonces **un renglón en cuarentena**, no un `400` de
todo el lote. Suena a contradicción con «`400` esquema inválido» y no lo es: el esquema que el
`400` nombra es el del sobre, y el teléfono necesita poder distinguir «no me entendiste» de
«este dato no me gustó».

### 2.6 La cuarentena guarda la carga original, filtrada por el nombre de las columnas

`cuarentena` tiene `carga_original`, y ahí va el renglón **tal como llegó**, en JSON. Con un
cuidado: se guardan solo las claves que son columnas de la tabla destino, y **los nombres de
las que se descartaron** se anotan aparte.

Por qué no se guarda el renglón entero: si un día una versión de la app manda `nota` por error,
guardar la carga completa metería una nota de texto libre en el servidor, que es justo lo que
la regla 3 prohíbe, y por la puerta de atrás de una tabla de diagnóstico. Guardar los nombres
de las claves descartadas da el diagnóstico («llegó una `nota`, arréglalo en la app») sin
guardar el contenido.

### 2.7 El usuario nace en su primer contacto

**La especificación no tiene endpoint para crear un usuario.** Los siete son los siete, y
`usuarios` dice «escribe la app al activar la sincronización», pero por dónde no está dicho.

Decisión: **el `sub` del token es el `usuario_uuid`, y la fila de `usuarios` se crea en el
primer lote que llegue con ese UUID**, con `uuid` y `ts_alta` llenos y todo lo demás nulo. Una
lectura nunca se queda sin dueño y no hace falta un endpoint nuevo.

Lo que queda pendiente de verdad, y hay que anotarlo: los parámetros clínicos del perfil
—`umbral_hipo`, `umbral_hiper`, `tipo_insulina_rapida`, `duracion_accion_insulina`,
`tipo_usuario`, `anio_nacimiento`— los **necesita** el pipeline para el IOB y para derivar la
alerta, y hoy no tienen por dónde llegar. Eso es el paso 2 (apartado 9).

### 2.8 El token se comprueba desde el primer endpoint, pero todavía no se emite

Un `POST` abierto en un repositorio público es una mala costumbre que después nadie quita. Así
que desde este paso el endpoint exige `Authorization: Bearer <jwt>`, firmado con HS256 y
`GLUCY_JWT_SECRET`, y devuelve **`401`** si falta, si no se puede verificar o si está vencido.

Lo que **no** entra todavía: emitirlo, rotarlo y la pantalla de la app que lo guarda en el
Keychain. Para las pruebas y para probar a mano, un script corto en `scripts/token-de-prueba.py`
que firma un token con el `sub` que se le pase. **Ese script no es un endpoint y no se despliega.**

### 2.9 El `usuario_uuid` sale del token, nunca del cuerpo

Si el cuerpo trae un `usuario_uuid` igual al del token, se ignora. Si trae uno **distinto**, el
renglón va a cuarentena con ese motivo. Podría ser un error de la app, pero también es la forma
exacta que tendría un intento de escribir en la serie de otra persona, y eso no se descarta en
silencio: se guarda con su motivo para que se vea en el panel del paso 4.

### 2.10 Las marcas de tiempo tienen que traer su offset

`ts_utc` sin zona —`"2026-10-13T14:32:00"`, sin `Z` ni `+00:00`— va a **cuarentena**. Suponer
UTC sería correcto el 90 % de las veces y desplazaría la serie seis horas el 10 % restante, sin
que nada falle y sin que nadie lo note hasta que las métricas salgan raras.

El teléfono siempre manda con offset: en Swift, un `Date` codificado con
`.iso8601` sale con `Z`. Y `zona_horaria` se comprueba resolviéndola con `ZoneInfo`; una zona
que no se puede resolver hace que la hora local sea irrecuperable, y la hora local es lo que
alimenta `hora_sin` y `hora_cos` en la fase 3.

---

## 3. Archivos que hay que crear

```
requirements.txt                 fastapi, uvicorn, pydantic-settings, sqlalchemy, alembic
app/__init__.py
app/main.py                      crea la FastAPI, monta el router, expone /salud
app/config.py                    Ajustes con pydantic-settings, prefijo GLUCY_
app/seguridad.py                 usuario_del_token: verifica el JWT y devuelve el UUID
app/db/__init__.py
app/db/sesion.py                 engine, SessionLocal, la dependencia de sesión
app/models/__init__.py
app/models/tablas.py             las DOCE tablas con SQLAlchemy 2.0 (Mapped/mapped_column)
app/schemas/__init__.py
app/schemas/lotes.py             LoteCrudo, RespuestaLote, RenglonEnCuarentena
app/schemas/lecturas.py          LecturaEntrada (la que valida UN renglón)
app/repositories/__init__.py
app/repositories/lecturas.py     insertar_ignorando_duplicados
app/repositories/cuarentena.py   guardar
app/repositories/usuarios.py     asegurar_que_existe
app/services/__init__.py
app/services/ingesta.py          el reparto en tres listas; aquí vive la regla, no en el router
app/routers/__init__.py
app/routers/readings.py          POST /readings
alembic.ini
migrations/env.py
migrations/versions/0001_esquema_inicial.py
scripts/token-de-prueba.py
tests/test_readings.py
tests/test_esquema.py
```

Y hay que **llenar** `docs/api.md` y `docs/database.md`, que la fase 0 dejó con «pendiente de
llenar». Son entregables del punto 14 de la rúbrica, no un extra.

`referencia/` **no se toca**. Es la referencia; si hay que cambiarla es porque se encontró un
error en ella, y eso es un pull request aparte con su discusión.

---

## 4. Las firmas, exactas

### `app/config.py`

```python
class Ajustes(BaseSettings):
    """Lee el entorno. Ningún valor por omisión que sea un secreto."""

    model_config = SettingsConfigDict(env_prefix="GLUCY_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./glucy.db"
    jwt_secret: str                      # sin valor por omisión: si falta, la app no arranca
    jwt_minutos_vigencia: int = 15


@lru_cache
def ajustes() -> Ajustes: ...
```

`jwt_secret` **no lleva valor por omisión a propósito**: un secreto con valor por omisión acaba
en producción. Que la aplicación se niegue a arrancar sin él es la única garantía que funciona.

### `app/seguridad.py`

```python
def usuario_del_token(
    credenciales: Annotated[HTTPAuthorizationCredentials, Depends(HTTPBearer())],
) -> UUID:
    """Devuelve el `usuario_uuid` del `sub`, o levanta 401.

    Un 401 significa para la app «renueva el token y reintenta UNA vez» (RF-21), así que no se
    usa para nada más: un dato que no gusta es cuarentena, no 401.
    """
```

### `app/schemas/lotes.py`

```python
class LoteCrudo(BaseModel):
    """El sobre, y solo el sobre. Los renglones llegan como dict y se validan uno por uno
    dentro del servicio, para que un renglón malo no tire el lote entero (decisión 2.5).
    """
    items: list[dict] = Field(min_length=1, max_length=500)


class RenglonEnCuarentena(BaseModel):
    uuid: UUID | None          # None cuando el renglón ni siquiera traía un uuid legible
    motivo: str


class RespuestaLote(BaseModel):
    aceptados: list[UUID]
    duplicados: list[UUID]
    cuarentena: list[RenglonEnCuarentena]
```

**`cuarentena` lleva el motivo, no solo el uuid.** El ejemplo de la especificación muestra una
lista de identificadores, y se cambia a propósito: RF-22 obliga a conservar el motivo, y si la
respuesta no lo trae, el teléfono tiene que preguntar al servidor qué pasó con un dato que él
mismo mandó. No hay costo de compatibilidad porque la cola del teléfono se escribe en el paso 7.

### `app/schemas/lecturas.py`

```python
class LecturaEntrada(BaseModel):
    """Un renglón de `POST /readings`. Son exactamente las columnas de `glucose_readings`
    que el teléfono llena; `usuario_uuid` sale del token (decisión 2.9).
    """
    model_config = ConfigDict(extra="forbid")

    uuid: UUID
    ts_utc: AwareDatetime          # con offset obligatorio (decisión 2.10)
    zona_horaria: str
    mg_dl: float
    origen: Origen                 # el StrEnum de referencia/reglas_clinicas.py
    contexto_comida: ContextoComida | None = None
```

`extra="forbid"` es lo que convierte una `nota` que llegue de más en un renglón en cuarentena
con un motivo legible, en lugar de en un campo que se ignora sin que nadie se entere.

### `app/services/ingesta.py`

```python
@dataclass(frozen=True)
class Resultado:
    aceptados: list[UUID]
    duplicados: list[UUID]
    cuarentena: list[RenglonEnCuarentena]


def ingerir_lecturas(
    sesion: Session, usuario_uuid: UUID, renglones: list[dict], ahora: datetime
) -> Resultado:
    """Reparte un lote en aceptados, duplicados y cuarentena. Aquí vive la regla.

    `ahora` entra como parámetro y no se lee de dentro: una prueba de marca de tiempo futura
    necesita poder fijar el presente.
    """
```

El orden dentro de la función, que es el del pipeline del CLAUDE.md:

1. `asegurar_que_existe(sesion, usuario_uuid)` — decisión 2.7.
2. Por cada renglón: `LecturaEntrada.model_validate(renglon)`. Si levanta, **cuarentena** con
   el mensaje de Pydantic como motivo.
3. `usuario_uuid` del cuerpo distinto del del token → **cuarentena** (decisión 2.9).
4. `ZoneInfo(zona_horaria)` — si levanta, **cuarentena**.
5. `validar_lectura(mg_dl, ts_utc, ahora, origen)` de la referencia. Si devuelve `Rechazo`,
   **cuarentena** con `rechazo.motivo`.
6. Lo que sobrevive se inserta con `insertar_ignorando_duplicados`, que devuelve qué uuid
   entraron de verdad. Los que no entraron son **duplicados**.

### `app/repositories/lecturas.py`

```python
def insertar_ignorando_duplicados(
    sesion: Session, filas: list[dict]
) -> list[UUID]:
    """Inserta y devuelve solo los uuid que de verdad entraron.

    La idempotencia es una restricción de la base, no un SELECT previo: dos lotes iguales que
    llegan a la vez pasarían los dos el SELECT y duplicarían (RF-36c). `UNIQUE` sobre `uuid`
    más `ON CONFLICT DO NOTHING`, y la lista de los que entraron sale del `RETURNING`.
    """
```

En SQLAlchemy 2.0 es `sqlalchemy.dialects.sqlite.insert(...).on_conflict_do_nothing(index_elements=["uuid"]).returning(Tabla.uuid)`.
Eso es específico de SQLite, **y por eso vive en `repositories/` y en ningún otro sitio**: en el
paso 4 cambia a `dialects.postgresql` y no se toca ninguna otra capa.

### Las doce tablas, campo por campo

Las que este paso usa, completas:

```python
class Usuario(Base):                      # usuarios
    uuid: Mapped[UUID] = mapped_column(primary_key=True)
    tipo_usuario: Mapped[str | None]
    anio_nacimiento: Mapped[int | None]
    umbral_hipo: Mapped[float | None]
    umbral_hiper: Mapped[float | None]
    tipo_insulina_rapida: Mapped[str | None]
    duracion_accion_insulina: Mapped[float | None]
    ts_alta: Mapped[datetime]
    # Sin nombre, sin apellidos, sin peso, sin correo. No es un olvido (regla 3).


class LecturaGlucosa(Base):               # glucose_readings
    uuid: Mapped[UUID] = mapped_column(primary_key=True)      # UNIQUE por ser PK
    usuario_uuid: Mapped[UUID] = mapped_column(ForeignKey("usuarios.uuid"), index=True)
    ts_utc: Mapped[datetime] = mapped_column(index=True)
    zona_horaria: Mapped[str]
    mg_dl: Mapped[float]
    contexto_comida: Mapped[str | None]
    origen: Mapped[str]
    # Sin la nota (regla 3).


class Cuarentena(Base):                   # cuarentena
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts_recepcion: Mapped[datetime]
    tabla_destino: Mapped[str]
    carga_original: Mapped[dict] = mapped_column(JSON)
    claves_descartadas: Mapped[list[str]] = mapped_column(JSON, default=list)
    motivo_rechazo: Mapped[str]
```

`claves_descartadas` es la única columna que **no** está en el Documento 3, y entra por la
decisión 2.6. Hay que anotarlo en `docs/database.md` como añadido con su razón, no colarlo.

Las otras nueve se crean con las columnas que el Documento 3 les da, todas nulas salvo las
claves:

- `meals`: `uuid`, `usuario_uuid`, `ts_utc`, `zona_horaria`, `carbs_g`, `tiempo_absorcion_min`,
  `proteina_g`, `grasa_g`, `fibra_g`, `codigo_barras`, `porciones`, `origen`.
- `insulin_doses`: `uuid`, `usuario_uuid`, `ts_utc`, `zona_horaria`, `unidades`, `tipo`, `motivo`.
- `context_events`: `uuid`, `usuario_uuid`, `ts_inicio`, `ts_fin`, `clase`, `intensidad`,
  `calidad`, `origen`.
- `predictions`: `uuid`, `usuario_uuid`, `ts_utc`, `horizonte_min`, `valor_predicho`, `modo`,
  `modelo_version`, `confianza`.
- `alerts`: `uuid`, `usuario_uuid`, `prediccion_uuid`, `ts_emision`, `tipo`, `ts_respuesta`,
  `accion`, `resulto_real`.
- `modelos`: `version`, `algoritmo`, `horizonte`, `fecha_entrenamiento`, `rmse`, `mae`, `mard`,
  `clarke_ab`, `ruta_artefacto`.
- `agregados_horarios` y `agregados_diarios`: `usuario_uuid`, `periodo`, `promedio`, `minimo`,
  `maximo`, `desviacion`, `tir`, `tbr`, `tar`, `gmi`.
- `xapi_events`: `uuid`, `usuario_uuid`, `ts_utc`, `actor`, `verbo`, `objeto`, `resultado`.

**`proteina_g`, `grasa_g` y `fibra_g` se quedan y siempre serán nulas en la fase 2**: la app de
la fase 1 no captura esos tres (decisión 2.2). Es distinto de no tenerlas.

---

## 5. El endpoint, de arriba abajo

```
POST /readings
Authorization: Bearer <jwt>
Content-Type: application/json

{ "items": [
    { "uuid": "6f3a1b2c-…", "ts_utc": "2026-10-13T14:32:00Z",
      "zona_horaria": "America/Monterrey", "mg_dl": 112,
      "origen": "foto_glucometro", "contexto_comida": "antes_de_comer" }
] }
```

```json
200 OK
{ "aceptados": ["6f3a1b2c-…"], "duplicados": [], "cuarentena": [] }
```

Los cuatro códigos, y nada más:

| Código | Cuándo | Qué hace el teléfono |
| --- | --- | --- |
| `200` | el lote se procesó, aunque haya renglones en cuarentena | marca cada renglón según la lista en la que salió |
| `400` | el sobre no es usable: sin `items`, no es lista, vacía, más de 500 | no reintenta, marca el lote con el motivo |
| `401` | falta el token, no se verifica o está vencido | lo renueva y reintenta **una** vez |
| `5xx` | algo se rompió del lado del servidor | deja el lote en la cola para la siguiente ventana de wifi |

**El `409` de la especificación no se usa en este endpoint**, y hay que decirlo: un uuid
repetido no es un conflicto, es un duplicado, y sale en su lista con un `200`. Reservar el
`409` para un conflicto de verdad —si algún día el teléfono intentara cambiar algo de lo que el
backend es autoridad— es más útil que gastarlo en el caso normal de un reintento.

El router hace tres cosas y ninguna más: depende de `usuario_del_token`, valida el sobre con
`LoteCrudo`, llama a `ingerir_lecturas` y devuelve. **Ni una consulta, ni una regla.**

`GET /salud` devuelve `{"estado": "ok"}` y la versión. No es uno de los siete: es para el
`healthcheck` del `docker-compose.yml` del paso 4, y no toca la base ni devuelve ningún dato
de nadie.

---

## 6. Lo que este paso NO construye, y no es por falta de tiempo

- **No emite tokens.** Solo los verifica (decisión 2.8).
- **No hay PostgreSQL, ni TimescaleDB, ni Docker.** D-4, y el paso 4.
- **No hay pipeline**: ni suavizado, ni interpolación, ni características, ni COB, ni IOB. Este
  paso guarda lo que llega; limpiarlo es el paso 4.
- **No hay predicción ni explicación.** Pasos 5 y 6.
- **No se escribe nada en la app de iOS.** La cola de sincronización del teléfono es el paso 7,
  y hasta entonces este endpoint se prueba con `pytest` y con `curl`.
- **No se infiere ninguna comida** a partir de que la glucosa suba (RF-37, D-9). No en este
  paso, ni en ninguno.
- **No se calcula ni se sugiere ninguna dosis.** Ni aquí ni nunca (regla 7).

---

## 7. Las pruebas que tienen que pasar

Catorce, numeradas, y cada una apunta a su requisito. En `tests/test_readings.py` salvo la 14.

1. **Un lote de tres lecturas válidas** → `200`, los tres uuid en `aceptados`, tres filas en
   `glucose_readings` y ninguna en `cuarentena`.
2. **P-05, idempotencia.** El mismo lote otra vez → `200`, los tres en `duplicados`, y
   `SELECT count(*)` **no cambió**. La cuenta antes y después es la afirmación, no la respuesta.
3. **P-06, cuarentena.** Una marca de tiempo una hora en el futuro → `200`, el uuid en
   `cuarentena` con su motivo, y una fila en `cuarentena` con `tabla_destino = "glucose_readings"`
   y su carga original.
4. **P-02 del lado del servidor.** 900 mg/dL → cuarentena, y el motivo nombra el rango 20–600.
   El mismo renglón con 600 exactos **se acepta**: el límite es inclusivo en la referencia.
5. **Un renglón malo entre cuatro buenos** → `200`, cuatro en `aceptados`, uno en `cuarentena`,
   y cuatro filas nuevas. Esta es la prueba de la decisión 2.5 y la que más importa.
6. **El sobre roto** (sin `items`, `items` vacío, `items` con 501 elementos) → `400`, y
   **ninguna fila nueva en ninguna tabla**, `cuarentena` incluida.
7. **Sin token** → `401`. **Con un token vencido** → `401`. **Con un token firmado con otro
   secreto** → `401`.
8. **Marca de tiempo sin offset** (`"2026-10-13T14:32:00"`) → cuarentena, y el motivo lo dice.
9. **`zona_horaria` que no existe** (`"America/Nowhere"`) → cuarentena.
10. **Un `usuario_uuid` en el cuerpo distinto del del token** → cuarentena, con ese motivo
    (decisión 2.9).
11. **Una `nota` en el cuerpo** → el renglón va a cuarentena por `extra="forbid"`, **y el texto
    de la nota no aparece en `carga_original`**, solo su nombre en `claves_descartadas`
    (decisión 2.6). Afirmar las dos cosas.
12. **El usuario nace solo.** Una lectura de un UUID que no existe → una fila nueva en
    `usuarios` con su `uuid` y su `ts_alta`, y todo lo demás nulo (decisión 2.7).
13. **La respuesta y la base coinciden.** Para un lote mezclado, cada uuid está en exactamente
    una de las tres listas, y la suma de las tres es el número de renglones que se mandaron.
    Ninguno se pierde: eso es lo que «nunca se descarta en silencio» significa en una prueba.
14. **El esquema**, en `tests/test_esquema.py`: tras `alembic upgrade head` existen las doce
    tablas con sus nombres exactos, y `glucose_readings.uuid` es único.

Y el estilo tiene que pasar: `ruff check .` corre como primer paso de la integración continua.

---

## 8. Cómo se sabe que el paso 1 está hecho

```bash
# 1. Las doce tablas se crean desde cero.
rm -f glucy.db && alembic upgrade head
python - <<'PY'
import sqlite3
nombres = {f[0] for f in sqlite3.connect("glucy.db").execute(
    "select name from sqlite_master where type='table'")}
esperadas = {"usuarios","glucose_readings","meals","insulin_doses","context_events",
             "predictions","alerts","modelos","cuarentena","agregados_horarios",
             "agregados_diarios","xapi_events"}
print("faltan:", esperadas - nombres)   # tiene que decir: faltan: set()
PY

# 2. Las pruebas, todas.
pytest -q

# 3. El estilo.
ruff check .

# 4. La OpenAPI existe y lista el endpoint. Es entregable del punto 14.
uvicorn app.main:app --reload
# y abrir http://127.0.0.1:8000/docs — tiene que verse POST /readings con su esquema

# 5. A mano, el camino completo, que es lo que de verdad convence:
TOKEN=$(python scripts/token-de-prueba.py 11111111-1111-1111-1111-111111111111)
curl -s -X POST http://127.0.0.1:8000/readings \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"items":[{"uuid":"6f3a1b2c-0000-4000-8000-000000000001",
                 "ts_utc":"2026-10-13T14:32:00Z","zona_horaria":"America/Monterrey",
                 "mg_dl":112,"origen":"manual"}]}'
# la primera vez: aceptados con ese uuid. La segunda vez, el mismo comando: duplicados.
```

Que el mismo `curl` dos veces conteste primero `aceptados` y después `duplicados`, **sin crear
una segunda fila**, es la demostración de RF-36c y lo que hay que pegar en el pull request.

---

## 9. Dos cosas que encontré al escribir esto, y hay que anotarlas

Van en `05-PENDIENTES-Y-CONTRADICCIONES.md`, con su número, igual que C-1 a C-6.

**C-7. Los parámetros clínicos del perfil no tienen por dónde llegar al servidor.** La tabla
`usuarios` tiene `umbral_hipo`, `umbral_hiper`, `tipo_insulina_rapida`,
`duracion_accion_insulina`, `tipo_usuario` y `anio_nacimiento`, y el pipeline los **necesita**:
el IOB usa la duración de acción, y la alerta se deriva comparando la predicción con el umbral
de hipoglucemia del perfil. Pero los siete endpoints no incluyen ninguno para subirlos, y
`PerfilDato` del teléfono no se encola nunca, a propósito, porque arrastra nombre, apellidos y
peso. *Recomendación:* en el paso 2, un `POST /perfil` con **solo esos seis campos** —la «carga
aparte y reducida» que el propio comentario de `PerfilDato.swift` ya anticipa—, y decir en el
reporte que son ocho endpoints y por qué, en lugar de meterlo escondido en `/readings`.

**C-8. La confirmación del usuario no se puede volver a comprobar en el servidor.**
`validar_lectura` acepta `confirmada_por_usuario` y rechaza un valor de OCR sin confirmar
(D-11, P-01), pero `glucose_readings` **no tiene esa columna**, así que el servidor no tiene con
qué comprobarlo y la llamada pasa `confirmada_por_usuario=True`. En la práctica la regla se
cumple por construcción: en el teléfono nada se guarda sin confirmarse, así que nada sin
confirmar puede llegar a la cola. *Recomendación:* dejarlo así y **escribir la limitación** en
`docs/privacy.md` y en el reporte, en lugar de añadir una columna al Documento 3 para un dato
que ya no se puede verificar desde el servidor. P-01 se queda como garantía del teléfono, donde
ya tiene su prueba en `GlucyTests`. Si Jesus prefiere la columna, es un cambio del Documento 3
y hay que hacerlo antes del paso 2, no después.

---

## 10. Git

```bash
git checkout develop && git pull origin develop
git checkout -b feature/base-de-datos-y-readings
# …trabajo…
git add -A
git commit -m "feat: las doce tablas y POST /readings con cuarentena e idempotencia"
git push -u origin feature/base-de-datos-y-readings
gh pr create --base develop --title "feat: la base de datos y POST /readings" --body-file cuerpo.md
```

Commits en **Conventional Commits en español**. Van bien tres: uno `feat:` con el esqueleto y
las tablas, uno `feat:` con el endpoint y su servicio, uno `test:` con las catorce pruebas. Uno
solo también se acepta; cuatro ya es contarse la historia a sí mismo.

**Y esto, que ya costó una semana en iOS:** no fusionar hasta que la integración continua esté
**en verde de verdad**. Leer la conclusión del run, no la ausencia de rojo: un run `cancelled`
no es ni rojo ni verde.

## 10 bis. El cuerpo del pull request, ya escrito

Sigue la plantilla del repositorio, `.github/pull_request_template.md`.

### Antes

El repositorio tenía la estructura de la fase 0 y las reglas clínicas de referencia, pero ni
una tabla ni un endpoint. El teléfono no tenía a dónde subir nada: la fase 1 funciona entera en
local y la cola de sincronización no tenía interlocutor.

### Después

El servidor recibe lotes de lecturas de glucosa y contesta qué pasó con cada renglón:
`aceptados`, `duplicados` y `cuarentena` con su motivo. El mismo lote dos veces no duplica
nada. Lo que no pasa la validación se guarda en la tabla `cuarentena` con su carga original y
el motivo del rechazo, nunca se descarta en silencio. La documentación OpenAPI se publica en
`/docs`.

Las doce tablas del Documento 3 existen, sobre SQLite, creadas con una migración de Alembic.

### Cómo

La validación **no se reimplementa**: el servicio de ingesta importa `validar_lectura` de
`referencia/reglas_clinicas.py`, así que los números del servidor son los mismos que los de la
referencia por construcción y no por prueba. La app de iOS es una tercera implementación
independiente, y las tres tienen que coincidir.

El esquema valida el sobre y las reglas validan cada renglón: un renglón con un campo mal
escrito va a cuarentena y los demás se aceptan, en lugar de tirar el lote entero con un 422 y
hacer que el teléfono marque quinientas lecturas como fallidas.

La idempotencia es una restricción de la base —`UNIQUE` sobre `uuid` más `ON CONFLICT DO
NOTHING` con `RETURNING`— y no un `SELECT` previo, porque dos lotes iguales que llegan a la vez
pasarían los dos el `SELECT`. Lo específico de SQLite vive solo en `repositories/`, para que el
cambio a PostgreSQL del paso 4 no toque ninguna otra capa.

El `usuario_uuid` sale del token y nunca del cuerpo; si el cuerpo trae uno distinto, el renglón
va a cuarentena con ese motivo en lugar de ignorarse.

### Requisitos que cubre

RF-21 (el primero de los siete endpoints y la OpenAPI), RF-22 (validación y cuarentena),
RF-36c (idempotencia por UUID del teléfono), D-4 (SQLite para arrancar). Casos de prueba
**P-05** (el mismo lote dos veces no crea filas nuevas) y **P-06** (marca de tiempo futura a
cuarentena con su motivo), más P-02 comprobado del lado del servidor.

### Comprobado

- [x] Las catorce pruebas pasan en local
- [x] `ruff check .` limpio
- [x] La integración continua está en verde
- [x] No se agregó ninguna llave, token ni dato personal al repositorio
- [x] `curl` dos veces con el mismo uuid: primero `aceptados`, después `duplicados`, y una sola
      fila en la tabla

---

## 11. El texto para pegarle a Claude Code

Lo que va de aquí abajo es lo que se pega tal cual.

---

Estás en el repositorio `glucy-backend`. **Lee primero dos archivos y no empieces sin ellos:**
`CLAUDE.md` de la raíz y `docs/paso-1-base-de-datos-y-readings.md`. El segundo es el que manda:
tiene las diez decisiones, las firmas exactas, las doce tablas campo por campo y las catorce
pruebas. Si algo de lo que te pido aquí parece contradecirlo, gana el documento.

**La rama sale de `develop`, no de `main`:**

```bash
git checkout develop && git pull origin develop
git checkout -b feature/base-de-datos-y-readings
```

Construye, en este orden:

1. `requirements.txt` con fastapi, uvicorn, pydantic-settings, sqlalchemy y alembic.
2. El esqueleto de `app/` con `config.py`, `db/sesion.py`, `seguridad.py` y `main.py` con
   `GET /salud`.
3. Las **doce** tablas en `app/models/tablas.py` y la migración `0001` de Alembic. Las doce de
   una vez, aunque este paso solo escriba en tres.
4. Los esquemas de Pydantic del apartado 4, con `LoteCrudo` validando el sobre y
   `LecturaEntrada` validando un renglón.
5. `app/services/ingesta.py` con `ingerir_lecturas`, siguiendo los seis pasos del orden que da
   el documento.
6. `app/routers/readings.py` con `POST /readings`.
7. `scripts/token-de-prueba.py`.
8. Las catorce pruebas del apartado 7.
9. Llena `docs/api.md` y `docs/database.md`, que están marcados «pendiente de llenar».

Todo en **español**: comentarios, docstrings, nombres del dominio, mensajes de commit y la
descripción del pull request. Los nombres de las tablas **no se traducen ni se renombran**:
`usuarios`, `glucose_readings`, `meals`, `insulin_doses`, `context_events`, `predictions`,
`alerts`, `modelos`, `cuarentena`, `agregados_horarios`, `agregados_diarios`, `xapi_events`.
Están mezclados en dos idiomas a propósito, porque así están en el Documento 3.

**Lo que NO tienes que hacer:**

- **No reimplementes la validación.** Importa `validar_lectura`, `Origen` y `Rechazo` de
  `referencia/reglas_clinicas.py`. Y **no toques nada dentro de `referencia/`**.
- **No metas PostgreSQL, TimescaleDB ni Docker.** SQLite, por D-4. Son del paso 4.
- **No escribas el emisor de tokens**, solo la verificación que devuelve 401.
- **No pongas ningún valor por omisión en `jwt_secret`.** Si falta la variable, la aplicación
  no debe arrancar.
- **No escribas pipeline, ni predicción, ni explicación, ni nada que calcule o sugiera una
  dosis de insulina.**
- **Ningún valor real en `.env.example`**, solo los nombres. Y nada de llaves en el código.

Cuando termines, **antes de decir que está hecho**: corre `pytest -q` y `ruff check .` y pega
la salida de los dos. Después corre a mano el `curl` del apartado 8 **dos veces** y pega las
dos respuestas, que tienen que ser `aceptados` la primera y `duplicados` la segunda.

Y por último, **abre el pull request**, contra `develop`:

```bash
git push -u origin feature/base-de-datos-y-readings
gh pr create --base develop --title "feat: la base de datos y POST /readings" --body-file cuerpo.md
```

El cuerpo ya está escrito en el apartado 10 bis del documento: cópialo a `cuerpo.md` y
sustituye las casillas por lo que de verdad hayas comprobado. Si una no la comprobaste, déjala
sin marcar y dilo. **Sin pull request la integración continua no corre.**
