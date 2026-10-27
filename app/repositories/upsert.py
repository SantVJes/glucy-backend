"""El `insert` según el motor (decisión 2.2 del paso 4).

`ON CONFLICT` no es SQL estándar, y SQLAlchemy solo lo expone en el `insert` de los dialectos
que lo tienen: el de SQLite no compila contra PostgreSQL y el genérico no trae
`on_conflict_do_nothing`. Elegirlo aquí deja los repositorios iguales en los dos motores, que
es lo que pide CLAUDE.md: lo específico de cada motor vive en `repositories/` y en ningún otro
lado.
"""

from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.models.tablas import Base

_INSERT_POR_DIALECTO = {
    "sqlite": sqlite.insert,
    "postgresql": postgresql.insert,
}


def insertar(sesion: Session, modelo: type[Base]) -> sqlite.Insert | postgresql.Insert:
    """El `insert` del dialecto de la sesión, para poder usar `on_conflict_do_nothing`.

    La idempotencia es una restricción de la base (decisión del paso 1) y `ON CONFLICT` no es
    SQL estándar: SQLAlchemy lo expone por dialecto. Los dos `Insert` tienen la misma forma
    (`on_conflict_do_nothing`, `on_conflict_do_update` con `index_elements` y `set_`, y
    `excluded`), así que quien lo usa no se entera de en qué motor está.
    """
    motor = sesion.get_bind().dialect.name
    try:
        return _INSERT_POR_DIALECTO[motor](modelo)
    except KeyError:
        raise NotImplementedError(
            f"motor sin ON CONFLICT soportado: {motor!r}; solo SQLite y PostgreSQL (D-4)"
        ) from None
