# Paso 4 de la fase 2 — PostgreSQL con TimescaleDB y el pipeline

Escrito el 25 de octubre de 2026, después de fusionar el paso 3. Lee antes `CLAUDE.md` y los
tres documentos anteriores: sus decisiones siguen vigentes y este documento no las vuelve a
discutir.

Es el paso más grande de la fase. Tiene dos mitades que se pueden hacer en dos días distintos:
**la base** (apartados 2.1 a 2.6) y **el pipeline** (2.7 a 2.11).

---

## 0. Antes de abrir Claude Code

```bash
cd glucy-backend
git checkout develop && git pull origin develop
git checkout -b feature/postgres-timescale-y-pipeline
```

**La rama sale de `develop` y el pull request va contra `develop`.**

Lo que dejaron los pasos 1 a 3: los seis endpoints, `FechaUtc`, el reparto en tres listas con su
descriptor, los repositorios de consulta filtrados por dueño, y las siete validaciones de
`referencia/reglas_clinicas.py`. **202 pruebas en verde** (152 al cerrar el paso 2).

## 1. Qué se construye

1. **Que el mismo código corra en PostgreSQL**, sin dejar de correr en SQLite.
2. **`docker-compose.yml`** con la API y TimescaleDB, que es entregable de la rúbrica.
3. **La serie limpia**: una tabla nueva con la señal del sensor ya depurada (RF-23).
4. **El pipeline**: limpieza, los dos juegos de características (RF-24) y los agregados.
5. **Una orden** que lo corre sobre un periodo: `python -m app.pipeline`.

No hay ningún endpoint nuevo. `/predict` es el paso 5.

## 1 bis. Los requisitos, pegados

### RF-23, limpieza

> Detección de atípicos por tasa de cambio, suavizado Savitzky-Golay e interpolación de huecos
> de hasta 15 minutos. **Solo sobre la serie continua del sensor.**

### RF-24 y RF-24b, características

> Dos juegos de características: el *denso* para modo sensor (rezagos a 5/10/15/30/60 min,
> primera y segunda derivada, medias móviles, COB, IOB, hora cíclica, día de la semana,
> actividad y sueño) y el *disperso* para modo sin sensor (última lectura y su antigüedad,
> carbohidratos y dosis de la comida, hora del día, promedio de los últimos días, contexto).
> COB con absorción lineal; no se modela la digestión (D-8).

### RF-25

> Cada fila conserva su origen y la versión del modelo que la generó.

### D-4

> SQLite sirve para arrancar; PostgreSQL con TimescaleDB cuando haya volumen.

### De `CLAUDE.md`

> El código no debe asumir extensiones de Timescale fuera de la capa de repositorios.

---

## 2. Las decisiones de este paso

### 2.1 Dos motores, y el esquema ya es portable

SQLite sigue siendo lo de desarrollo y lo de las 202 pruebas; PostgreSQL entra **por la URL**,
sin una sola rama en el código de aplicación. No se migra: se gana un segundo motor.

Y hay una buena noticia comprobada antes de escribir esto: **las doce tablas compilan tal cual
en PostgreSQL.** Se compiló el `CREATE TABLE` de cada una contra el dialecto de PostgreSQL y
ninguna falló. `sa.Uuid`, `sa.Double`, `sa.JSON` y `DateTime(timezone=True)` son portables, y
en PostgreSQL ese último es un `TIMESTAMPTZ` que ya devuelve la fecha con zona, así que
`FechaUtc` sigue sirviendo sin cambiarle nada.

**Lo que no es portable son tres líneas**, y es la decisión siguiente.

### 2.2 Los tres `upsert` no compilan en PostgreSQL

`app/repositories/usuarios.py`, `lotes.py` y `perfil.py` empiezan con:

```python
from sqlalchemy.dialects.sqlite import insert
```

Se compiló la sentencia de `lotes.py` contra el dialecto de PostgreSQL y esto es lo que pasa:

```
1) el insert de SQLite, compilado contra SQLite:   INSERT INTO glucose_readings … (bien)
2) el MISMO insert, compilado contra PostgreSQL:
     AttributeError -> 'OnConflictDoNothing' object has no attribute 'constraint_target'
3) el insert de PostgreSQL, compilado contra PostgreSQL:  INSERT INTO glucose_readings … (bien)
4) y el insert genérico de sqlalchemy, ¿tiene on_conflict_do_nothing?  False
```

Las dos cosas importan: **el de SQLite truena en PostgreSQL**, y **el genérico no sirve de
reemplazo** porque `ON CONFLICT` no es SQL estándar y SQLAlchemy solo lo expone en los
dialectos que lo tienen. Así que hace falta elegir el `insert` según el motor, en un solo sitio:

