# glucy-backend

> **Glucy — «Tu glucosa, media hora antes».**
> Sistema que registra glucosa por tres vías intercambiables, la predice a 30 y 60 minutos con
> un modelo de aprendizaje automático y explica cada predicción en español llano.
> Proyecto académico de la Universidad Tecmilenio, 8.º semestre, materia Desarrollo de
> Proyectos de Aplicaciones Móviles. Autor: Jesús Santiago Velasco.

**Qué hace este repositorio:** la API REST y el pipeline de datos. Python 3.12, FastAPI, PostgreSQL 16 con TimescaleDB y Docker. Recibe los lotes que sube la aplicación, los valida, y expone la predicción, las estadísticas y la explicación en lenguaje natural.

Los otros dos: [glucy-ios](https://github.com/SantVJes/glucy-ios) ·
[glucy-backend](https://github.com/SantVJes/glucy-backend) ·
[glucy-ml](https://github.com/SantVJes/glucy-ml-)


## Cómo levantarlo

**Requisitos:** Python 3.12 y Docker.

```bash
cp .env.example .env          # y llenarlo; .env nunca se sube
docker compose up -d          # API, PostgreSQL con TimescaleDB y lo demás
# o, sin contenedor:
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

La documentación OpenAPI queda publicada en `/docs`, y es un entregable del proyecto, no un
extra.

## Variables de entorno

Están en [`.env.example`](.env.example), con **los nombres y ningún valor real**. Ninguna
llave, token ni cadena de conexión vive en el repositorio.

## Cómo correr las pruebas

```bash
pytest -q          # incluye las 30 pruebas de las reglas clínicas
ruff check .
```

## Estructura de carpetas

| Carpeta | Qué contiene |
| --- | --- |
| `app/routers/` | FastAPI: recibe, valida el esquema y responde. Sin lógica de negocio |
| `app/services/` | pipeline de datos, predicción y explicación |
| `app/repositories/` | **todo** el acceso a la base de datos |
| `app/schemas/` | Pydantic: lo que entra y lo que sale |
| `referencia/` | **las reglas clínicas como especificación ejecutable**, ver abajo |
| `grafana/` | las consultas del panel de seguimiento y el tablero que se arma con ellas |
| `simulador/` | el simulador en Streamlit (fase 4): un escenario a mano y lo que el sistema contestaría |
| `tests/` | pytest con httpx |
| `docs/` | arquitectura, API, base de datos, modelos, pruebas y privacidad |

## Las reglas clínicas, en un solo lugar

[`referencia/reglas_clinicas.py`](referencia/reglas_clinicas.py) implementa validación,
carbohidratos activos, insulina activa, tiempo en rango, GMI, decisión de modo, zonas de
Clarke y las métricas del modelo, con **30 pruebas** que nombran el caso del reporte al que
corresponden. Es la referencia contra la que se comparan la aplicación iOS y el
entrenamiento: **si el Swift y esto no coinciden, uno de los dos está mal.**

## Estado

| Fase | Qué es | Cómo va |
| --- | --- | --- |
| 1 | la app iOS autónoma | terminada, en el repositorio `glucy-ios` |
| 2 | este backend, con sus siete endpoints y el pipeline | terminada |
| 3 | predicción en vivo y explicación con SHAP | **esperando los datos de OhioT1DM** |
| 4 | el simulador en Streamlit | construido, ver [`docs/simulador.md`](docs/simulador.md) |
| 5 | validación del modo sensor, 48 h continuas | necesita un sensor comercial |
| 6 | panel de Grafana y Learning Record Store | terminada, ver [`docs/panel.md`](docs/panel.md) |
| 7 | piloto de usabilidad y documentación final | al final |

Las fases 4 y 6 se construyeron antes que la 3 porque sus dependencias reales son del backend,
no del modelo. El plan completo, con las siete fases repartidas hasta finales de noviembre de
2026, está en la base de documentación del proyecto.

## Aviso

**Glucy no es un dispositivo médico certificado.** El sistema informa; nunca prescribe ni
administra, y **jamás calcula ni sugiere una dosis de insulina**. No debe usarse como única
fuente para una decisión terapéutica. Ante cualquier síntoma hay que medir, prediga lo que
prediga la aplicación.

## Licencia y cómo citar

Licencia MIT, ver [LICENSE](LICENSE). Todo el stack del proyecto es software libre y gratuito.

> Santiago Velasco, J. (2026). *Glucy: aplicación iOS de monitoreo y predicción de glucosa con
> aprendizaje automático e inteligencia artificial generativa* [software]. Universidad
> Tecmilenio.
