# Paso 3 de la fase 2 — El historial y las estadísticas

Escrito el 24 de octubre de 2026, después de fusionar el paso 2. Lee antes `CLAUDE.md`,
`docs/paso-1-base-de-datos-y-readings.md` y `docs/paso-2-comidas-insulina-y-perfil.md`: sus
decisiones siguen vigentes y este documento no las vuelve a discutir.

---

## 0. Antes de abrir Claude Code

```bash
cd glucy-backend
git checkout develop && git pull origin develop
git checkout -b feature/historial-y-estadisticas
```

**La rama sale de `develop` y el pull request va contra `develop`.**

Lo que dejaron los pasos 1 y 2, y se reusa: los cuatro endpoints (`/readings`, `/meals`,
`/insulin`, `/perfil`), el reparto en tres listas con su descriptor, `FechaUtc`, y las cuatro
validaciones en `referencia/reglas_clinicas.py`. **152 pruebas en verde.**

## 1. Qué se construye

`GET /history` y `GET /stats`, los dos primeros endpoints de **lectura** del proyecto. Con eso
quedan seis de los ocho; faltan `/predict` (paso 5) y `/explain` (paso 6).

Son dos endpoints pequeños con una trampa grande cada uno: el primero puede enseñar datos de
otra persona, y el segundo puede enseñar cifras que no significan nada.

## 1 bis. Los requisitos, pegados

### RF-21, la parte que toca

> `/stats` GET TIR, promedio, GMI, coeficiente de variación del periodo · `/history` GET
> histórico para el panel y la exportación.

### El `docstring` de `indicadores` en la referencia, que es la regla real

> TIR, TBR, TAR, promedio, desviación, CV y GMI. GMI = 3.31 + 0.02392 × glucosa media en
> mg/dL. El TIR se calcula sobre el rango objetivo 70-180; el TBR y el TAR sobre los umbrales
> del perfil, que la persona puede cambiar.
>
> La pantalla de historial dice **sobre cuántas lecturas** se calculó, y **no calcula nada con
> menos de tres días de datos: una cifra sobre cuatro lecturas engaña.**

### Lo que `ConsultarHistorial.swift` ya hace en el teléfono, y es la referencia de verdad

> Lo que decide es **cuándo se enseña cada cifra**, que es donde un indicador bien calculado
> puede engañar: con dos días de lecturas un tiempo en rango describe un día suelto, y un GMI
> sobre seis pinchazos sale igual de bonito y no significa nada.

### La regla de seguridad del proyecto

> **El servidor no sabe quién eres.** Solo conoce un UUID. Y el panel de Grafana está detrás de
> autenticación y no se publica en internet abierto, porque aunque los datos estén
> seudonimizados **siguen siendo datos de salud**.

---

## 2. Las nueve decisiones del paso 3

### 2.1 Es el primer `GET`, así que lo primero es que nadie vea la serie de otra persona

Hasta ahora el servidor solo escribía, y el peor error posible era guardar mal. Desde este paso
el peor error posible es **devolver los datos de alguien más**, y son datos de salud.

Por eso:

- **Toda consulta se filtra por el `usuario_uuid` del token**, en el repositorio, no en el
  router ni en el servicio. Un `WHERE usuario_uuid = :usuario` que no se puede olvidar porque
  es parte de la firma de la función, no un parámetro opcional.
- **Ningún endpoint de lectura acepta un `usuario_uuid` por parámetro.** Ni como filtro «de
  administración», ni para el panel. El panel del paso 4 lee la base directamente, no por aquí.
- Hay **una prueba con dos usuarios** que sube datos con los dos tokens y comprueba que cada
  uno ve solo lo suyo, y que el conteo de la respuesta coincide con lo que ese usuario subió.

Esa prueba no es una formalidad: es la única que falla si alguien «simplifica» el repositorio.

### 2.2 Las cifras no se enseñan si no significan nada, y esa regla vive en la referencia

El Swift ya la tiene y el Python **no**:

| Puerta | Valor | Qué pasa debajo |
| --- | --- | --- |
| `diasMinimosIndicadores` | **3 días** con al menos una lectura | `indicadores` es `nil`; la pantalla dice qué falta, **no un cero** |
| `diasMinimosGmi` | **14 días** | se calculan los indicadores pero el **GMI no se reporta** |

`indicadores()` de la referencia calcula con cualquier lista no vacía, así que **el `docstring`
promete una regla que el código no implementa**. Eso es una errata: hay que arreglarla, no
copiarla.

Decisión: **las dos puertas se agregan a `referencia/reglas_clinicas.py`** como constantes y
dos funciones de una línea, y `/stats` las usa:

```python
DIAS_MINIMOS_INDICADORES = 3   # igual que ConfiguracionDominio.diasMinimosIndicadores
DIAS_MINIMOS_GMI = 14          # igual que ConfiguracionDominio.diasMinimosGmi


def hay_suficientes_dias(dias_con_lecturas: int) -> bool: ...
def gmi_es_fiable(dias_con_lecturas: int) -> bool: ...
```

**No se cambia la firma ni el valor de retorno de `indicadores`**: eso rompería las 30 pruebas
de la referencia y el Swift que ya la espeja. Las dos funciones nuevas son aditivas, y el
`docstring` se corrige para decir dónde vive la puerta.

### 2.3 Los días se cuentan por el día local de cada lectura, no por día UTC

`ConsultarHistorial` en Swift cuenta los días así: `Set(delPeriodo.map(DiaTipico.diaLocal))`, y
`diaLocal` usa **la zona horaria guardada con cada lectura**, con GMT de respaldo si el
identificador no se puede leer.

Si el servidor contara días UTC, una lectura de las 19:00 en Monterrey —01:00 UTC del día
siguiente— caería en otro día que en el teléfono. **Y los días deciden si las cifras se
enseñan o no**, así que el teléfono mostraría el tiempo en rango y el panel diría que faltan
datos, con la misma base.

Es exactamente el tipo de divergencia que no se nota hasta que alguien compara las dos
pantallas delante del profesor. El servidor cuenta igual: `ZoneInfo(fila.zona_horaria)` por
renglón, `.date()` en esa zona, y un conjunto.

La zona ya viene en cada fila porque la regla 5 obliga a guardarla junto al `ts_utc`. Este es
el primer sitio donde sirve de verdad.

### 2.4 Sin perfil, umbrales por omisión, **y se dice en la respuesta**

El TIR es fijo sobre 70–180. El **TBR y el TAR** usan los umbrales del perfil, que la persona
puede cambiar. Y el perfil puede no haber llegado todavía: `POST /perfil` es del paso 2 y nada
obliga a que se mande antes del primer lote.

El Swift resuelve con `actual?.umbralHipo ?? ...PorOmision` y un comentario que dice «el
historial no se cae el primer día». El servidor hace lo mismo, **y además lo declara**: la
respuesta lleva `umbrales_del_perfil: false` cuando se usaron los de omisión.

Sin ese campo, un TBR calculado con 70 cuando la persona tiene su umbral en 80 se ve idéntico a
uno correcto. Con el campo, el panel puede decir «este porcentaje usa los umbrales por omisión».

### 2.5 `desde` y `hasta` son obligatorios, y el periodo está acotado

Sin `desde`, la primera consulta al panel del paso 4 pide la serie completa de todos los
tiempos sobre una hipertabla. Así que:

- Los dos son **obligatorios**, en ISO 8601 **con offset** (la misma regla 2.10 del paso 1), y
  si falta uno es `400`.
- `desde < hasta`, o `400`.
- El periodo máximo es **90 días** en `/history` y **90 días** en `/stats`. Los periodos que la
  app pide son 7, 14 y 30 (`periodosHistorialDias`), así que 90 deja margen y no es un número
  inventado al aire.
- Un `hasta` en el futuro **se acepta** y no devuelve nada de más: no es un dato que se guarde,
  es un extremo de consulta, y rechazarlo obligaría al teléfono a redondear relojes.

### 2.6 La paginación es por cursor, no por `offset`

`/history` de 90 días de sensor son hasta 25 920 lecturas. Hay que paginar, y **no con
`offset`**: mientras alguien pagina, el teléfono sigue subiendo lotes, y con `offset` eso
**repite o se salta renglones** sin que nadie lo note.