```python
# app/repositories/upsert.py
def insertar(sesion: Session, modelo: type[Base]) -> Insert:
    """El `insert` del dialecto de la sesión, para poder usar `on_conflict_do_nothing`.

    La idempotencia es una restricción de la base (decisión del paso 1) y `ON CONFLICT` no es
    SQL estándar: SQLAlchemy lo expone por dialecto. Elegirlo aquí deja los repositorios
    iguales en los dos motores, que es justo lo que pide CLAUDE.md: lo específico de cada
    motor vive en `repositories/` y en ningún otro lado.
    """
```

La prueba que vale es de compilación y **no necesita un servidor**: compilar la misma sentencia
contra los dos dialectos y comprobar que las dos salen. Hoy esa prueba falla.

### 2.3 TimescaleDB va en su propia migración, y solo en PostgreSQL

`create_hypertable` no existe en SQLite. La migración `0002` tiene que preguntar por el motor:

```python
def upgrade() -> None:
    op.create_table("serie_limpia", …)          # en los dos motores
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
        op.execute("SELECT create_hypertable('serie_limpia', 'ts_utc', "
                   "chunk_time_interval => INTERVAL '7 days')")
```

En SQLite la migración termina ahí y la tabla queda normal. **Las 202 pruebas no se enteran**,
que es el criterio: ninguna prueba vieja se modifica y ninguna necesita un servidor.

### 2.4 La hipertabla **no** puede ser `glucose_readings`

Esta es la trampa del paso, y conviene entenderla antes de escribir la migración.

TimescaleDB exige que **cualquier índice único de una hipertabla incluya la columna de
particionado**. La llave primaria de `glucose_readings` es `uuid` a secas, y es la llave de
idempotencia de todo el sistema: el mismo lote dos veces no duplica porque el `uuid` es único.

Las salidas, y por qué se descartan dos:

| Salida | Qué cuesta |
| --- | --- |
| Llave compuesta `(uuid, ts_utc)` | la idempotencia se rompe: el mismo `uuid` con otra marca de tiempo entraría como fila nueva, y nadie se enteraría |
| Hipertabla con un único índice sobre `uuid` | Timescale la rechaza; no es una opción |
| **Dejar `glucose_readings` como tabla normal** | se pierde el particionado en la tabla cruda, que es la que menos lo necesita porque se lee por periodo y ya tiene índice en `ts_utc` |

**Se queda la tercera.** La tabla cruda es el registro de lo que el teléfono subió y su llave
tiene que seguir siendo el `uuid` solo. La hipertabla es la tabla de la decisión que sigue.

### 2.5 La serie limpia es la tabla trece (C-9)

El pipeline limpia la señal y **no tiene dónde dejarla**. `glucose_readings` ni siquiera tiene
la columna `atipica`: el paso 1 decidió no subirla porque el pipeline la recalcula, y la tabla
del Documento 3 tampoco la trae. Escribir encima de `mg_dl` sería perder el dato crudo, y la
regla 1 dice que el teléfono es el dueño de lo crudo.

Así que se crea **`serie_limpia`**, que no está en el Documento 3 y hay que decirlo en el
reporte:

```
usuario_uuid  ts_utc  mg_dl  origen  atipica  interpolada
```

Llave primaria `(usuario_uuid, ts_utc)`: **sin `uuid`, porque una fila interpolada no viene de
ninguna lectura y no tiene uno.** Esa llave incluye la columna de tiempo, así que **esta sí
puede ser hipertabla**, y es la única tabla que de verdad crece: 288 filas por día y por
persona.

`atipica` e `interpolada` viajan en la fila porque una métrica calculada sobre datos
interpolados no vale lo mismo que una calculada sobre lecturas reales, y quien entrene tiene
que poder distinguirlas sin adivinar.

### 2.6 Los agregados los llena el pipeline, no un *continuous aggregate*

El comentario de `_ColumnasAgregado` dice hoy que «en PostgreSQL serán *continuous aggregates*
de TimescaleDB (paso 4)». **Ese comentario hay que corregirlo**, por dos razones independientes
y las dos comprobadas:

1. **La licencia.** La edición Apache 2 de TimescaleDB trae hipertablas y `time_bucket`, pero
   **los *continuous aggregates* son de la edición Community, que no es software libre** sino
   código disponible con licencia propia. La restricción del proyecto es que todo sea libre, así
   que la imagen es la `-oss`, y en ella esas funciones no existen. Tampoco la compresión ni
   `time_bucket_gapfill`.
2. **El árbitro.** Un *continuous aggregate* calcularía el TIR y el GMI **en SQL**, y eso sería
   una cuarta implementación de las reglas clínicas, sin nada que la compare contra
   `referencia/reglas_clinicas.py`. Ya hay tres (Swift, el pipeline, la referencia) y coinciden
   porque dos de ellas importan la tercera.

