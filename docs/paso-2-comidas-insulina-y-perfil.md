# Paso 2 de la fase 2 — Comidas, insulina y el perfil

Escrito el 24 de octubre de 2026, justo después de fusionar el paso 1. Lee antes `CLAUDE.md`
de este repositorio y `docs/paso-1-base-de-datos-y-readings.md`: las diez decisiones de ese
documento siguen vigentes y este paso no las vuelve a discutir.

---

## 0. Antes de abrir Claude Code

### 0.1 La rama

```bash
cd glucy-backend
git checkout develop && git pull origin develop
git checkout -b feature/comidas-insulina-y-perfil
```

**La rama sale de `develop` y el pull request va contra `develop`.** No contra `main`.

### 0.2 Qué dejó el paso 1, y se reusa tal cual

`POST /readings` funciona de punta a punta: las doce tablas sobre SQLite con Alembic, la
verificación del token, el reparto en `aceptados`, `duplicados` y `cuarentena`, y catorce
pruebas más las treinta de la referencia. **51 pruebas en verde.**

Tres cosas de ese paso que **no se tocan**: el contrato snake_case idéntico a las columnas, que
la validación se importe de `referencia/reglas_clinicas.py` en lugar de reimplementarse, y que
el esquema valide el sobre mientras las reglas validan cada renglón.

---

## 1. Qué se construye, y por qué en este orden

1. **El arreglo de las fechas.** Va primero, antes de que exista una línea que lea una marca de
   tiempo.
2. **Las tres validaciones que le faltan a la referencia**, en `referencia/reglas_clinicas.py`.
3. **La generalización del reparto en tres listas**, sin cambiar ni una de las catorce pruebas
   del paso 1.
4. **`POST /meals` y `POST /insulin`.**
5. **`POST /perfil`**, el octavo endpoint, que cierra C-7.

El orden no es negociable: los puntos 4 y 5 son copias del patrón, y si el patrón se generaliza
después de escribirlos habrá tres copias que mantener.

## 1 bis. Los requisitos y los pendientes, pegados

### C-7, del apartado 9 del paso 1

> **Los parámetros clínicos del perfil no tienen por dónde llegar al servidor.** La tabla
> `usuarios` tiene `umbral_hipo`, `umbral_hiper`, `tipo_insulina_rapida`,
> `duracion_accion_insulina`, `tipo_usuario` y `anio_nacimiento`, y el pipeline los
> **necesita**: el IOB usa la duración de acción, y la alerta se deriva comparando la
> predicción con el umbral de hipoglucemia del perfil. Pero los siete endpoints no incluyen
> ninguno para subirlos, y `PerfilDato` del teléfono no se encola nunca, a propósito, porque
> arrastra nombre, apellidos y peso. *Recomendación:* en el paso 2, un `POST /perfil` con
> **solo esos seis campos** —la «carga aparte y reducida» que el propio comentario de
> `PerfilDato.swift` ya anticipa—, y decir en el reporte que son ocho endpoints y por qué, en
> lugar de meterlo escondido en `/readings`.

### RF-22, otra vez, porque es el que manda en este paso

> Las mismas reglas que en el teléfono, otra vez aquí, **porque un servidor nunca debe confiar
> en lo que le mandan**: rango 20–600 mg/dL, marcas de tiempo en UTC y no futuras, unicidad
> por UUID, **carbohidratos 0–300 g, insulina 0–50 UI, absorción 30–300 min**.
>
> Lo que no pasa **va a `cuarentena` con su motivo y su carga original. Nunca se descarta en
> silencio.**

### Las dos reglas del proyecto que este paso roza

> **7. Nunca se calcula ni se sugiere una dosis de insulina** ni gramos a tomar. La app
> registra lo que la persona dice haberse aplicado. Es la frontera con un dispositivo médico
> regulado.
>
> **3. Lo que identifica a la persona no sube.** Nombre, apellidos, peso, notas y fotografías
> nunca salen del teléfono.

---

## 2. Las ocho decisiones del paso 2

### 2.1 Las fechas vuelven de SQLite sin zona, y se arregla antes de todo lo demás

Esto no es una sospecha. Está reproducido el 24 de octubre de 2026 sobre la rama del paso 1:

```
ts_utc leído: 2026-10-24 04:00:00 | tzinfo: None
ERROR al comparar con un datetime con offset: TypeError can't compare offset-naive and
offset-aware datetimes
```

