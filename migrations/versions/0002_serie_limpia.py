"""La tabla trece, `serie_limpia`, y la única hipertabla (decisiones 2.3 a 2.5 del paso 4).

Revisión: 0002
Anterior: 0001
Creada: 2026-10-25

`serie_limpia` no está en el Documento 3 (C-9): es donde el pipeline deja la señal del sensor
ya depurada, sin escribir encima del dato crudo.

La tabla se crea en los dos motores. La extensión y la hipertabla, **solo en PostgreSQL**:
`create_hypertable` no existe en SQLite, y en SQLite la migración termina con la tabla normal.

La hipertabla es `serie_limpia` y no `glucose_readings`: TimescaleDB exige que todo índice
único incluya la columna de tiempo, y la llave de `glucose_readings` es el `uuid` solo, que es
la llave de idempotencia de todo el sistema. Cambiarla a `(uuid, ts_utc)` dejaría entrar el
mismo `uuid` dos veces con marcas distintas (decisión 2.4).

Solo se usa lo de la edición Apache 2 de TimescaleDB: hipertabla con trozos de siete días. Ni
*continuous aggregates*, ni compresión, ni retención (decisión 2.6).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "serie_limpia",
        sa.Column("usuario_uuid", sa.Uuid(), nullable=False),
        sa.Column("ts_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("zona_horaria", sa.String(), nullable=False),
        sa.Column("mg_dl", sa.Double(), nullable=False),
        sa.Column("origen", sa.String(), nullable=False),
        sa.Column("atipica", sa.Boolean(), nullable=False),
        sa.Column("interpolada", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["usuario_uuid"], ["usuarios.uuid"]),
        sa.PrimaryKeyConstraint("usuario_uuid", "ts_utc"),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
        op.execute(
            "SELECT create_hypertable('serie_limpia', 'ts_utc', "
            "chunk_time_interval => INTERVAL '7 days')"
        )


def downgrade() -> None:
    # La extensión se queda: puede haber otra base usándola, y quitarla no es de esta tabla.
    op.drop_table("serie_limpia")
