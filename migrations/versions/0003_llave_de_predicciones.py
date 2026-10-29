"""La llave natural de `predictions`, para que `/predict` sea idempotente (paso 5).

Revisión: 0003
Anterior: 0002
Creada: 2026-10-29

`predictions.uuid` es la llave primaria, pero no dice nada: lo genera el servidor en cada
respuesta. Lo que de verdad identifica una predicción es **de quién es, de qué instante, a qué
horizonte y con qué versión del modelo**, y sin esa restricción una app que reintenta en una
ventana de wifi acumularía filas del mismo instante. El cálculo del error del reporte saldría
pesado hacia los instantes que se consultaron más veces, sin que nada fallara.

Se crea en los dos motores: es un índice único normal, no tiene nada de TimescaleDB.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDICE = "ix_predictions_llave_natural"
COLUMNAS = ["usuario_uuid", "ts_utc", "horizonte_min", "modelo_version"]


def upgrade() -> None:
    with op.batch_alter_table("predictions", schema=None) as lote:
        lote.create_index(INDICE, COLUMNAS, unique=True)


def downgrade() -> None:
    with op.batch_alter_table("predictions", schema=None) as lote:
        lote.drop_index(INDICE)