El valor es correcto —una lectura de las 22:00 con offset −06:00 se guarda como 04:00 UTC— y lo
que falla es **al leer**: las columnas son `Mapped[datetime]`, el dialecto de SQLite devuelve un
`datetime` sin `tzinfo`, y compararlo con `datetime.now(UTC)` levanta `TypeError`. Pasa igual con
`usuarios.ts_alta` y `cuarentena.ts_recepcion`.

En el paso 1 no rompe nada porque solo escribe. **Truena en el paso 3**, donde `/history` y
`/stats` leen esas fechas, y otra vez en el pipeline del paso 4. Un error que se arregla en
veinte líneas hoy y cuesta una tarde de depuración dentro de dos semanas.

`DateTime(timezone=True)` **no basta**: SQLite lo ignora y sigue devolviendo naive. Lo que sirve
es un `TypeDecorator` propio, `FechaUtc`, en las columnas de fecha de las doce tablas.

**No hace falta una migración.** El tipo solo cambia el procesado del lado de Python; en SQLite
el DDL sigue siendo `DATETIME`, así que `0001` se queda como está y la comprobación de que el
esquema y los modelos no divergen sigue pasando.

### 2.2 La referencia está incompleta frente al Swift, y eso se cierra aquí

`referencia/reglas_clinicas.py` tiene `validar_lectura` y nada más. El Swift, en cambio, tiene
`Validacion.validarLectura`, **`validarComida`, `validarDosis` y `validarPerfil`**.

Si este paso escribe la validación de comidas en el servidor, habrá **dos** implementaciones de
la misma regla —una en Swift y otra en Python— sin una tercera que las arbitre, que es
exactamente lo que el CLAUDE.md quiere evitar. Así que el primer commit del paso **agrega
`validar_comida`, `validar_dosis` y `validar_perfil` a la referencia**, con sus pruebas en
`tests/test_reglas_clinicas.py`, copiando del Swift **el mismo orden de las comprobaciones**:
el orden decide qué motivo se reporta cuando un renglón falla por dos cosas a la vez.

Es el único caso en que se toca `referencia/`, y por eso va en su propio commit y se nombra en
el pull request.

`validar_perfil` del servidor **no lleva `nombre`, `apellidos` ni `peso_kg`**, aunque el Swift
sí los lleve. No es un olvido: esos tres campos no llegan nunca al servidor, y una firma que no
los acepta es la regla 3 escrita de forma que no se pueda romper por accidente.

### 2.3 El COB diverge entre Swift y Python con minutos negativos, y se cierra ahora

El comentario de `Validacion.validarComida` en Swift ya lo dice:

> Una comida futura llegaría a `Carbohidratos.cob` con minutos negativos. Ahí el Swift devuelve
> los carbohidratos completos y `referencia/reglas_clinicas.py` lanza: la divergencia sigue
> existiendo.

Comprobado: el Swift hace `guard minutosDesdeComida > 0 else { return carbsG }` y el Python hace
`if minutos_desde_comida < 0: raise ValueError`. Con la misma entrada, uno devuelve **todos** los
carbohidratos y el otro se cae.

**Los dos tienen que devolver `0`.** Una comida que todavía no ocurrió no tiene carbohidratos
activos; devolver los gramos completos es la respuesta más peligrosa de las tres, porque es la
única que parece un número razonable. Que ninguno de los dos pueda llegar ahí —las dos
validaciones rechazan la hora futura— no quita que el día que algo lo esquive, los dos deben
contestar lo mismo.

Hay que cambiar `cob` en la referencia, ajustar su prueba, y anotar en el pull request que la
regla cambió para que la misma línea entre en el Swift cuando le toque.

### 2.4 El reparto en tres listas se generaliza, y las catorce pruebas del paso 1 no se tocan

Tres endpoints de lote con el mismo comportamiento piden una sola función. `ingerir_lecturas`
se convierte en `ingerir(sesion, usuario_uuid, renglones, ahora, lote)`, donde `lote` describe
qué tabla, qué esquema, qué columnas y qué validación.

**La prueba de que la generalización no cambió nada es que las catorce pruebas del paso 1 pasan
sin modificarse.** Si hay que tocar una prueba para que pase, el refactor cambió el
comportamiento y hay que revisarlo, no arreglar la prueba.

Lo que **no** se abstrae: cada endpoint mantiene su propio router y su propio esquema. Un
«router genérico de lotes» parametrizado ahorra treinta líneas y hace que la OpenAPI —que es
entregable del punto 14— quede ilegible.

### 2.5 Las comidas: `carbs_g` es el total, y tres columnas viajan nulas

