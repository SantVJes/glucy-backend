# CLAUDE.md — glucy-backend

Este archivo va en la raíz del repositorio `glucy-backend`. Claude Code lo lee solo al abrir el
proyecto, así que todo lo que esté aquí se aplica sin que nadie tenga que repetirlo.

---

## Qué es este repositorio

API REST y pipeline de datos de **Glucy**, un sistema que registra glucosa por tres vías, la
predice a 30 y 60 minutos y explica la predicción en español llano. Python 3.12 + FastAPI +
PostgreSQL 16 con TimescaleDB, empaquetado con Docker.

Proyecto académico (Universidad Tecmilenio, 8.º semestre) de **una sola persona**, Jesús
Santiago Velasco. Entrega final: **finales de noviembre de 2026**. Este repositorio
corresponde a la **fase 2** de siete.

Este repositorio es **uno de tres**:

| Repositorio | Qué contiene | Cómo se conecta con este |
| --- | --- | --- |
| glucy-ios | app SwiftUI con SwiftData, HealthKit, Vision, Core ML | le sube lotes por HTTP y le pide predicción, estadísticas y explicación |
| **glucy-backend** (este) | API, pipeline, base de datos, servicio de explicación | — |
| glucy-ml | entrenamiento, validación, artefactos del modelo | deja aquí el artefacto versionado que carga el servicio de predicción |

Además habla con dos piezas que **no** son de este proyecto y corren en el mismo servidor:
**Ollama con Qwen3 8B** (el modelo de lenguaje) y **Learning Locker** (el Learning Record
Store). Son software de terceros: se instalan y se consumen, no se escriben aquí.

## La regla que ordena todo lo demás

**El teléfono es el dueño del dato. Este servidor es una copia para analítica y para el
modelo, nunca la fuente.** De ahí se derivan las tres decisiones que hacen que la
sincronización no tenga que resolver conflictos:

1. El **UUID lo genera el teléfono**, no la base de datos.
2. El envío es **idempotente**: el mismo UUID dos veces no duplica.
3. **Flujo en un solo sentido por tipo de dato.** El teléfono es autoridad sobre lecturas,
   comidas, insulina y contexto; el backend lo es sobre predicciones, versiones del modelo y
   agregados. Nunca compiten por el mismo campo.

Y una cuarta que es de seguridad: **el servidor no sabe quién eres.** Solo conoce un UUID. Sin
nombre, sin apellidos, sin peso, sin correo, sin notas, sin fotografías.

## Idioma y comentarios (regla del proyecto)

- **Todo en español**: comentarios, docstrings, mensajes de commit, ramas, pull requests e
  issues.
- **Los nombres del dominio van en español** porque así están especificados y así viajan desde
  el teléfono: `mg_dl`, `contexto_comida`, `tiempo_absorcion_min`, `cuarentena`,
  `valor_predicho`. Lo que es vocabulario de la plataforma se queda como es (`router`,
  `Depends`, `session`).
- Los nombres de las tablas del backend están fijados en el Documento 3 y **no se traducen ni
  se renombran**: `usuarios`, `glucose_readings`, `meals`, `insulin_doses`, `context_events`,
  `predictions`, `alerts`, `modelos`, `cuarentena`, `agregados_horarios`,
  `agregados_diarios`, `xapi_events`. Sí, están mezclados en dos idiomas; así están
  documentados y cambiarlos rompería la correspondencia con el reporte.
- **Docstrings en los servicios y en las funciones del pipeline**, con el formato que entiende
  la documentación automática. Se documenta **el porqué**:
  ```python
  def interpolar(hueco_min: float, origen: str) -> bool:
      """Solo se interpolan huecos de hasta 15 min y solo en la serie continua (RF-23).

      Interpolar entre dos pinchazos separados por horas sería inventar datos, y un dato
      inventado que entra al entrenamiento envenena el modelo sin que nadie lo note.
      """
  ```
- Cuando una regla viene de un requisito o una decisión, **se cita su identificador**
  (`RF-22`, `D-8`, `P-06`).

## Arquitectura por capas

```
routers/       FastAPI: recibe, comprueba el token, valida el esquema, devuelve el código
               correcto. NUNCA ejecuta una consulta ni contiene lógica de negocio.
services/      pipeline de datos, servicio de predicción, servicio de explicación.
repositories/  todo el acceso a la base. El SQL y las series de tiempo viven solo aquí.
db/            PostgreSQL 16 + TimescaleDB. Ninguna capa superior escribe directamente.
```

