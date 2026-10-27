# La API de Glucy. La base es otro servicio de docker-compose.yml (TimescaleDB, edición libre).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/glucy

# Primero las dependencias, para que un cambio en el código no las vuelva a instalar.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY migrations ./migrations
COPY referencia ./referencia
COPY scripts ./scripts
COPY app ./app

# Sin privilegios: el proceso de la API no necesita ser root.
RUN useradd --create-home --uid 1000 glucy
USER glucy

EXPOSE 8000

# Las migraciones antes de servir. depends_on con service_healthy garantiza que la base ya
# acepta conexiones; sin eso, alembic fallaría y parecería un error de migración.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