Las columnas de `meals` son doce. El esquema acepta **las doce menos `usuario_uuid`**, con esto:

- **Obligatorias**: `uuid`, `ts_utc`, `zona_horaria`, `carbs_g`, `origen`.
- **Opcionales**: `tiempo_absorcion_min` (si falta, 180, que es `ABSORCION_DEFECTO_MIN`),
  `porciones` (si falta, 1), `codigo_barras`, y `proteina_g`, `grasa_g`, `fibra_g`.
- **`proteina_g`, `grasa_g` y `fibra_g` van a ser siempre nulas en esta fase** porque la app no
  las captura. Se aceptan igual: son columnas del Documento 3, y el día que la app las capture
  el servidor no cambia.

**`carbs_g` son los gramos totales, ya multiplicados por las porciones.** En la app,
`Carbohidratos` los calcula como `carbsPor100g / 100 × porcionG × porciones`, y `porciones`
viaja aparte solo como información. Esto importa de verdad: si el servidor volviera a
multiplicar por `porciones`, el COB del pipeline saldría al doble o al triple y nadie lo notaría
hasta ver las métricas raras.

Lo que **no** sube, y se queda en el teléfono: `descripcion`, `nombre_producto`, `porcion_g`,
`confirmada_por_usuario`, `escrita_en_health_kit` y `nota`. No son columnas de `meals`
(decisión 2.2 del paso 1).

### 2.6 La insulina: se valida que la dosis sea anotable, no que sea la correcta

`insulin_doses` tiene siete columnas. Obligatorias: `uuid`, `ts_utc`, `zona_horaria`,
`unidades`, `tipo`. Opcional: `motivo`, que es `nil` si la persona no lo dijo y **no se
adivina**.

`validar_dosis` revisa tres cosas y ninguna más: que las unidades sean mayores que cero (cero no
es una dosis, es un campo sin llenar), que no pasen de 50 UI, y que caigan en la resolución de
**0.5 UI**. Nada más. **No opina sobre si la cantidad es la adecuada, y no existe ningún campo,
parámetro ni función en este paso que acepte una relación insulina/carbohidratos o un factor de
sensibilidad** (regla 7, contradicción C-2).

Sobre la resolución: `unidades % 0.5 != 0` es seguro aquí **porque 0.5 es exactamente
representable en binario**, al contrario que 0.1. No hace falta `Decimal`.

`tipo` es `bolo | basal` y nunca «rápida» (C-4): la etiqueta «rápida (bolo)» es de la interfaz
del teléfono y no viaja.

### 2.7 `POST /perfil` es el octavo endpoint, y lo interesante es lo que no acepta

Seis campos, los que el pipeline necesita: `tipo_usuario`, `anio_nacimiento`, `umbral_hipo`,
`umbral_hiper`, `tipo_insulina_rapida`, `duracion_accion_insulina`.

Con `extra="forbid"`, así que **`nombre`, `apellidos`, `peso_kg` y `nota` son un rechazo con
motivo legible**, no un campo que se ignora en silencio. La regla 3 deja de depender de que la
app se porte bien.

No es un lote: es **un** objeto, y es un *upsert*. El teléfono es la autoridad sobre su perfil
(flujo en un solo sentido), así que el segundo envío **actualiza** en lugar de duplicar o de
contestar `duplicados`. La respuesta devuelve los seis valores tal como quedaron guardados, para
que el teléfono confirme contra lo que mandó y no contra lo que creía haber mandado.

`tipo_usuario` admite los **cuatro** valores de `TipoUsuario` en Swift —`tipo1`,
`tipo2_insulinodependiente`, `prediabetes`, `resistencia_insulina`— y no tres (C-3).

### 2.8 Un perfil que no pasa es `400` **y** cuarentena

En un lote, un renglón malo va a cuarentena y los demás se aceptan, así que `200` es la
respuesta correcta. En `/perfil` **no hay «los demás»**: si el único objeto no pasa, no se
guardó nada, y el teléfono tiene que saber que no reintente igual. Así que **`400`**.

Y además se escribe en `cuarentena`, con `tabla_destino = "usuarios"`, porque RF-22 dice que
nada se descarta en silencio y un `400` solo vive en el teléfono. La carga se filtra por las
columnas de `usuarios` igual que en el paso 1, así que **un `nombre` que llegue por error deja
su nombre de clave en `claves_descartadas` y su contenido en ninguna parte.**

---

## 3. Archivos que hay que crear o tocar