Así que los dos agregados se llenan **con el mismo `indicadores()` de la referencia**, agrupando
por hora y por día. Siguen siendo tablas normales en los dos motores. El `time_bucket` de la
edición libre se puede usar para agrupar en SQL **si hace falta por velocidad**, pero el cálculo
clínico no baja a SQL.

Qué sí da la edición libre, y es lo que se usa: la hipertabla de `serie_limpia`, con sus trozos
de siete días y el `time_bucket` para agrupar.

### 2.6 bis Por qué vale la pena, con el número medido

Se midió `/stats` sobre el periodo máximo con densidad de sensor de verdad —90 días cada
5 minutos, **25 920 lecturas**— y tarda **600 ms**; `/history` devuelve su página de 200 en
35 ms. No incumple nada, porque los 200 ms son el presupuesto de `/predict` y no de `/stats`.
Pero son tres veces ese presupuesto, y es exactamente el trabajo que los agregados ahorran:
una vez que `agregados_diarios` existe, el mismo periodo son 90 filas en lugar de 25 920.

**El paso 4 no cambia `/stats`.** Deja los agregados llenos y la medición escrita; cambiarlo
para que los lea es un paso aparte, porque los agregados se calculan sobre la serie limpia y
`/stats` hoy responde sobre las lecturas crudas de **todos** los orígenes, que no es lo mismo.

### 2.7 Savitzky-Golay con numpy, y scipy solo como árbitro

El suavizado es un filtro estándar, pero meter scipy en la imagen de la API para una función es
mucho peso. La alternativa habitual —reescribirlo a mano y esperar que esté bien— es peor.

Se hace así: **el filtro se escribe con numpy**, que ya hace falta para el vector de
características, y **scipy entra en `requirements-dev.txt`** para que una prueba compare las dos
salidas. El filtro se escribió y se corrió antes de recetarlo:

```
n=   7  diferencia maxima contra scipy: 1.705e-13
n=  12  diferencia maxima contra scipy: 1.990e-13
n=  50  diferencia maxima contra scipy: 2.274e-13
n= 289  diferencia maxima contra scipy: 2.274e-13
pesos: [-0.095238  0.142857  0.285714  0.333333  0.285714  0.142857 -0.095238]
suman 1: 1.0
```

Coincide con scipy en el centro **y en los extremos**, que es donde suelen fallar estas
reescrituras. Y los pesos de ventana 7 con grado 2 salen siendo
`(−2, 3, 6, 7, 6, 3, −2) / 21`, que son los publicados: eso se puede poner en el reporte como
comprobación de que el filtro es el de la literatura y no uno inventado.

**Ventana 7 y grado 2**, es decir 35 minutos y una parábola. Con 5 minutos de muestreo, una
ventana más corta no quita el ruido del sensor y una más larga empieza a aplanar los picos
postprandiales, que son justo lo que M-3 tiene que predecir.

### 2.8 Se limpia la señal del sensor y nada más

Las tres operaciones de RF-23 corren **solo** sobre filas con `origen = sensor`, y la referencia
ya lo tiene decidido en su firma: `es_atipica_por_tasa(..., origen)` devuelve `False` para
cualquier otro origen y `se_puede_interpolar(hueco_min, origen)` también.

Una lectura manual o de foto es un punto aislado: entre dos pinchazos separados por horas
cualquier tasa de cambio es posible, y suavizar dos puntos sueltos no significa nada.

Qué pasa con cada caso:

- **Atípica por tasa** (> 4 mg/dL/min): la fila entra a `serie_limpia` con `atipica = true`,
  **no se borra**. Un dato descartado sin rastro es una falla invisible, igual que en cuarentena.
  No entra al suavizado ni al entrenamiento.
- **Hueco de hasta 15 min**: se rellena por interpolación lineal y la fila nueva lleva
  `interpolada = true` y `origen = sensor`.
- **Hueco de más de 15 min**: **no se rellena.** Queda el hueco, y el juego de características
  denso simplemente no tiene fila ahí.
- **Lecturas manuales y de foto**: entran a `serie_limpia` tal cual, con su origen, sin tocar.

### 2.9 Los nombres de las características son un contrato con glucy-ml

Esta es la decisión que más cuesta si se descubre tarde. El artefacto que entrene `glucy-ml`
recibe un vector de números **en un orden**. Si aquí se llaman o se ordenan distinto, la
predicción se alimenta con las columnas cambiadas de lugar y **nada falla**: salen números
plausibles y equivocados.

Así que los dos juegos se declaran en un solo módulo, como tuplas ordenadas, y **ese módulo es
la autoridad**; `glucy-ml` copia la lista, no la reinventa:

