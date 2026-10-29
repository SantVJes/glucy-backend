"""Acceso a `predictions`. De esta tabla el backend es la autoridad, no el teléfono.

Guardar lo que se predijo es lo que permite comparar después la predicción con lo que de verdad
pasó, que es la mitad de la evaluación del reporte (RF-25). Sin esa fila no queda rastro de con
qué versión del modelo se contestó.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.models.tablas import Prediccion
from app.repositories.upsert import insertar


def registrar(
    sesion: Session,
    usuario_uuid: UUID,
    ts_utc: datetime,
    filas: list[dict],
) -> int:
    """Deja una fila por horizonte. Devuelve cuántas quedaron.

    Es un `upsert` sobre `(usuario_uuid, ts_utc, horizonte_min, modelo_version)`: pedir dos
    veces la predicción del mismo instante no acumula filas. Sin esa llave, una app que
    reintenta en una ventana de wifi llenaría la tabla de duplicados y el cálculo del error
    saldría pesado hacia los instantes que se consultaron más veces.
    """
    if not filas:
        return 0
    valores = [
        {
            "uuid": uuid4(),
            "usuario_uuid": usuario_uuid,
            "ts_utc": ts_utc,
            "horizonte_min": fila["horizonte_min"],
            "valor_predicho": fila["valor_predicho"],
            "modo": fila["modo"],
            "modelo_version": fila["modelo_version"],
            "confianza": None,
        }
        for fila in filas
    ]
    sentencia = (
        insertar(sesion, Prediccion)
        .values(valores)
        .on_conflict_do_nothing(
            index_elements=["usuario_uuid", "ts_utc", "horizonte_min", "modelo_version"]
        )
    )
    sesion.execute(sentencia)
    sesion.commit()
    return len(valores)