```
referencia/reglas_clinicas.py        TOCAR: + validar_comida, validar_dosis, validar_perfil
                                     y cob deja de lanzar con minutos negativos (decisión 2.3)
tests/test_reglas_clinicas.py        TOCAR: pruebas de las tres nuevas + la de cob
app/models/tipos.py                  NUEVO: FechaUtc, el TypeDecorator
app/models/tablas.py                 TOCAR: todas las columnas de fecha pasan a FechaUtc
app/schemas/enums.py                 NUEVO: TipoInsulina, MotivoDosis, TipoUsuario
                                     y ContextoComida se mueve aquí desde schemas/lecturas.py
app/schemas/comidas.py               NUEVO: ComidaEntrada, COLUMNAS_MEALS
app/schemas/dosis.py                 NUEVO: DosisEntrada, COLUMNAS_INSULIN_DOSES
app/schemas/perfil.py                NUEVO: PerfilEntrada, PerfilGuardado, COLUMNAS_USUARIOS
app/services/ingesta.py              TOCAR: ingerir_lecturas → ingerir, con su descriptor
app/repositories/lotes.py            NUEVO: insertar_ignorando_duplicados genérico
app/repositories/lecturas.py         BORRAR: lo sustituye el genérico
app/repositories/perfil.py           NUEVO: guardar, que es un upsert
app/routers/meals.py                 NUEVO
app/routers/insulin.py               NUEVO
app/routers/perfil.py                NUEVO
app/main.py                          TOCAR: montar los tres routers
docs/api.md  docs/database.md        TOCAR: los tres endpoints nuevos y FechaUtc
tests/test_meals.py  tests/test_insulin.py  tests/test_perfil.py  tests/test_fechas.py   NUEVOS
```

**`tests/test_readings.py` y `tests/test_esquema.py` no se tocan.** Son el testigo de que la
generalización no cambió el comportamiento.

## 4. Las firmas, exactas

### `app/models/tipos.py`

```python
class FechaUtc(TypeDecorator):
    """Guarda en UTC y devuelve con zona.

    SQLite devuelve `datetime` sin `tzinfo`, y comparar eso con `datetime.now(UTC)` levanta
    `TypeError` (reproducido el 24/10/2026, decisión 2.1). `DateTime(timezone=True)` no basta
    porque SQLite lo ignora.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, valor: datetime | None, dialecto) -> datetime | None:
        if valor is None:
            return None
        if valor.tzinfo is None:
            # Suponer UTC acertaría casi siempre y desplazaría la serie el resto de las
            # veces, sin que nada falle. Mejor que truene aquí, en el código, que en los datos.
            raise ValueError("una fecha sin zona no se guarda: conviértela con astimezone(UTC)")
        return valor.astimezone(UTC)

    def process_result_value(self, valor: datetime | None, dialecto) -> datetime | None:
        if valor is None:
            return None
        return valor.replace(tzinfo=UTC) if valor.tzinfo is None else valor.astimezone(UTC)
```

**Esto no es una receta a ciegas: el tipo se escribió y se corrió antes de pedirlo**, el
24/10/2026, y da esto:

```
DDL del tipo: DATETIME            ← el mismo de antes, por eso no hace falta migración
leída: 2026-10-24 04:00:00+00:00 | tzinfo: UTC
compara con ahora: True           ← ya no levanta TypeError
naive rechazada: StatementError (builtins.ValueError) una fecha sin zona no se guarda
```

En `app/models/tablas.py`, cada columna de fecha queda así, en las doce tablas:

```python
ts_utc: Mapped[datetime] = mapped_column(FechaUtc, index=True)
```

Y en `app/services/ingesta.py` se **quita** el `astimezone(UTC)` de `_fila`: la conversión ahora
es del tipo de la columna, y en dos sitios acabaría divergiendo.

### Las tres validaciones nuevas en `referencia/reglas_clinicas.py`

Mismos rangos y **mismo orden de comprobaciones** que el Swift, porque el orden decide qué
motivo se reporta cuando un renglón falla por dos cosas:

```python
def validar_comida(
    carbs_g: float, tiempo_absorcion_min: int, porciones: float,
    ts_utc: datetime, ahora: datetime,
) -> Rechazo | None:
    """Espejo de `Validacion.validarComida` en Swift. `carbs_g` son los gramos TOTALES, ya
    multiplicados por las porciones: volver a multiplicar aquí duplicaría el COB."""
    # 1. rango 0-300 g   2. absorción 30-300 min   3. porciones > 0   4. hora no futura


def validar_dosis(unidades: float, ts_utc: datetime, ahora: datetime) -> Rechazo | None:
    """Espejo de `Validacion.validarDosis`. Revisa que la dosis sea *anotable*, no que sea la
    adecuada: eso sería dosificar (regla 7)."""
    # 1. unidades > 0   2. unidades <= 50   3. múltiplo de 0.5   4. hora no futura


def validar_perfil(
    anio_nacimiento: int, umbral_hipo: float, umbral_hiper: float,
    duracion_accion_h: float, tiempo_absorcion_min: int,
    tipo_insulina_rapida: str | None, ahora: datetime,
) -> Rechazo | None:
    """Espejo de `Validacion.validarPerfil`, **sin nombre, apellidos ni peso**: esos tres no
    llegan nunca al servidor, y una firma que no los acepta es la regla 3 hecha código."""
    # edad >= 15 y <= 120 · hipo 50-90 · hiper 140-300 · duración 2-8 h · absorción 30-300
    # · tipo de insulina de 40 caracteres como máximo
```

Las constantes ya existen en la referencia: `CARBS_MAX_G`, `INSULINA_MAX_UI`, `EDAD_MINIMA`,
`UMBRAL_HIPO_DEFECTO`. Las que falten (`CARBS_MIN_G = 0`, `INSULINA_RESOLUCION_UI = 0.5`,
`EDAD_MAXIMA = 120`, `ABSORCION_MIN_MIN = 30`, `ABSORCION_MAX_MIN = 300`,
`UMBRAL_HIPO_RANGO = (50, 90)`, `UMBRAL_HIPER_RANGO = (140, 300)`, `DIA_RANGO_H = (2, 8)`,
`TIPO_INSULINA_MAX_CARACTERES = 40`) se agregan ahí arriba, **con el mismo valor que
`ConfiguracionDominio.swift`**, y no se escriben sueltas dentro de las funciones.

### `app/services/ingesta.py`

```python
@dataclass(frozen=True)
class DescriptorDeLote:
    """Lo que cambia entre /readings, /meals y /insulin. Lo que no cambia es `ingerir`."""

    tabla: str
    esquema: type[BaseModel]
    columnas: frozenset[str]
    modelo: type[Base]
    validar: Callable[[Any, datetime], str | None]


LOTE_LECTURAS = DescriptorDeLote(...)
LOTE_COMIDAS = DescriptorDeLote(...)
LOTE_DOSIS = DescriptorDeLote(...)


def ingerir(
    sesion: Session, usuario_uuid: UUID, renglones: list[dict],
    ahora: datetime, lote: DescriptorDeLote,
) -> Resultado:
    """El mismo reparto de siempre, con el descriptor del lote como único parámetro nuevo."""
```

Los seis pasos de dentro no cambian de orden: usuario, esquema del renglón, `usuario_uuid`
ajeno, zona horaria resoluble, reglas clínicas, inserción idempotente.

### `app/repositories/lotes.py` y `app/repositories/perfil.py`

```python
def insertar_ignorando_duplicados(
    sesion: Session, modelo: type[Base], filas: list[dict[str, Any]]
) -> list[UUID]:
    """El de `lecturas.py` del paso 1, con el modelo como parámetro. Sigue siendo el único
    sitio con algo específico de SQLite."""


def guardar(sesion: Session, usuario_uuid: UUID, campos: dict[str, Any], ahora: datetime) -> dict:
    """Upsert del perfil: `ON CONFLICT (uuid) DO UPDATE` sobre los seis campos.

    El teléfono es la autoridad sobre su perfil, así que el segundo envío actualiza. No se
    toca `ts_alta`: se puso la primera vez y no vuelve a cambiar.
    """
```

---

## 5. Los tres endpoints, de arriba abajo

```
POST /meals
{ "items": [ { "uuid": "…", "ts_utc": "2026-10-24T13:10:00Z",
               "zona_horaria": "America/Monterrey", "carbs_g": 60,
               "tiempo_absorcion_min": 180, "porciones": 1,
               "codigo_barras": "7501055300014", "origen": "barcode" } ] }
→ 200 { "aceptados": ["…"], "duplicados": [], "cuarentena": [] }
```

```
POST /insulin
{ "items": [ { "uuid": "…", "ts_utc": "2026-10-24T13:12:00Z",
               "zona_horaria": "America/Monterrey", "unidades": 6.5,
               "tipo": "bolo", "motivo": "comida" } ] }
→ 200 { "aceptados": ["…"], "duplicados": [], "cuarentena": [] }
```