```python
# app/services/pipeline/caracteristicas.py
CARACTERISTICAS_DENSAS: tuple[str, ...] = (
    "mg_dl", "rezago_5", "rezago_10", "rezago_15", "rezago_30", "rezago_60",
    "derivada_1", "derivada_2", "media_30", "media_60",
    "cob", "iob", "hora_sin", "hora_cos", "dia_semana",
)
CARACTERISTICAS_DISPERSAS: tuple[str, ...] = (
    "mg_dl", "antiguedad_min", "carbs_g", "dosis_ui",
    "cob", "iob", "hora_sin", "hora_cos", "contexto_comida", "promedio_7d",
)
```

Reglas que van con la lista:

- **`hora_sin` y `hora_cos`** y no «hora»: a las 23:50 y a las 00:10 la hora cruda está a
  23 horas de distancia y en realidad son veinte minutos. `sin` y `cos` de `2π × minutos/1440`.
- **`dia_semana`** es 0 a 6 con el lunes en 0, en la **zona de la fila**, no en UTC, por lo mismo
  que los días del paso 3.
- **`contexto_comida`** es categórica y se codifica con un entero fijo por valor del enum,
  declarado en el mismo módulo. `None` es un código propio y no un cero disfrazado.
- **Lo que falta es `NaN`, no cero.** Un rezago de 60 minutos que no existe porque la serie
  empieza ahí no es «glucosa cero»: XGBoost trata el `NaN` como información y el cero como un
  valor. Esto hay que hacerlo bien o el modelo aprende que cero significa «faltaba el dato».
- **COB e IOB salen de la referencia**, `cob_total` e `iob`, con el tiempo de absorción de cada
  comida y la duración de acción del perfil. El IOB cuenta **solo las dosis de bolo**: se filtra
  por `tipo`, porque la basal no se acumula en este modelo.
- **Ninguna característica se construye a partir de una comida que no se registró** (D-9,
  RF-37). Si no hay comida, `carbs_g` es `NaN` y el COB es 0 porque no hay nada que absorber,
  que no es lo mismo.

### 2.10 Sin actividad ni sueño, y hay que decir por qué (C-10 y C-11)

RF-24 pide actividad y sueño en el juego denso. **No hay de dónde sacarlas**, y al mirarlo
aparecieron tres desajustes que conviene anotar los tres:

1. **Ningún endpoint sube contexto.** Los ocho que hay no incluyen uno para `context_events`,
   igual que pasaba con el perfil antes de C-7.
2. **La app tampoco lo captura.** `EventoContexto.swift` existe en el modelo de la fase 1, pero
   ninguna pantalla ni ningún caso de uso crea uno: no hay dónde registrar un ejercicio.
3. **Las escalas no coinciden.** El comentario de `EventoContexto.swift` dice «escala de 1 a 5
   tal como la persona la declara»; la regla de `glucy-ml` dice que las escalas de OhioT1DM son
   **1 a 10 para ejercicio y 1 a 3 para calidad de sueño** y que **no se cambian**, precisamente
   para no tener que traducirlas. Y en el backend `context_events.intensidad` y `.calidad` son
   **texto**, no números.

Decisión para este paso, que es reversible y hay que decirla en el reporte: **el juego denso se
queda sin `actividad` ni `sueno`.** Un modelo entrenado con una variable que en producción
siempre falta aprende de algo que nunca va a tener, y eso se llama desajuste entre
entrenamiento y servicio; es peor que no tenerla.

Lo que lo convierte en una ventaja para el reporte: OhioT1DM **sí** trae ejercicio y sueño, así
que en `glucy-ml` se entrena **con y sin** esas dos variables y se reporta la diferencia. Eso
mide lo que cuesta no capturarlas, en lugar de esconderlo, y es un resultado honesto que se
puede defender.

Si se decidiera lo contrario, el orden sería: arreglar la escala en la app, un `POST /context`
con el descriptor de lote que ya existe, y una pantalla de registro. Son tres cosas, y el
calendario de noviembre no las tiene.

### 2.11 El pipeline es una orden, no un endpoint

No se corre dentro de `POST /readings`: el teléfono sube un lote de 500 lecturas en una ventana
de wifi y no tiene por qué esperar a que se recalculen las características de ocho semanas.

```bash
python -m app.pipeline --usuario <uuid> --desde 2026-10-01 --hasta 2026-10-26
python -m app.pipeline --todos --ultimos-dias 7
```

Es **idempotente**: correrlo dos veces sobre el mismo periodo deja la misma `serie_limpia` y los
mismos agregados, con `ON CONFLICT DO UPDATE` sobre `(usuario_uuid, ts_utc)`. Programarlo es de
la fase 6; por ahora se corre a mano, y eso basta para entrenar y para el panel.

---

## 3. Archivos que hay que crear o tocar