El cursor es `(ts_utc, uuid)` del último renglón devuelto, opaco para quien consume
—se devuelve en `siguiente` y se manda de vuelta tal cual—, y el orden es `ts_utc` ascendente
con `uuid` para desempatar, porque dos lecturas pueden compartir la marca de tiempo.
`limite` por omisión 200, máximo 1000.

Cuando ya no hay más, `siguiente` es `null`. Esa es la señal de fin, no «vino menos de
`limite`»: con un límite exacto el último lote legítimamente trae `limite` renglones.

### 2.7 `/history` devuelve lo que se subió, con la forma de su tabla

Tres series —`lecturas`, `comidas`, `dosis`—, y cada renglón son **las columnas de su tabla**,
las mismas que se aceptaron al subir. La simetría no es estética: el teléfono y el panel ya
saben leer esa forma, y cualquier campo nuevo aquí sería un dato que el servidor se inventó.

No lleva nota, ni nombre, ni foto, porque **el servidor no los tiene**. Y no lleva `cuarentena`:
lo rechazado se consulta en el panel del paso 4, no por un endpoint que el teléfono usa para
pintar gráficas.

`que` es un parámetro opcional (`lecturas`, `comidas`, `dosis`, o varias separadas por coma)
para no bajar las tres series cuando la pantalla solo dibuja una.

### 2.8 Este es el paso que se habría caído sin el arreglo del paso 2

Vale decirlo porque es la justificación de haberlo hecho antes: **toda consulta de aquí compara
y ordena marcas de tiempo**. Con las fechas volviendo de SQLite sin zona, el primer
`fila.ts_utc < hasta` habría levantado `TypeError`, y el primer intento de agrupar por día local
habría sido imposible sin inventarse la zona.

Ahora `FechaUtc` las devuelve en UTC con zona, y la respuesta las serializa en ISO 8601 con `Z`.
Cada renglón lleva además su `zona_horaria`, igual que al subir (regla 5).

### 2.9 Los `GET` no escriben nada, ni una fila de bitácora

Ninguna de las dos consultas crea el usuario si no existe —eso solo lo hace un lote del paso
1—, ni escribe en `cuarentena`, ni actualiza `agregados_horarios`. Un usuario que no existe
devuelve series vacías e `indicadores: null`, no un `404`: para quien consulta, «no tengo datos
tuyos» y «no existes» son la misma cosa, y distinguirlas le diría a un tercero con un token
válido si un UUID está dado de alta.

Las tablas de agregados siguen vacías. Se llenan con TimescaleDB en el paso 4.

---

## 3. Archivos que hay que crear o tocar

```
referencia/reglas_clinicas.py      TOCAR: + DIAS_MINIMOS_INDICADORES, DIAS_MINIMOS_GMI,
                                   hay_suficientes_dias, gmi_es_fiable, y la errata del
                                   docstring de indicadores (decisión 2.2)
tests/test_reglas_clinicas.py      TOCAR: pruebas de las dos puertas
app/schemas/consultas.py           NUEVO: Periodo (desde/hasta/limite/cursor) y las respuestas
app/repositories/consultas.py      NUEVO: las lecturas de la base, filtradas por usuario
app/services/estadisticas.py       NUEVO: arma /stats con la referencia, no recalcula nada
app/services/historial.py          NUEVO: arma /history y el cursor
app/routers/history.py             NUEVO
app/routers/stats.py               NUEVO
app/main.py                        TOCAR: montar los dos routers
docs/api.md                        TOCAR: los dos endpoints, con sus parámetros
tests/test_history.py  tests/test_stats.py  tests/test_aislamiento.py   NUEVOS
```

**No se toca ninguna prueba de los pasos 1 y 2**, por lo mismo que en el paso 2: son el testigo
de que nada cambió de comportamiento. `git diff --stat develop -- tests/` solo debe mostrar los
tres archivos nuevos y `test_reglas_clinicas.py`.

## 4. Las firmas, exactas

### La referencia

