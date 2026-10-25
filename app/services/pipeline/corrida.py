"""Una corrida del pipeline para un usuario y un periodo (decisión 2.11 del paso 4).

Limpia las lecturas del periodo (RF-23), deja la serie en `serie_limpia` y recalcula los dos
agregados. Las características (RF-24) no se guardan: se construyen cuando se necesitan, con
`caracteristicas.py`, en el entrenamiento y en `/predict` (paso 5).
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.repositories import consultas as repo_consultas
from app.repositories import serie as repo_serie
from app.services.pipeline import agregados
from app.services.pipeline.limpieza import limpiar


@dataclass(frozen=True)
class Resumen:
    lecturas: int
    serie: int
    interpoladas: int
    atipicas: int
    horarios: int
    diarios: int


def correr(sesion: Session, usuario_uuid: UUID, desde: datetime, hasta: datetime) -> Resumen:
    """Idempotente: correrla dos veces sobre el mismo periodo deja la misma `serie_limpia` y los
    mismos agregados. Un usuario sin lecturas en el periodo no escribe nada.
    """
    lecturas = repo_consultas.lecturas_del_periodo(sesion, usuario_uuid, desde, hasta)
    if not lecturas:
        return Resumen(0, 0, 0, 0, 0, 0)

    puntos = limpiar(lecturas)
    filas = [
        {
            "ts_utc": p.ts_utc,
            "zona_horaria": p.zona_horaria,
            "mg_dl": p.mg_dl,
            "origen": p.origen.value,
            "atipica": p.atipica,
            "interpolada": p.interpolada,
        }
        for p in puntos
    ]
    en_serie = repo_serie.reemplazar(sesion, usuario_uuid, desde, hasta, filas)
    horarios, diarios = agregados.recalcular(sesion, usuario_uuid, desde, hasta)
    sesion.commit()
    return Resumen(
        lecturas=len(lecturas),
        serie=en_serie,
        interpoladas=sum(p.interpolada for p in puntos),
        atipicas=sum(p.atipica for p in puntos),
        horarios=horarios,
        diarios=diarios,
    )