```
requirements.txt                   TOCAR: + psycopg[binary], numpy
requirements-dev.txt               TOCAR: + scipy (solo árbitro del filtro, decisión 2.7)
app/repositories/upsert.py         NUEVO: el insert según el dialecto (decisión 2.2)
app/repositories/usuarios.py       TOCAR: usar upsert.insertar
app/repositories/lotes.py          TOCAR: igual
app/repositories/perfil.py         TOCAR: igual
app/models/tablas.py               TOCAR: + SerieLimpia, y corregir el comentario de
                                   _ColumnasAgregado (decisión 2.6)
migrations/versions/0002_*.py      NUEVO: serie_limpia, e hipertabla solo en PostgreSQL
app/services/pipeline/__init__.py  NUEVO
app/services/pipeline/filtro.py    NUEVO: Savitzky-Golay con numpy
app/services/pipeline/limpieza.py  NUEVO: atípicos, interpolación, suavizado (RF-23)
app/services/pipeline/caracteristicas.py  NUEVO: los dos juegos (RF-24)
app/services/pipeline/agregados.py NUEVO: llena agregados_horarios y agregados_diarios
app/repositories/serie.py          NUEVO: leer y escribir serie_limpia
app/pipeline.py                    NUEVO: la orden (python -m app.pipeline)
docker-compose.yml                 NUEVO
Dockerfile                         NUEVO
.env.example                       TOCAR: el ejemplo de URL de PostgreSQL, sin valores
.github/workflows/ci.yml           TOCAR: un segundo trabajo con PostgreSQL y TimescaleDB
docs/database.md                   TOCAR: la tabla trece y por qué
docs/pipeline.md                   NUEVO: las tres operaciones y los dos juegos
tests/test_portabilidad.py  tests/test_limpieza.py  tests/test_caracteristicas.py
tests/test_agregados.py  tests/test_pipeline.py     NUEVOS
```

**No se toca ninguna prueba de los pasos 1, 2 y 3.** `git diff --stat develop -- tests/` solo
debe mostrar los archivos nuevos.

## 4. Las firmas, exactas

```python
# app/services/pipeline/filtro.py
VENTANA_SUAVIZADO = 7   # 7 muestras de 5 min = 35 min (decisión 2.7)
GRADO_SUAVIZADO = 2

def coeficientes(ventana: int = VENTANA_SUAVIZADO, grado: int = GRADO_SUAVIZADO) -> np.ndarray:
    """Los pesos del filtro: la fila central de la pseudoinversa de Vandermonde.

    Con ventana 7 y grado 2 salen (−2, 3, 6, 7, 6, 3, −2)/21, los publicados.
    """

def suavizar(valores: Sequence[float]) -> np.ndarray:
    """Savitzky-Golay. Con menos muestras que la ventana devuelve la serie intacta."""


# app/services/pipeline/limpieza.py
@dataclass(frozen=True)
class Punto:
    ts_utc: datetime
    mg_dl: float
    origen: Origen
    atipica: bool = False
    interpolada: bool = False

def limpiar(lecturas: Sequence[LecturaGlucosa]) -> list[Punto]:
    """Las tres operaciones de RF-23, en orden: atípicos, interpolación, suavizado.

    Solo toca las filas de origen `sensor` (decisión 2.8). Nada se borra: una atípica sale
    marcada, no ausente.
    """


# app/services/pipeline/caracteristicas.py
def vector_denso(punto: datetime, serie: Sequence[Punto], comidas, dosis, perfil) -> dict[str, float]:
    """El juego denso de RF-24, en el orden de CARACTERISTICAS_DENSAS.

    Lo que no se puede calcular es `NaN` y nunca cero (decisión 2.9): un rezago que no existe
    no es una glucosa de cero.
    """

def vector_disperso(punto: datetime, ultima: Punto | None, comidas, dosis, perfil) -> dict[str, float]:
    """El juego disperso, para modo sin sensor. `antiguedad_min` es la edad de `ultima`."""

def como_fila(vector: dict[str, float], juego: tuple[str, ...]) -> list[float]:
    """El vector en el orden del juego. Es lo único que el modelo recibe (decisión 2.9)."""


# app/services/pipeline/agregados.py
def recalcular(sesion, usuario_uuid: UUID, desde: datetime, hasta: datetime) -> tuple[int, int]:
    """Llena agregados_horarios y agregados_diarios desde serie_limpia con la referencia.

    Devuelve cuántas filas quedaron en cada uno. El día es el día **local** de cada fila, igual
    que en /stats (decisión 2.3 del paso 3).
    """
```

## 5. Docker y el entorno

`docker-compose.yml`, con dos servicios y ningún valor secreto dentro:

```yaml
services:
  base:
    # La edición Apache 2: libre de verdad. Trae hipertablas y time_bucket; no trae
    # continuous aggregates ni compresión, y por eso los agregados los llena el
    # pipeline (decisión 2.6).
    image: timescale/timescaledb:2.31.0-pg16-oss
    environment:
      POSTGRES_DB: glucy
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes: [datos:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d glucy"]
      interval: 5s
      retries: 10
  api:
    build: .
    env_file: .env
    depends_on:
      base: {condition: service_healthy}
    ports: ["8000:8000"]
volumes:
  datos:
```

