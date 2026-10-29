"""El estado de envío de `xapi_events`, que es lo que la convierte en cola (paso 1 de la fase 6).

Revisión: 0004
Anterior: 0003
Creada: 2026-10-29

El Documento 3 fija siete columnas para `xapi_events` y deja «por definir» qué sube. Con esas
siete, la tabla es un registro de hechos y **no hay forma de saber qué falta mandar al Learning
Record Store**: un reenvío tendría que mandar todo otra vez o nada. El requisito dice que si el
LRS no responde las sentencias se encolan y se reenvían después (RF-19, RF-33), y una cola
necesita saber qué salió y qué no.

Se agregan tres columnas y se anota como contradicción **C-12** para el reporte, igual que la
tabla trece del paso 4 (C-9):

- `enviado_ts`: cuándo lo aceptó el LRS. Es una marca de tiempo y no un booleano porque el
  panel necesita saber **cuánto tardó** en salir: una cola que se vacía con tres días de
  retraso funciona y a la vez está mal.
- `motivo_rechazo`: por qué no va a salir nunca. Se llama igual que la columna de `cuarentena`
  a propósito, porque hace lo mismo: nada se descarta en silencio (RF-22).
- `intentos`: cuántas veces se intentó. Es informativo, para el panel.

**Una sentencia está en la cola cuando las dos primeras son nulas**, y nada más. Esa es la
regla entera. De ahí sale la propiedad que pide el requisito: cuando el LRS está caído **no se
toca ninguna fila**, así que una caída de una semana no gasta reintentos y las sentencias
siguen esperando. Solo un rechazo por contenido saca una sentencia de la cola, y lo hace con
su motivo escrito, porque reintentar lo mismo da lo mismo.

Son columnas normales en los dos motores: nada de TimescaleDB.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDICE = "ix_xapi_events_pendientes"


def upgrade() -> None:
    with op.batch_alter_table("xapi_events", schema=None) as lote:
        lote.add_column(sa.Column("enviado_ts", sa.DateTime(timezone=True), nullable=True))
        lote.add_column(sa.Column("intentos", sa.Integer(), nullable=False, server_default="0"))
        lote.add_column(sa.Column("motivo_rechazo", sa.String(), nullable=True))
        # La consulta de la cola es siempre «lo que no se ha enviado, lo más antiguo primero»:
        # sin índice, cada corrida recorre la tabla entera, que es la que más crece de todas
        # después de la serie.
        lote.create_index(INDICE, ["enviado_ts", "ts_utc"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("xapi_events", schema=None) as lote:
        lote.drop_index(INDICE)
        lote.drop_column("motivo_rechazo")
        lote.drop_column("intentos")
        lote.drop_column("enviado_ts")
