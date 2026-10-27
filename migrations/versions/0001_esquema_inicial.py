"""Esquema inicial: las doce tablas del Documento 3, de una vez (decisión 2.4).

Revisión: 0001
Anterior: ninguna
Creada: 2026-10-14

Aunque el paso 1 solo escribe en `usuarios`, `glucose_readings` y `cuarentena`, las doce se
crean aquí: una migración por paso son siete oportunidades de que dos no se apliquen en orden.

`agregados_horarios` y `agregados_diarios` son tablas normales, en SQLite y en PostgreSQL, y las
llena el pipeline. No son *continuous aggregates*: no existen en la edición Apache 2 de
TimescaleDB (decisión 2.6 del paso 4, que corrige lo que decía aquí).

`cuarentena.claves_descartadas` es la única columna que no está en el Documento 3 (decisión
2.6): guarda los nombres de las claves que no son columnas, nunca su contenido.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cuarentena",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ts_recepcion", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tabla_destino", sa.String(), nullable=False),
        sa.Column("carga_original", sa.JSON(), nullable=False),
        sa.Column("claves_descartadas", sa.JSON(), nullable=False),
        sa.Column("motivo_rechazo", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "modelos",
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("algoritmo", sa.String(), nullable=True),
        sa.Column("horizonte", sa.Integer(), nullable=True),
        sa.Column("fecha_entrenamiento", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rmse", sa.Double(), nullable=True),
        sa.Column("mae", sa.Double(), nullable=True),
        sa.Column("mard", sa.Double(), nullable=True),
        sa.Column("clarke_ab", sa.Double(), nullable=True),
        sa.Column("ruta_artefacto", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("version"),
    )
    op.create_table(
        "usuarios",
        sa.Column("uuid", sa.Uuid(), nullable=False),
        sa.Column("tipo_usuario", sa.String(), nullable=True),
        sa.Column("anio_nacimiento", sa.Integer(), nullable=True),
        sa.Column("umbral_hipo", sa.Double(), nullable=True),
        sa.Column("umbral_hiper", sa.Double(), nullable=True),
        sa.Column("tipo_insulina_rapida", sa.String(), nullable=True),
        sa.Column("duracion_accion_insulina", sa.Double(), nullable=True),
        sa.Column("ts_alta", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("uuid"),
    )
    op.create_table(
        "agregados_diarios",
        sa.Column("usuario_uuid", sa.Uuid(), nullable=False),
        sa.Column("periodo", sa.DateTime(timezone=True), nullable=False),
        sa.Column("promedio", sa.Double(), nullable=True),
        sa.Column("minimo", sa.Double(), nullable=True),
        sa.Column("maximo", sa.Double(), nullable=True),
        sa.Column("desviacion", sa.Double(), nullable=True),
        sa.Column("tir", sa.Double(), nullable=True),
        sa.Column("tbr", sa.Double(), nullable=True),
        sa.Column("tar", sa.Double(), nullable=True),
        sa.Column("gmi", sa.Double(), nullable=True),
        sa.ForeignKeyConstraint(
            ["usuario_uuid"],
            ["usuarios.uuid"],
        ),
        sa.PrimaryKeyConstraint("usuario_uuid", "periodo"),
    )
    op.create_table(
        "agregados_horarios",
        sa.Column("usuario_uuid", sa.Uuid(), nullable=False),
        sa.Column("periodo", sa.DateTime(timezone=True), nullable=False),
        sa.Column("promedio", sa.Double(), nullable=True),
        sa.Column("minimo", sa.Double(), nullable=True),
        sa.Column("maximo", sa.Double(), nullable=True),
        sa.Column("desviacion", sa.Double(), nullable=True),
        sa.Column("tir", sa.Double(), nullable=True),
        sa.Column("tbr", sa.Double(), nullable=True),
        sa.Column("tar", sa.Double(), nullable=True),
        sa.Column("gmi", sa.Double(), nullable=True),
        sa.ForeignKeyConstraint(
            ["usuario_uuid"],
            ["usuarios.uuid"],
        ),
        sa.PrimaryKeyConstraint("usuario_uuid", "periodo"),
    )
    op.create_table(
        "context_events",
        sa.Column("uuid", sa.Uuid(), nullable=False),
        sa.Column("usuario_uuid", sa.Uuid(), nullable=False),
        sa.Column("ts_inicio", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ts_fin", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clase", sa.String(), nullable=True),
        sa.Column("intensidad", sa.String(), nullable=True),
        sa.Column("calidad", sa.String(), nullable=True),
        sa.Column("origen", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["usuario_uuid"],
            ["usuarios.uuid"],
        ),
        sa.PrimaryKeyConstraint("uuid"),
    )
    with op.batch_alter_table("context_events", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_context_events_ts_inicio"), ["ts_inicio"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_context_events_usuario_uuid"), ["usuario_uuid"], unique=False
        )

    op.create_table(
        "glucose_readings",
        sa.Column("uuid", sa.Uuid(), nullable=False),
        sa.Column("usuario_uuid", sa.Uuid(), nullable=False),
        sa.Column("ts_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("zona_horaria", sa.String(), nullable=False),
        sa.Column("mg_dl", sa.Double(), nullable=False),
        sa.Column("contexto_comida", sa.String(), nullable=True),
        sa.Column("origen", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["usuario_uuid"],
            ["usuarios.uuid"],
        ),
        sa.PrimaryKeyConstraint("uuid"),
    )
    with op.batch_alter_table("glucose_readings", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_glucose_readings_ts_utc"), ["ts_utc"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_glucose_readings_usuario_uuid"), ["usuario_uuid"], unique=False
        )

    op.create_table(
        "insulin_doses",
        sa.Column("uuid", sa.Uuid(), nullable=False),
        sa.Column("usuario_uuid", sa.Uuid(), nullable=False),
        sa.Column("ts_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("zona_horaria", sa.String(), nullable=True),
        sa.Column("unidades", sa.Double(), nullable=True),
        sa.Column("tipo", sa.String(), nullable=True),
        sa.Column("motivo", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["usuario_uuid"],
            ["usuarios.uuid"],
        ),
        sa.PrimaryKeyConstraint("uuid"),
    )
    with op.batch_alter_table("insulin_doses", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_insulin_doses_ts_utc"), ["ts_utc"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_insulin_doses_usuario_uuid"), ["usuario_uuid"], unique=False
        )

    op.create_table(
        "meals",
        sa.Column("uuid", sa.Uuid(), nullable=False),
        sa.Column("usuario_uuid", sa.Uuid(), nullable=False),
        sa.Column("ts_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("zona_horaria", sa.String(), nullable=True),
        sa.Column("carbs_g", sa.Double(), nullable=True),
        sa.Column("tiempo_absorcion_min", sa.Integer(), nullable=True),
        sa.Column("proteina_g", sa.Double(), nullable=True),
        sa.Column("grasa_g", sa.Double(), nullable=True),
        sa.Column("fibra_g", sa.Double(), nullable=True),
        sa.Column("codigo_barras", sa.String(), nullable=True),
        sa.Column("porciones", sa.Double(), nullable=True),
        sa.Column("origen", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["usuario_uuid"],
            ["usuarios.uuid"],
        ),
        sa.PrimaryKeyConstraint("uuid"),
    )
    with op.batch_alter_table("meals", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_meals_ts_utc"), ["ts_utc"], unique=False)
        batch_op.create_index(batch_op.f("ix_meals_usuario_uuid"), ["usuario_uuid"], unique=False)

    op.create_table(
        "predictions",
        sa.Column("uuid", sa.Uuid(), nullable=False),
        sa.Column("usuario_uuid", sa.Uuid(), nullable=False),
        sa.Column("ts_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("horizonte_min", sa.Integer(), nullable=True),
        sa.Column("valor_predicho", sa.Double(), nullable=True),
        sa.Column("modo", sa.String(), nullable=True),
        sa.Column("modelo_version", sa.String(), nullable=True),
        sa.Column("confianza", sa.Double(), nullable=True),
        sa.ForeignKeyConstraint(
            ["usuario_uuid"],
            ["usuarios.uuid"],
        ),
        sa.PrimaryKeyConstraint("uuid"),
    )
    with op.batch_alter_table("predictions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_predictions_ts_utc"), ["ts_utc"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_predictions_usuario_uuid"), ["usuario_uuid"], unique=False
        )

    op.create_table(
        "xapi_events",
        sa.Column("uuid", sa.Uuid(), nullable=False),
        sa.Column("usuario_uuid", sa.Uuid(), nullable=False),
        sa.Column("ts_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor", sa.JSON(), nullable=True),
        sa.Column("verbo", sa.String(), nullable=True),
        sa.Column("objeto", sa.JSON(), nullable=True),
        sa.Column("resultado", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["usuario_uuid"],
            ["usuarios.uuid"],
        ),
        sa.PrimaryKeyConstraint("uuid"),
    )
    with op.batch_alter_table("xapi_events", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_xapi_events_usuario_uuid"), ["usuario_uuid"], unique=False
        )

    op.create_table(
        "alerts",
        sa.Column("uuid", sa.Uuid(), nullable=False),
        sa.Column("usuario_uuid", sa.Uuid(), nullable=False),
        sa.Column("prediccion_uuid", sa.Uuid(), nullable=True),
        sa.Column("ts_emision", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tipo", sa.String(), nullable=True),
        sa.Column("ts_respuesta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accion", sa.String(), nullable=True),
        sa.Column("resulto_real", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(
            ["prediccion_uuid"],
            ["predictions.uuid"],
        ),
        sa.ForeignKeyConstraint(
            ["usuario_uuid"],
            ["usuarios.uuid"],
        ),
        sa.PrimaryKeyConstraint("uuid"),
    )
    with op.batch_alter_table("alerts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_alerts_usuario_uuid"), ["usuario_uuid"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("alerts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_alerts_usuario_uuid"))

    op.drop_table("alerts")
    with op.batch_alter_table("xapi_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_xapi_events_usuario_uuid"))

    op.drop_table("xapi_events")
    with op.batch_alter_table("predictions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_predictions_usuario_uuid"))
        batch_op.drop_index(batch_op.f("ix_predictions_ts_utc"))

    op.drop_table("predictions")
    with op.batch_alter_table("meals", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_meals_usuario_uuid"))
        batch_op.drop_index(batch_op.f("ix_meals_ts_utc"))

    op.drop_table("meals")
    with op.batch_alter_table("insulin_doses", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_insulin_doses_usuario_uuid"))
        batch_op.drop_index(batch_op.f("ix_insulin_doses_ts_utc"))

    op.drop_table("insulin_doses")
    with op.batch_alter_table("glucose_readings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_glucose_readings_usuario_uuid"))
        batch_op.drop_index(batch_op.f("ix_glucose_readings_ts_utc"))

    op.drop_table("glucose_readings")
    with op.batch_alter_table("context_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_context_events_usuario_uuid"))
        batch_op.drop_index(batch_op.f("ix_context_events_ts_inicio"))

    op.drop_table("context_events")
    op.drop_table("agregados_horarios")
    op.drop_table("agregados_diarios")
    op.drop_table("usuarios")
    op.drop_table("modelos")
    op.drop_table("cuarentena")