Tres cosas que no se negocian:

- **Ningún valor en el `docker-compose.yml`.** Usuario y contraseña salen del `.env`, que está
  en `.gitignore`. En `.env.example` van los nombres y ningún valor, como hasta ahora.
- **`depends_on` con `service_healthy`**, no a secas: sin eso la API arranca antes que la base,
  `alembic upgrade head` falla y parece un error de migración.
- **El volumen con nombre.** Sin él, `docker compose down` borra la base y no se nota hasta que
  alguien pierde los datos de una semana de pruebas.

En la integración continua se agrega un **segundo trabajo** con la misma imagen como `services:`
que corre `alembic upgrade head` y las pruebas marcadas `postgres`. El trabajo de siempre, con
SQLite, se queda como está y sigue siendo el rápido.

---

## 6. Lo que este paso NO construye

- **Ni `/predict` ni `/explain`.** Pasos 5 y 6.
- **Ningún endpoint nuevo**, y en particular **no** un `POST /context` (decisión 2.10).
- **Ni Grafana, ni el Learning Record Store.** Fase 6.
- **No cambia `/stats` ni `/history`** para que lean los agregados (decisión 2.6 bis).
- **No migra los datos de SQLite a PostgreSQL**: no hay datos que migrar todavía.
- **Ni compresión, ni políticas de retención, ni continuous aggregates**: no están en la edición
  libre.
- **No entrena nada.** El modelo es `glucy-ml`, fase 3.
- **Nada en la app de iOS.** Paso 7.

---

## 7. Las pruebas que tienen que pasar

Las 202 anteriores siguen pasando **sin modificarse**.

**Portabilidad** (`tests/test_portabilidad.py`) — no necesitan servidor:

55. El `insert` de `upsert.insertar` compila contra SQLite **y** contra PostgreSQL, para las tres
    tablas que lo usan. Esta prueba falla hoy.
56. El `CREATE TABLE` de las **trece** tablas compila contra los dos dialectos.
57. `FechaUtc` sigue devolviendo la fecha con zona después del cambio (la prueba del paso 2, sin
    tocarla, tiene que seguir en verde).

**Limpieza** (`tests/test_limpieza.py`):

58. Una lectura con tasa > 4 mg/dL/min sale con `atipica = True` y **sigue en la lista**.
59. La misma tasa entre dos lecturas **manuales** no marca nada: no es una serie.
60. Un hueco de 10 min se rellena con `interpolada = True`; uno de 20 min **no se rellena**.
61. Un hueco de 10 min entre dos lecturas manuales **no se rellena** (`se_puede_interpolar`).
62. El suavizado coincide con `scipy.signal.savgol_filter` a menos de 1e-9, en el centro y en
    los dos extremos, con 7, 12, 50 y 289 muestras.
63. Los pesos de la ventana 7 grado 2 son `(−2, 3, 6, 7, 6, 3, −2)/21` y suman 1.
64. Una fila `atipica` **no entra** al suavizado: quitarla o dejarla cambia el resultado, y la
    prueba fija cuál es el correcto.

**Características** (`tests/test_caracteristicas.py`):

65. `como_fila` devuelve los valores en el orden exacto de `CARACTERISTICAS_DENSAS`, comparado
    contra la tupla literal. Es la prueba del contrato con `glucy-ml` (decisión 2.9).
66. Un rezago que no existe es `NaN`, **no cero**, y `math.isnan` lo confirma.
67. `hora_sin` y `hora_cos` de las 23:50 y las 00:10 están a menos de 0.09 de distancia
    euclidiana; con la hora cruda estarían a 23.67.
68. `dia_semana` de una lectura de las 19:00 en `America/Monterrey` es el día local, no el UTC
    del día siguiente.
69. `cob` del vector coincide con `cob_total` de la referencia, y el caso P-11 —60 g, 180 min, a
    los 90 min— da **30**.
70. `iob` ignora las dosis con `tipo = basal` y coincide con `iob` de la referencia para las de
    bolo.
71. **Sin comida registrada, `carbs_g` es `NaN` y el COB es 0**, y no se inventa ninguna comida
    (D-9, RF-37).
72. El vector denso **no tiene** `actividad` ni `sueno` (decisión 2.10).

**Agregados** (`tests/test_agregados.py`):

73. Tres días de serie limpia dejan 3 filas en `agregados_diarios` y 72 en `agregados_horarios`.
74. El promedio y el TIR de una fila coinciden **campo por campo** con `indicadores()` de la
    referencia sobre los mismos valores.
75. Correr `recalcular` dos veces sobre el mismo periodo **no duplica filas** y deja los mismos
    números.
76. El agregado diario agrupa por día **local**, con la zona de cada fila.
77. Los agregados de un usuario no incluyen ni una fila de otro.