```python
DIAS_MINIMOS_INDICADORES = 3   # = ConfiguracionDominio.diasMinimosIndicadores
DIAS_MINIMOS_GMI = 14          # = ConfiguracionDominio.diasMinimosGmi


def hay_suficientes_dias(dias_con_lecturas: int) -> bool:
    """Con menos de tres días distintos, un tiempo en rango describe un día suelto.

    Quien consulta tiene que decir que faltan datos, no mostrar un cero (RF-16). La puerta
    vive aquí y no en el servidor para que el teléfono, el backend y el entrenamiento la
    tengan en el mismo sitio.
    """
    return dias_con_lecturas >= DIAS_MINIMOS_INDICADORES


def gmi_es_fiable(dias_con_lecturas: int) -> bool:
    """El GMI estima la hemoglobina glucosilada, que resume semanas. Con seis pinchazos sale
    igual de bonito y no significa nada."""
    return dias_con_lecturas >= DIAS_MINIMOS_GMI
```

### `app/schemas/consultas.py`

```python
MAX_DIAS_PERIODO = 90
LIMITE_POR_OMISION = 200
LIMITE_MAXIMO = 1000


class Periodo(BaseModel):
    """Los parámetros comunes a las dos consultas. Los dos extremos son obligatorios: sin
    `desde`, la primera consulta del panel pide la serie completa (decisión 2.5)."""

    desde: AwareDatetime
    hasta: AwareDatetime

    @model_validator(mode="after")
    def comprobar(self) -> "Periodo": ...   # desde < hasta, y no más de 90 días


class Indicadores(BaseModel):
    n: int
    promedio: float
    desviacion: float
    coeficiente_variacion: float
    tir: float
    tbr: float
    tar: float
    gmi: float | None          # None cuando hay menos de 14 días (decisión 2.2)


class RespuestaStats(BaseModel):
    desde: datetime
    hasta: datetime
    dias_con_lecturas: int
    indicadores: Indicadores | None       # None con menos de 3 días: faltan datos, no un cero
    umbrales_del_perfil: bool            # False si se usaron los de omisión (decisión 2.4)
    umbral_hipo: float
    umbral_hiper: float
```

`indicadores: None` y `gmi: None` son dos cosas distintas y las dos tienen que poder viajar:
«no hay con qué calcular» y «calculé todo menos el GMI».

### `app/repositories/consultas.py`

```python
def lecturas_del_periodo(
    sesion: Session, usuario_uuid: UUID, desde: datetime, hasta: datetime,
    limite: int | None = None, cursor: tuple[datetime, UUID] | None = None,
) -> list[LecturaGlucosa]:
    """Las lecturas del usuario en el periodo, ordenadas por (ts_utc, uuid).

    `usuario_uuid` es el primer parámetro y no tiene valor por omisión: el filtro por dueño no
    se puede olvidar (decisión 2.1). Sin `limite` devuelve todo el periodo, que es lo que
    /stats necesita para contar días.
    """
```

Lo mismo para `comidas_del_periodo` y `dosis_del_periodo`. **Las tres con el usuario como
primer parámetro obligatorio.**

### `app/services/estadisticas.py`

```python
def calcular(sesion: Session, usuario_uuid: UUID, periodo: Periodo) -> RespuestaStats:
    """Arma /stats. No calcula ningún indicador por su cuenta: los pide a la referencia.

    Si el servidor y el teléfono pudieran dar números distintos para los mismos datos, algún
    día los darían.
    """
```

El orden de dentro:

1. Leer las lecturas del periodo (sin límite: hay que contar días).
2. **Contar días locales** con la zona de cada renglón (decisión 2.3).
3. `hay_suficientes_dias(dias)` → si no, devolver `indicadores=None` y terminar.
4. Leer los umbrales del perfil; si no hay perfil, los de omisión y `umbrales_del_perfil=False`.
5. `indicadores(valores, umbral_hipo, umbral_hiper)` de la referencia.
6. `gmi_es_fiable(dias)` → si no, `gmi=None` en la respuesta, **sin tocar el resto**.

---

## 5. Los dos endpoints