```
POST /perfil
{ "tipo_usuario": "tipo1", "anio_nacimiento": 2001, "umbral_hipo": 70,
  "umbral_hiper": 180, "tipo_insulina_rapida": "lispro",
  "duracion_accion_insulina": 5 }
→ 200 con los seis campos tal como quedaron guardados
→ 400 si alguno no pasa, con su motivo, y una fila en `cuarentena`
```

Los códigos de los dos lotes son los mismos cuatro del paso 1 y no hace falta repetirlos. El de
`/perfil` cambia en una cosa: **`400` también cuando el objeto no pasa las reglas**, no solo
cuando el sobre está roto, porque no hay más renglones que salvar (decisión 2.8).

---

## 6. Lo que este paso NO construye

- **Ningún `GET`.** `/history` y `/stats` son el paso 3.
- **Ni pipeline, ni limpieza de la señal, ni características, ni COB ni IOB calculados sobre lo
  guardado.** Paso 4. Aquí solo se corrige la función `cob` de la referencia.
- **Ni PostgreSQL, ni TimescaleDB, ni Docker.** Paso 4.
- **Ni emisión de tokens.** Sigue solo la verificación.
- **Ni `context_events`.** La app de la fase 1 no captura ejercicio, sueño ni estrés; la tabla
  existe desde el paso 1 y se llena cuando haya de dónde (fase 5).
- **Ni un solo campo de relación insulina/carbohidratos o factor de sensibilidad** (regla 7).
- **Nada en la app de iOS.** La cola que llama a estos endpoints es el paso 7.

---

## 7. Las pruebas que tienen que pasar

Las catorce del paso 1 siguen pasando **sin modificarse**. Estas son nuevas, numeradas a
continuación.

**Las fechas** (`tests/test_fechas.py`):

15. Ida y vuelta: se guarda una lectura con `ts_utc` de las 22:00 con offset −06:00; al leerla,
    `ts_utc` es las 04:00 **y trae `tzinfo`**, y `leida.ts_utc < datetime.now(UTC)` **no levanta
    `TypeError`**. Afirmar las tres cosas, no solo la última.
16. Lo mismo para `usuarios.ts_alta` y `cuarentena.ts_recepcion`.
17. Escribir un `datetime` sin zona desde el código **no se guarda**. Ojo con lo que hay
    que esperar: SQLAlchemy envuelve el `ValueError` del tipo, así que la prueba afirma
    `pytest.raises(StatementError)` —de `sqlalchemy.exc`— y que el mensaje del `ValueError`
    aparece en el texto. Comprobado el 24/10/2026 con el tipo ya escrito.

**Comidas** (`tests/test_meals.py`):

18. Tres comidas válidas → `200`, tres en `aceptados`, tres filas.
19. **P-05 en comidas**: el mismo lote dos veces → `duplicados`, y la cuenta de filas no cambia.
20. 301 g → cuarentena nombrando el rango; **300 exactos se aceptan**.
21. Absorción de 20 y de 400 min → cuarentena; **30 y 300 se aceptan**.
22. `porciones` en 0 → cuarentena.
23. Sin `tiempo_absorcion_min` → la fila queda con **180**.
24. Una `descripcion` o una `nota` en el cuerpo → cuarentena, **y el texto no aparece en
    `carga_original`**; solo su nombre en `claves_descartadas`.
25. `proteina_g`, `grasa_g` y `fibra_g` ausentes → la fila existe con los tres en nulo.

**Insulina** (`tests/test_insulin.py`):

26. Dos dosis válidas → `200` y dos filas.
27. 0 UI → cuarentena; 50.5 UI → cuarentena por rango; **2.3 UI → cuarentena por resolución**;
    2.5 UI se acepta.
28. `tipo` que no es `bolo` ni `basal` → cuarentena. Sin `motivo` → la fila queda con nulo.
29. **P-06 en los dos lotes nuevos**: una marca de tiempo futura va a cuarentena en `/meals` y
    en `/insulin`, con `tabla_destino` correcto en cada uno.

**Perfil** (`tests/test_perfil.py`):

30. Los seis campos se guardan y la respuesta los devuelve tal como quedaron.
31. El segundo envío con valores distintos **actualiza**: una sola fila, los valores nuevos, y
    `ts_alta` **no cambió**.
32. `nombre` en el cuerpo → `400`, una fila en `cuarentena` con `tabla_destino = "usuarios"`,
    `claves_descartadas == ["nombre"]`, y el texto del nombre **en ninguna parte de la base**.