**La orden** (`tests/test_pipeline.py`):

78. `python -m app.pipeline --usuario X --desde … --hasta …` llena `serie_limpia` y los dos
    agregados, y devuelve código de salida 0.
79. Correrla dos veces deja la base igual (idempotencia).
80. Sobre un usuario sin lecturas no falla: no escribe nada y sale con 0.

Y `ruff check .` limpio.

---

## 8. Cómo se sabe que el paso 4 está hecho

```bash
pytest -q                 # las 202 de antes más las nuevas, ninguna de las 202 modificada
ruff check .
git diff --stat develop -- tests/test_readings.py tests/test_esquema.py tests/test_meals.py \
  tests/test_insulin.py tests/test_perfil.py tests/test_fechas.py tests/test_history.py \
  tests/test_stats.py tests/test_aislamiento.py tests/test_reglas_clinicas.py
# tiene que salir VACÍO

# Y la comprobación que de verdad convence: el mismo código, los dos motores.
docker compose up -d
docker compose exec api alembic upgrade head
docker compose exec base psql -U $POSTGRES_USER -d glucy -c "SHOW timescaledb.license;"
# tiene que decir 'apache'
docker compose exec base psql -U $POSTGRES_USER -d glucy \
  -c "SELECT hypertable_name FROM timescaledb_information.hypertables;"
# tiene que listar serie_limpia, y solo serie_limpia

# sube un lote con el token de prueba contra el contenedor, corre el pipeline y mira:
docker compose exec api python -m app.pipeline --usuario <uuid> --desde … --hasta …
docker compose exec base psql -U $POSTGRES_USER -d glucy \
  -c "SELECT count(*), count(*) FILTER (WHERE interpolada) FROM serie_limpia;"
```

Que las mismas pruebas pasen en SQLite y que el lote entre en PostgreSQL sin cambiar una línea
de `app/` es el criterio del paso.

---

## 9. Git y el cuerpo del pull request

Seis commits, en este orden: la portabilidad del `upsert`, la tabla trece con su migración, el
filtro, la limpieza, las características y los agregados, y al final Docker con la integración
continua. Contra `develop`, y **sin fusionar hasta leer la conclusión del run**, que ahora son
dos trabajos y los dos tienen que estar verdes.

### Antes

El servidor guardaba y devolvía lo que el teléfono subía, tal cual, sobre SQLite. La señal del
sensor llegaba con sus huecos y sus saltos imposibles, nadie la limpiaba, y no existía ninguna
característica con la que entrenar o predecir. Las dos tablas de agregados estaban vacías.

### Después

El mismo código corre en SQLite y en PostgreSQL con TimescaleDB, y `docker compose up` levanta
las dos piezas. El pipeline deja la señal del sensor limpia en una tabla nueva —atípicos
marcados, huecos de hasta 15 minutos interpolados, suavizado Savitzky-Golay— y construye los dos
juegos de características de RF-24 en el orden que el modelo va a esperar. Los dos agregados se
llenan con las mismas reglas clínicas que usa el teléfono.

### Cómo

Tres líneas impedían el segundo motor: los `upsert` importaban el `insert` del dialecto de
SQLite, que **no compila** contra PostgreSQL, y el `insert` genérico de SQLAlchemy no tiene
`on_conflict_do_nothing` porque `ON CONFLICT` no es SQL estándar. Ahora el dialecto se elige en
`repositories/upsert.py` y una prueba de compilación lo comprueba sin necesitar un servidor.

La hipertabla **no** es `glucose_readings`: Timescale exige que todo índice único incluya la
columna de tiempo, y la llave de esa tabla es el `uuid` solo, que es la llave de idempotencia de
todo el sistema. Tocarla habría dejado entrar el mismo `uuid` dos veces con marcas distintas. La
hipertabla es `serie_limpia`, cuya llave es `(usuario_uuid, ts_utc)` y que es la única tabla que
crece de verdad: 288 filas por día y por persona.

Los agregados **no** son *continuous aggregates*, por dos razones: no existen en la edición
Apache 2 de TimescaleDB, que es la libre, y calcularlos en SQL sería una cuarta implementación de
las reglas clínicas sin nada que la compare contra la referencia.

El suavizado se escribió con numpy y `scipy` quedó en las dependencias de desarrollo como
árbitro: una prueba compara las dos salidas y coinciden a 2e-13 en el centro y en los extremos.
Los pesos de ventana 7 y grado 2 salen `(−2, 3, 6, 7, 6, 3, −2)/21`, los publicados.

Lo que no se calcula también está decidido: el juego denso va **sin actividad ni sueño**, porque
ningún endpoint las sube, la app no las captura y las escalas no coinciden entre la app, el
backend y OhioT1DM. Entrenar con una variable que en producción siempre falta es un desajuste
entre entrenamiento y servicio, así que `glucy-ml` entrenará con y sin ellas y reportará la
diferencia.