```
GET /stats?desde=2026-10-01T00:00:00Z&hasta=2026-10-24T00:00:00Z
Authorization: Bearer <jwt>
→ 200
{ "desde": "2026-10-01T00:00:00Z", "hasta": "2026-10-24T00:00:00Z",
  "dias_con_lecturas": 21,
  "indicadores": { "n": 1843, "promedio": 142.7, "desviacion": 48.2,
                   "coeficiente_variacion": 33.8, "tir": 68.4, "tbr": 3.1,
                   "tar": 28.5, "gmi": 6.72 },
  "umbrales_del_perfil": true, "umbral_hipo": 70, "umbral_hiper": 180 }
```

Con menos de tres días:

```json
{ "desde": "…", "hasta": "…", "dias_con_lecturas": 2, "indicadores": null,
  "umbrales_del_perfil": true, "umbral_hipo": 70, "umbral_hiper": 180 }
```

Con tres días o más pero menos de catorce, **todo menos el GMI**:

```json
{ "dias_con_lecturas": 9, "indicadores": { "n": 412, "…": "…", "gmi": null }, "…": "…" }
```

```
GET /history?desde=…&hasta=…&que=lecturas,dosis&limite=200
→ 200
{ "lecturas": [ { "uuid": "…", "ts_utc": "2026-10-23T22:00:00Z",
                  "zona_horaria": "America/Monterrey", "mg_dl": 112,
                  "contexto_comida": "antes_de_comer", "origen": "sensor" } ],
  "comidas": [], "dosis": [ … ],
  "siguiente": "eyJ0cyI6…" }
```

Códigos: `200`; `400` si falta un extremo, si `desde >= hasta`, si el periodo pasa de 90 días,
si `limite` pasa de 1000 o si una fecha viene sin offset; `401` sin token o con uno vencido.
**No hay `404`** (decisión 2.9).

---

## 6. Lo que este paso NO construye

- **Ni `/predict` ni `/explain`.** Pasos 5 y 6.
- **Ni agregados, ni TimescaleDB, ni Docker, ni Grafana.** Paso 4 y fase 6. Las dos tablas de
  agregados siguen vacías y estos dos endpoints **no las leen**.
- **Ni el día típico por horas** que dibuja el teléfono: eso lo calcula el teléfono con sus
  propias lecturas, y el servidor no lo necesita para nada todavía.
- **Ni exportación en CSV.** «Histórico para el panel y la exportación» se cubre con el JSON;
  si hace falta un CSV es del panel, no de la API.
- **Ni ningún parámetro para consultar otro usuario.** Nunca (decisión 2.1).
- **Nada en la app de iOS.** Paso 7.

---

## 7. Las pruebas que tienen que pasar

Las 152 anteriores siguen pasando **sin modificarse**.

**Aislamiento** (`tests/test_aislamiento.py`) — las que de verdad importan:

37. Dos usuarios suben lecturas con sus tokens; cada `GET /history` devuelve **solo** las
    propias, y el conteo coincide con lo que cada uno subió.
38. Lo mismo con `/stats`: la `n` de cada uno es la de sus lecturas, no la suma.
39. Un `usuario_uuid` como parámetro de consulta **no cambia nada**: se ignora o es `400`,
    nunca devuelve la serie de ese usuario.

**Estadísticas** (`tests/test_stats.py`):

40. Con lecturas en **2 días** distintos → `indicadores` es `null` y `dias_con_lecturas` es 2.
41. Con lecturas en **3 días** → hay indicadores, y `gmi` es `null`.
42. Con lecturas en **14 días** → hay `gmi`, y vale `3.31 + 0.02392 × promedio`.
43. Los indicadores dan **lo mismo que `indicadores()` de la referencia** con los mismos
    valores: se compara campo por campo, no «se parece».
44. **El día local, no el UTC**: dos lecturas a las 19:00 y a las 20:00 de `America/Monterrey`
    el mismo día local —01:00 y 02:00 UTC del día siguiente— cuentan como **un** día. Esta es la
    prueba de la decisión 2.3 y la que se rompe si alguien agrupa por UTC.
45. Sin perfil → `umbrales_del_perfil: false` y los umbrales de omisión. Después de un
    `POST /perfil` con hipo 80 → `true`, y el **TBR cambia** con los mismos datos.