33. Umbral hipo 40, hiper 320, duración 9 h y un año de nacimiento que da 14 años → `400` cada
    uno, con su motivo.
34. Los **cuatro** `tipo_usuario` se aceptan (C-3).

**La referencia** (`tests/test_reglas_clinicas.py`):

35. `validar_comida`, `validar_dosis` y `validar_perfil` sobre una tabla de casos con los
    límites exactos, incluidos los dos extremos de cada rango.
36. `cob` con minutos negativos devuelve **0** (la prueba que esperaba `ValueError` se cambia,
    y el cambio se nombra en el pull request).

Y `ruff check .` limpio.

---

## 8. Cómo se sabe que el paso 2 está hecho

```bash
pytest -q                 # las 51 de antes más las nuevas, y NINGUNA de las 51 modificada
ruff check .
git diff --stat develop -- tests/test_readings.py tests/test_esquema.py   # tiene que salir vacío

uvicorn app.main:app --reload
# http://127.0.0.1:8000/docs tiene que listar /readings, /meals, /insulin y /perfil

TOKEN=$(python scripts/token-de-prueba.py 11111111-1111-1111-1111-111111111111)
# El perfil primero, dos veces con distinto umbral: la segunda actualiza y no duplica.
curl -s -X POST localhost:8000/perfil -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"tipo_usuario":"tipo1","anio_nacimiento":2001,"umbral_hipo":70,"umbral_hiper":180,
       "tipo_insulina_rapida":"lispro","duracion_accion_insulina":5}'
# Y el que la regla 3 tiene que rechazar:
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/perfil \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"tipo_usuario":"tipo1","anio_nacimiento":2001,"umbral_hipo":70,"umbral_hiper":180,
       "tipo_insulina_rapida":"lispro","duracion_accion_insulina":5,"nombre":"Jesus"}'
# tiene que decir 400
```

**Que `git diff --stat` de los dos archivos de prueba del paso 1 salga vacío es el criterio más
importante de este paso**, porque es lo único que demuestra que generalizar el reparto no
cambió lo que ya funcionaba.

---

## 9. Git, y el cuerpo del pull request

```bash
git checkout develop && git pull origin develop
git checkout -b feature/comidas-insulina-y-perfil
# …trabajo…
git push -u origin feature/comidas-insulina-y-perfil
gh pr create --base develop --title "feat: comidas, insulina y el perfil" --body-file cuerpo.md
```

Cinco commits, en el orden del apartado 1: la referencia, las fechas, la generalización, los
dos lotes, el perfil. **El commit de la referencia va solo y se nombra**, porque toca el árbitro
de las reglas clínicas de los tres repositorios.

Y lo de siempre: **no fusionar hasta que la integración continua esté verde de verdad**, leyendo
la conclusión del run y no la ausencia de rojo.

### Antes

El servidor solo recibía glucosa. Las comidas y las dosis que el teléfono ya registra no tenían
a dónde subir, y los parámetros clínicos del perfil —los umbrales y la duración de acción de la
insulina, que el pipeline necesita para el IOB y para derivar la alerta— no tenían ningún
endpoint por donde llegar (C-7). Además las fechas volvían de la base sin zona, lo que habría
tronado en el primer `GET` del paso 3.

### Después

Los tres lotes del teléfono tienen su endpoint —`/readings`, `/meals` y `/insulin`— con el mismo
reparto en `aceptados`, `duplicados` y `cuarentena`. Hay un octavo endpoint, `POST /perfil`, que
acepta **solo** los seis parámetros clínicos y rechaza con un motivo legible cualquier campo que
identifique a la persona. Las fechas se guardan y se leen siempre en UTC con su zona.

### Cómo

`referencia/reglas_clinicas.py` gana `validar_comida`, `validar_dosis` y `validar_perfil`,
copiadas del Swift con el mismo orden de comprobaciones, para que no haya dos implementaciones
de la misma regla sin un árbitro. En el mismo commit, `cob` deja de lanzar con minutos negativos
y devuelve 0, que es lo que el Swift también tiene que devolver: una comida que no ha ocurrido
no tiene carbohidratos activos, y devolver los gramos completos era la respuesta peligrosa
porque parece razonable.

El reparto en tres listas se generalizó con un descriptor de lote en lugar de copiarse tres
veces, y **las catorce pruebas del paso 1 pasan sin una sola modificación**, que es lo que
demuestra que el refactor no cambió el comportamiento.

