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
| `tests/` | pytest con httpx |
| `docs/` | arquitectura, API, base de datos, modelos, pruebas y privacidad |

## Las reglas clínicas, en un solo lugar

[`referencia/reglas_clinicas.py`](referencia/reglas_clinicas.py) implementa validación,
carbohidratos activos, insulina activa, tiempo en rango, GMI, decisión de modo, zonas de
Clarke y las métricas del modelo, con **30 pruebas** que nombran el caso del reporte al que
corresponden. Es la referencia contra la que se comparan la aplicación iOS y el
entrenamiento: **si el Swift y esto no coinciden, uno de los dos está mal.**

## Estado

Fase 0 terminada: repositorio con su estructura, su `CLAUDE.md`, su integración continua y su
documentación base. **La construcción empieza en la fase 1.** El plan completo, con las siete
fases repartidas hasta finales de noviembre de 2026, está en la base de documentación del
proyecto.

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
