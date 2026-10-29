"""Entorno de Alembic.

La URL sale de GLUCY_DATABASE_URL y no de los ajustes completos de la app: una migración no
necesita el secreto del token, y pedírselo obligaría a ponerlo donde no hace falta.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.models.tablas import Base

config = context.config
if config.config_file_name is not None:
    # `disable_existing_loggers=False` no es decoración: por omisión `fileConfig` **apaga**
    # todos los registradores que ya existan, y como las pruebas corren `alembic upgrade head`
    # dentro del mismo proceso, eso dejaba mudos los de `app.*`. Un error que se registra y no
    # se ve es un error que no se registra.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Una URL fijada desde fuera (las pruebas lo hacen) gana a la del entorno.
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option(
        "sqlalchemy.url", os.environ.get("GLUCY_DATABASE_URL") or "sqlite:///./glucy.db"
    )

target_metadata = Base.metadata


def correr_sin_conexion() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def correr_con_conexion() -> None:
    motor = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with motor.connect() as conexion:
        # render_as_batch: SQLite no sabe alterar columnas, y las migraciones futuras lo
        # necesitarán mientras sigamos en SQLite (D-4).
        context.configure(
            connection=conexion, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    correr_sin_conexion()
else:
    correr_con_conexion()
