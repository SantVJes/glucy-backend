"""La bitácora de las explicaciones, que es de dónde lee el panel del modelo de lenguaje.

Revisión: 0005
Anterior: 0004
Creada: 2026-10-29

El panel de Grafana pide un cuadro de **uso del modelo de lenguaje**: cuántas explicaciones
salieron, cuántas fallaron, cuántas veces salió la plantilla determinista y cuánto tardaron. No
tenía de dónde leer: el servicio de explicación cachea en memoria y no dejaba rastro en la base.

Y es justo la cifra que el reporte necesita decir. El `docstring` de `RespuestaExplicacion` ya lo
decía desde el paso 6 —«el reporte tiene que poder decir cuántas explicaciones salieron del
modelo y cuántas de la plantilla»— y no había forma de contarlas.

Es la tabla **catorce**, no está en el Documento 3, y queda anotada como **C-13** igual que
`serie_limpia` (C-9) y las columnas de la cola del LRS (C-12).

**Lo que esta tabla NO guarda**, y conviene que se vea en el DDL: ni el prompt, ni el texto de la
explicación, ni una sola cifra de glucosa. Guardar la explicación sería guardar una frase sobre
la glucosa de alguien en una tabla de diagnóstico, y el texto no hace falta para contar cuántas
veces contestó el modelo. Lo que se guarda es **si** contestó, **por qué** no, y **cuánto**
tardó.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "explicaciones",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ts_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usuario_uuid", sa.Uuid(), nullable=False),
        sa.Column("origen", sa.String(), nullable=False),
        sa.Column("motivo", sa.String(), nullable=True),
        sa.Column("modelo", sa.String(), nullable=True),
        sa.Column("duracion_ms", sa.Integer(), nullable=False),
        sa.Column("horizonte_min", sa.Integer(), nullable=True),
        sa.Column("modo", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["usuario_uuid"], ["usuarios.uuid"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("explicaciones", schema=None) as lote:
        lote.create_index(lote.f("ix_explicaciones_ts_utc"), ["ts_utc"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("explicaciones", schema=None) as lote:
        lote.drop_index(lote.f("ix_explicaciones_ts_utc"))
    op.drop_table("explicaciones")