**Cada capa habla solo con la inmediatamente inferior.** Un router nunca ejecuta una consulta;
un repositorio nunca decide una regla del producto.

```
app/
  main.py  config.py
  routers/       readings, meals, insulin, predict, explain, stats, history
  services/      pipeline/, prediccion/, explicacion/
  repositories/
  schemas/       Pydantic: lo que entra y lo que sale
  models/        SQLAlchemy o el ORM elegido
migrations/
tests/
docker-compose.yml
.env.example     los NOMBRES de las variables, ningún valor
```

## Los siete endpoints

| Endpoint | Método | Para qué |
| --- | --- | --- |
| `/readings` | POST | lote de lecturas de glucosa |
| `/meals` | POST | lote de comidas |
| `/insulin` | POST | lote de dosis |
| `/predict` | GET | predicción a 30 y 60 min **y con qué modo respondió** |
| `/explain` | POST | explicación en lenguaje natural de una predicción |
| `/stats` | GET | TIR, promedio, GMI, coeficiente de variación |
| `/history` | GET | histórico para el panel y la exportación |

Respuesta de los POST de lote, siempre con las tres listas:
`{"aceptados": [...], "duplicados": [...], "cuarentena": [...]}`.

Errores y lo que hace la app con cada uno: **400** esquema inválido, el lote no se reintenta ·
**401** token vencido, la app renueva y reintenta una vez · **409** conflicto, se trata como
duplicado · **5xx** o red caída, el lote se queda en la cola hasta la siguiente ventana de
wifi.

**`GET /predict` responde en menos de 200 ms** con el artefacto del modelo ya cargado en
memoria. `POST /explain` tarda de 1 a 3 segundos, y por eso la app lo pide en segundo plano y
nunca bloquea la pantalla.

Documentación **OpenAPI** generada por FastAPI en `/docs`: es entregable del punto 14 de la
rúbrica, no un extra.

## Validación y cuarentena

Las mismas reglas que ya corrieron en el teléfono, **otra vez aquí, porque un servidor nunca
debe confiar en lo que le mandan**: glucosa 20–600 mg/dL, marcas de tiempo en UTC y no
futuras, unicidad por UUID, carbohidratos 0–300 g, insulina 0–50 UI, absorción 30–300 min.

**Lo que no pasa va a la tabla `cuarentena` con su motivo y su carga original. Nunca se
descarta en silencio**: un dato rechazado sin rastro es una falla invisible (RF-22, casos P-05
y P-06).

## Pipeline de datos

1. Validar por esquema (Pydantic) → lo que falla, a cuarentena.
2. **Limpiar solo la señal del sensor**: atípicos por tasa de cambio > 4 mg/dL/min sostenida,
   suavizado Savitzky-Golay, interpolación de huecos **de hasta 15 minutos**. Nada de esto se
   aplica a lecturas manuales o por foto: son puntos aislados, no una serie.
3. Construir características con **dos juegos** (RF-24): el *denso* para modo sensor (rezagos
   a 5/10/15/30/60 min, primera y segunda derivada, medias móviles, COB, IOB, hora cíclica,
   día de la semana, actividad y sueño) y el *disperso* para modo sin sensor (última lectura y
   su antigüedad, carbohidratos y dosis de la comida, hora del día, promedio de los últimos
   días, contexto).
4. **COB con absorción lineal**: `carbs × (1 − t/tiempo_absorcion)`, cero pasado ese tiempo.
   No se modela la digestión (D-8, RF-24b).
5. **IOB** con la curva del perfil: tipo de insulina y duración de acción (5 h por omisión,
   rango 2–8, pico ~75 min).
6. **Cada fila conserva su origen y la versión del modelo** que la generó (RF-25).
7. **Nunca inferir una comida** que la persona no registró (RF-37, D-9).

## Servicio de explicación (la IA generativa, y lo que sí es código propio)

Es la **única** pieza que habla con el modelo de lenguaje. La app no sabe qué modelo hay del
otro lado, y cambiarlo mañana no toca ni una línea de Swift.