### Requisitos que cubre

RF-23 (limpieza), RF-24 y RF-24b (los dos juegos y el COB lineal), D-4 (el segundo motor), y
Docker como entregable. Casos P-11 (COB 60 g/180 min a los 90 min = 30 g) y P-12 (la glucosa sube
sin comida registrada y no se infiere nada).

### Contradicciones que deja anotadas

- **C-9: la serie limpia no está en el Documento 3.** Es la tabla trece. Sin ella el pipeline no
  tiene dónde dejar lo que limpia, y escribir sobre `mg_dl` perdería el dato crudo.
- **C-10: actividad y sueño no tienen origen.** Ningún endpoint, ninguna pantalla.
- **C-11: las escalas de contexto no coinciden** entre `EventoContexto.swift` (1 a 5),
  `glucy-ml` (1 a 10 y 1 a 3, las de OhioT1DM, que no se cambian) y `context_events`, donde son
  texto.

### Comprobado

- [ ] Las pruebas pasan en local y el `git diff` de las pruebas anteriores sale vacío
- [ ] `ruff check .` limpio
- [ ] Los **dos** trabajos de la integración continua están en verde
- [ ] `docker compose up` levanta las dos piezas y `alembic upgrade head` corre en PostgreSQL
- [ ] `SHOW timescaledb.license;` dice `apache`, y la única hipertabla es `serie_limpia`
- [ ] No se agregó ninguna llave, token ni contraseña al repositorio

---

## 10. El texto para pegarle a Claude Code

---

Estás en el repositorio `glucy-backend`. **Lee primero cinco archivos y no empieces sin ellos:**
`CLAUDE.md`, los documentos de los pasos 1, 2 y 3, y
`docs/paso-4-postgres-timescale-y-pipeline.md`, que es el que manda.

**La rama sale de `develop`, no de `main`:**

```bash
git checkout develop && git pull origin develop
git checkout -b feature/postgres-timescale-y-pipeline
```

Es el paso más grande de la fase. Constrúyelo en este orden y **haz un commit por cada bloque**:

1. **La portabilidad.** `app/repositories/upsert.py` y los tres repositorios que hoy importan el
   `insert` de SQLite. La prueba 55 es de compilación y no necesita servidor; escríbela primero y
   míralas fallar.
2. **La tabla trece.** `SerieLimpia` en los modelos, la migración `0002`, y la hipertabla
   **solo** si el dialecto es `postgresql`. Corrige también el comentario de `_ColumnasAgregado`,
   que promete *continuous aggregates* que la edición libre no tiene.
3. **El filtro**, con numpy, y `scipy` en `requirements-dev.txt` como árbitro.
4. **La limpieza** (RF-23) y **las características** (RF-24), con los nombres y el orden exactos
   del apartado 4.
5. **Los agregados**, con `indicadores()` de la referencia.
6. **`app/pipeline.py`**, `docker-compose.yml`, `Dockerfile`, y el segundo trabajo de la
   integración continua.

Todo en **español**. Los nombres de las tablas no se traducen.

**Lo que NO tienes que hacer:**

- **No toques ninguna prueba de los pasos 1, 2 y 3.** Tienen que pasar tal como están.
- **No hagas hipertabla a `glucose_readings`** ni le cambies la llave primaria: el `uuid` solo es
  la llave de idempotencia de todo el sistema.
- **No uses continuous aggregates, ni compresión, ni `time_bucket_gapfill`**: no existen en la
  edición Apache 2 y la licencia del proyecto es esa.
- **No calcules ningún indicador clínico en SQL.** Se piden a `referencia/reglas_clinicas.py`.
- **No rellenes con cero lo que falta.** Es `NaN`.
- **No limpies ni suavices lecturas que no sean de origen `sensor`.**
- **No borres una lectura atípica**: se marca.
- **No rellenes huecos de más de 15 minutos.**
- **No agregues `actividad` ni `sueno`** al juego denso, ni un `POST /context`.
- **No pongas ningún usuario ni contraseña en `docker-compose.yml`** ni en ningún archivo que se
  suba. Salen del `.env`, que está en `.gitignore`.
- **No escribas `/predict` ni `/explain`.**

Cuando termines, **antes de decir que está hecho**: corre `pytest -q` y `ruff check .` y pega la
salida; corre el `git diff --stat` del apartado 8 y pega el resultado, que tiene que estar
**vacío**; y corre las cuatro órdenes de `docker compose` del apartado 8, pegando que la licencia
dice `apache` y que la única hipertabla es `serie_limpia`.

Y por último **abre el pull request** contra `develop`, con el cuerpo del apartado 9 en
`cuerpo.md` y las casillas marcadas solo con lo que de verdad comprobaste.