Las fechas usan un `TypeDecorator` propio que guarda en UTC y devuelve con zona.
`DateTime(timezone=True)` no servía porque SQLite lo ignora. No hace falta migración: el cambio
es del lado de Python y el DDL de `0001` se queda igual.

`POST /perfil` es un upsert, porque el teléfono es la autoridad sobre su perfil; y un perfil que
no pasa contesta `400` **y** deja su rastro en `cuarentena`, filtrado por columnas, así que un
`nombre` enviado por error deja el nombre de la clave y no su contenido.

### Requisitos que cubre

RF-21 (los tres POST de lote y el octavo endpoint), RF-22 (validación y cuarentena de comidas,
dosis y perfil), RF-14 (la dosis se registra, nunca se calcula), RF-36c (idempotencia),
**C-7 cerrado**, C-3 y C-4 respetados. Casos **P-05** y **P-06** extendidos a los dos lotes
nuevos.

### Comprobado

- [ ] Las pruebas pasan en local, y `git diff` de `tests/test_readings.py` y
      `tests/test_esquema.py` sale **vacío**
- [ ] `ruff check .` limpio
- [ ] La integración continua está en verde
- [ ] No se agregó ninguna llave, token ni dato personal al repositorio
- [ ] `curl` del perfil dos veces: la segunda actualiza y no duplica; y con `nombre`, `400`

---

## 10. El texto para pegarle a Claude Code

Lo que va de aquí abajo se pega tal cual.

---

Estás en el repositorio `glucy-backend`. **Lee primero tres archivos y no empieces sin ellos:**
`CLAUDE.md`, `docs/paso-1-base-de-datos-y-readings.md` (sus diez decisiones siguen vigentes) y
`docs/paso-2-comidas-insulina-y-perfil.md`, que es el que manda. Si algo de lo que te pido aquí
parece contradecirlo, gana el documento.

**La rama sale de `develop`, no de `main`:**

```bash
git checkout develop && git pull origin develop
git checkout -b feature/comidas-insulina-y-perfil
```

Construye **en este orden**, que no es negociable:

1. En `referencia/reglas_clinicas.py`: `validar_comida`, `validar_dosis` y `validar_perfil`,
   copiando del Swift el mismo orden de comprobaciones, y `cob` deja de lanzar con minutos
   negativos y devuelve 0. Con sus pruebas. **Commit aparte.**
2. `app/models/tipos.py` con `FechaUtc`, aplicado a las columnas de fecha de las doce tablas, y
   quita el `astimezone(UTC)` de `_fila` en `ingesta.py`. **Sin migración nueva.**
3. Generaliza `ingerir_lecturas` a `ingerir` con un descriptor de lote, y
   `repositories/lotes.py` con el insert genérico.
4. `POST /meals` y `POST /insulin`.
5. `POST /perfil`.
6. Las pruebas del apartado 7 y llena `docs/api.md` y `docs/database.md`.

Todo en **español**. Los nombres de las tablas **no se traducen ni se renombran**.

**Lo que NO tienes que hacer:**

- **No modifiques `tests/test_readings.py` ni `tests/test_esquema.py`.** Tienen que pasar tal
  como están; son la prueba de que generalizar no cambió nada. Si una falla, el refactor está
  mal: arregla el código, no la prueba.
- **No escribas ninguna migración nueva.** El tipo de las fechas es del lado de Python.
- **No reimplementes ninguna validación en `app/`**: las cuatro se importan de la referencia.
- **No metas PostgreSQL, TimescaleDB ni Docker**, ni ningún `GET`, ni pipeline.
- **No aceptes `nombre`, `apellidos`, `peso_kg` ni `nota` en ningún esquema**, y que
  `extra="forbid"` lo haga cumplir.
- **No escribas nada que calcule ni sugiera una dosis**: ni relación insulina/carbohidratos, ni
  factor de sensibilidad, ni un campo que se llame así.
- **Nada de llaves ni valores reales en `.env.example`.**

Cuando termines, **antes de decir que está hecho**: corre `pytest -q` y `ruff check .` y pega la
salida; corre `git diff --stat develop -- tests/test_readings.py tests/test_esquema.py` y pega el
resultado, que tiene que estar **vacío**; y corre los dos `curl` del apartado 8, pegando que el
segundo envío del perfil actualiza y que el que lleva `nombre` contesta `400`.

Y por último **abre el pull request** contra `develop`, con el cuerpo del apartado 9 copiado a
`cuerpo.md` y las casillas marcadas solo con lo que de verdad comprobaste. **Sin pull request la
integración continua no corre.**