1. Recibe la predicción con sus valores SHAP.
2. Arma el prompt: **sistema fijo** (máximo tres frases, español llano, segunda persona;
   prohibido sugerir dosis, carbohidratos o medicamentos; prohibido diagnosticar; solo los
   datos entregados; no inventar cifras; cerrar recordando que es una estimación y que
   conviene confirmar con una medición) y **mensaje de usuario estructurado**: valor actual,
   valor predicho, horizonte, modo, umbral de hipoglucemia y las **cinco** variables con mayor
   SHAP con su contribución en mg/dL y su signo.
3. Llama a Ollama por HTTP en la red local, con **temperatura baja, tope de salida corto y
   semilla fija**, para que la misma predicción produzca siempre la misma explicación.
4. **Valida la respuesta antes de mostrarla**: si aparece un número que no venía en la
   petición, se descarta; si aparece un patrón de dosificación («unidades», «UI», «te
   inyectes», «toma»), se bloquea.
5. Cachea.
6. **Si no hay respuesta en 10 segundos, devuelve la plantilla determinista** (P-13).

Qué **se envía**: glucosa actual y predicha, horizonte y modo, umbrales, las cinco
contribuciones SHAP, COB e IOB del momento, hora del día.
Qué **no se envía nunca**: nombre, apellidos, UUID del usuario, notas, fotografías, peso, año
de nacimiento, ubicación, historial completo.

La **plantilla determinista** se arma por programa con los mismos valores SHAP y es la garantía
de que la función jamás depende de que algo externo esté encendido. Se usa también cuando la
persona desactivó el asistente y cuando la computadora está apagada.

## Seguridad

- **TLS 1.3** obligatorio; la app además hace certificate pinning.
- **JWT de corta vigencia con rotación**. La app lo guarda en el Keychain.
- **Ninguna llave, token ni cadena de conexión en el repositorio.** Variables de entorno, con
  un `.env.example` que lleva los nombres y ningún valor.
- Cifrado de disco en el servidor y respaldos cifrados diarios **con prueba de restauración**:
  un respaldo que nunca se probó no es un respaldo.
- Bitácora de accesos, e identificadores disociados en cualquier conjunto que salga del
  sistema.
- El panel de Grafana está detrás de autenticación y **no se publica en internet abierto**,
  porque aunque los datos estén seudonimizados siguen siendo datos de salud.

## Órdenes de uso diario

```bash
docker compose up -d           # levanta API, PostgreSQL con TimescaleDB y el resto
uvicorn app.main:app --reload  # desarrollo, sin contenedor
pytest -q                      # pruebas
ruff check . && ruff format .  # estilo
alembic upgrade head           # migraciones
```

SQLite sirve para arrancar (D-4); PostgreSQL con TimescaleDB cuando haya volumen. El código no
debe asumir extensiones de Timescale fuera de la capa de repositorios.

## Pruebas

`pytest` con `httpx` sobre los siete endpoints: códigos de estado, validación por esquema,
**idempotencia** (P-05: el mismo lote dos veces no crea filas nuevas), **cuarentena** (P-06:
marca de tiempo futura va a cuarentena con su motivo) y **latencia** de `/predict`.

Las reglas clínicas tienen una **referencia ejecutable** en este mismo repositorio,
`referencia/reglas_clinicas.py`: COB, IOB, indicadores y métricas, con 30 pruebas pasando. El pipeline tiene que dar los mismos números que esa referencia y que la app.

## Git

Ramas `main` (protegida, siempre verde) y `develop`, más `feature/lo-que-hace` y
`fix/lo-que-arregla`. Commits con **Conventional Commits en español**. Un pull request por
funcionalidad con qué se veía antes y qué se ve después. Un issue por requisito, etiquetado con
su fase. GitHub Actions corre pruebas y análisis estático en cada pull request.

## Dónde está el resto de la documentación

Carpeta `glucy-base` en los archivos del proyecto de Claude: `00-CONTEXTO-GLUCY.md` (el panorama y la
tabla de constantes), `02-glucy-backend.md` (las doce tablas campo por campo y el detalle de
cada endpoint), `04-PLAN-FASE-1.md` y `05-PENDIENTES-Y-CONTRADICCIONES.md`. La fuente es
`Glucy - Reporte del Avance 1.pdf`.

## Aviso que va en el README

Glucy **no es un dispositivo médico certificado**. El sistema informa; nunca prescribe ni
administra, y **jamás calcula ni sugiere una dosis de insulina**.