46. Un usuario sin ninguna lectura → `200`, `dias_con_lecturas: 0`, `indicadores: null`, y
    **no** `404`.

**Historial** (`tests/test_history.py`):

47. Tres lecturas, dos comidas y una dosis en el periodo → las tres series con sus renglones, y
    cada renglón con **exactamente** las columnas de su tabla; ninguna lleva `nota`.
48. `que=lecturas` → `comidas` y `dosis` vienen vacías y **no se consultan**.
49. Fuera del periodo no entra: una lectura un minuto antes de `desde` no aparece.
50. **El cursor**: con `limite=2` sobre 5 lecturas, paginar siguiendo `siguiente` devuelve las
    5 **una sola vez cada una**, en orden, y la última página trae `siguiente: null`.
51. **El cursor no se salta nada si llega un lote nuevo a la mitad**: se pide la primera página,
    se sube una lectura **anterior** al cursor, se pide la segunda, y las 5 originales siguen
    saliendo completas.
52. `400` por cada caso: sin `desde`, sin `hasta`, `desde >= hasta`, 91 días, `limite=1001`, y
    una fecha sin offset.
53. Las marcas de tiempo salen en ISO 8601 con `Z` y **vuelven con zona** al leerlas del JSON;
    cada renglón trae su `zona_horaria` original.

**La referencia** (`tests/test_reglas_clinicas.py`):

54. `hay_suficientes_dias` en 2, 3 y 4; `gmi_es_fiable` en 13, 14 y 15. Los límites exactos, no
    valores cómodos.

Y `ruff check .` limpio.

---

## 8. Cómo se sabe que el paso 3 está hecho

```bash
pytest -q                 # las 152 de antes más las nuevas, ninguna de las 152 modificada
ruff check .
git diff --stat develop -- tests/test_readings.py tests/test_esquema.py \
  tests/test_meals.py tests/test_insulin.py tests/test_perfil.py tests/test_fechas.py
# tiene que salir VACÍO

uvicorn app.main:app --reload
# /docs tiene que listar los seis: readings, meals, insulin, perfil, history y stats

# Y la comprobación que de verdad convence, con dos tokens distintos:
A=$(python scripts/token-de-prueba.py 11111111-1111-1111-1111-111111111111)
B=$(python scripts/token-de-prueba.py 22222222-2222-2222-2222-222222222222)
# sube una lectura con A, y después:
curl -s "localhost:8000/history?desde=2026-10-01T00:00:00Z&hasta=2026-11-01T00:00:00Z" \
  -H "Authorization: Bearer $B"
# tiene que devolver las tres series VACÍAS
```

Que el token B no vea nada de A es el criterio del paso. Si eso falla, nada más importa.

---

## 9. Git y el cuerpo del pull request

Cuatro commits: la referencia (solo, porque toca el árbitro de las reglas), los repositorios de
consulta, los dos endpoints, y las pruebas. Contra `develop`, y **sin fusionar hasta que la
integración continua esté verde de verdad**, leyendo la conclusión del run.

### Antes

El servidor recibía datos y no había forma de volver a verlos. El panel y la exportación no
tenían de dónde leer, y los indicadores del periodo solo existían dentro del teléfono.

### Después

`GET /stats` da tiempo en rango, promedio, desviación, coeficiente de variación, TBR, TAR y GMI
del periodo, **y dice cuándo una cifra no significa nada**: con menos de tres días de lecturas
no devuelve indicadores, y con menos de catorce no devuelve GMI. `GET /history` devuelve las
tres series del periodo paginadas por cursor. Las dos consultas devuelven **solo** los datos de
quien pregunta.

### Cómo

Las dos puertas que decidían qué cifra se enseña vivían solo en el Swift, y el `docstring` de
`indicadores` prometía una regla que su código no implementaba. Ahora están en
`referencia/reglas_clinicas.py` como `hay_suficientes_dias` y `gmi_es_fiable`, sin cambiar la
firma de `indicadores`, así que las 30 pruebas de la referencia siguen pasando y el teléfono, el
servidor y el entrenamiento leen el mismo número.

Los días se cuentan por **día local de cada lectura**, con la zona que viaja guardada en su
propia fila, igual que `DiaTipico.diaLocal` en Swift. Contarlos en UTC haría que una lectura de
las 19:00 en Monterrey cayera en otro día que en el teléfono, y los días deciden si las cifras
se enseñan: el teléfono mostraría el tiempo en rango y el panel diría que faltan datos con la
misma base.

El filtro por dueño es el primer parámetro obligatorio de cada función del repositorio, no un
argumento opcional, y ningún endpoint acepta un `usuario_uuid` por parámetro. La paginación es
por cursor `(ts_utc, uuid)` y no por `offset`, porque mientras alguien pagina el teléfono sigue
subiendo lotes y con `offset` eso repite o se salta renglones sin que nadie lo note.

### Requisitos que cubre

RF-21 (`/history` y `/stats`, y la OpenAPI), RF-16 (los indicadores del periodo y cuándo se
enseñan), y la errata del `docstring` de `indicadores` corregida.

### Comprobado

- [ ] Las pruebas pasan en local y el `git diff` de las pruebas de los pasos 1 y 2 sale vacío
- [ ] `ruff check .` limpio
- [ ] La integración continua está en verde
- [ ] Con dos tokens distintos, cada uno ve **solo** sus datos
- [ ] No se agregó ninguna llave, token ni dato personal al repositorio

---

## 10. El texto para pegarle a Claude Code

---

Estás en el repositorio `glucy-backend`. **Lee primero cuatro archivos y no empieces sin
ellos:** `CLAUDE.md`, `docs/paso-1-base-de-datos-y-readings.md`,
`docs/paso-2-comidas-insulina-y-perfil.md` y `docs/paso-3-historial-y-estadisticas.md`, que es
el que manda.

**La rama sale de `develop`, no de `main`:**

```bash
git checkout develop && git pull origin develop
git checkout -b feature/historial-y-estadisticas
```

Construye en este orden:

1. En `referencia/reglas_clinicas.py`: `DIAS_MINIMOS_INDICADORES = 3`, `DIAS_MINIMOS_GMI = 14`,
   `hay_suficientes_dias` y `gmi_es_fiable`, y **corrige el `docstring` de `indicadores`**, que
   promete una regla que su código no implementa. **Sin cambiar la firma ni el retorno de
   `indicadores`.** Commit aparte.
2. `app/repositories/consultas.py`, con el `usuario_uuid` como **primer parámetro obligatorio**
   de cada función.
3. `app/services/estadisticas.py` y `app/services/historial.py`, con los seis pasos que da el
   documento.
4. `GET /stats` y `GET /history`.
5. Las pruebas del apartado 7, empezando por las tres de aislamiento.

Todo en **español**. Los nombres de las tablas no se traducen.

**Lo que NO tienes que hacer:**

- **No toques ninguna prueba de los pasos 1 y 2.** Tienen que pasar tal como están.
- **No aceptes un `usuario_uuid` por parámetro de consulta en ningún endpoint**, ni «solo para
  el panel». El filtro sale del token y de ningún otro sitio.
- **No cuentes los días en UTC.** Se cuentan por día local, con la zona de cada renglón.
- **No devuelvas ceros cuando faltan datos.** `indicadores: null` con menos de tres días y
  `gmi: null` con menos de catorce.
- **No pagines con `offset`.**
- **No devuelvas `404`** cuando un usuario no tiene datos: series vacías e `indicadores: null`.
- **No calcules ningún indicador en `app/`**: se piden a la referencia.
- **No metas TimescaleDB, Docker, Grafana ni agregados**, ni `/predict`, ni `/explain`.

Cuando termines, **antes de decir que está hecho**: corre `pytest -q` y `ruff check .` y pega la
salida; corre el `git diff --stat` del apartado 8 y pega el resultado, que tiene que estar
**vacío**; y corre el `curl` con los dos tokens, pegando que el token B no ve nada de A.

Y por último **abre el pull request** contra `develop`, con el cuerpo del apartado 9 en
`cuerpo.md` y las casillas marcadas solo con lo que de verdad comprobaste.
