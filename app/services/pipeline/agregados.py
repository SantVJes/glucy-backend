"""Los agregados por hora y por día, con las reglas clínicas de la referencia (decisión 2.6).

No son *continuous aggregates*: no existen en la edición Apache 2 de TimescaleDB, y calcularían
el TIR y el GMI en SQL, una cuarta implementación de las reglas clínicas sin nada que la
compare contra `referencia/reglas_clinicas.py`. Aquí se agrupa en Python y cada grupo se le
pasa a `indicadores()`.
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta, tzinfo
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.models.tablas import AgregadoDiario, AgregadoHorario, SerieLimpia
from app.repositories import agregados as repo_agregados
from app.repositories import consultas as repo_consultas
from app.repositories import serie as repo_serie
from referencia.reglas_clinicas import (
    UMBRAL_HIPER_DEFECTO,
    UMBRAL_HIPO_DEFECTO,
    gmi_es_fiable,
    indicadores,
)

# Un día local puede empezar hasta 14 horas antes o después que el día UTC. Leyendo un día de
# más a cada lado, todo grupo que empieza dentro del periodo está completo.
MARGEN = timedelta(days=1)


def recalcular(
    sesion: Session, usuario_uuid: UUID, desde: datetime, hasta: datetime
) -> tuple[int, int]:
    """Llena agregados_horarios y agregados_diarios desde serie_limpia con la referencia.

    Devuelve cuántas filas quedaron en cada uno. El día es el día **local** de cada fila, igual
    que en /stats (decisión 2.3 del paso 3).

    - `periodo` es el inicio de la hora o del día local, guardado en UTC.
    - Solo se escriben los grupos que empiezan en `[desde, hasta)`: así un día no queda a medias
      por caer en la frontera del periodo.
    - Las filas atípicas no entran: son artefactos del sensor, marcados para no usarse.
    - El TBR y el TAR usan los umbrales del perfil, o los de omisión.
    - `gmi` queda nulo: resume semanas, y un día no las tiene (`gmi_es_fiable` con un día).
    """
    filas = [
        fila
        for fila in repo_serie.del_periodo(sesion, usuario_uuid, desde - MARGEN, hasta + MARGEN)
        if not fila.atipica
    ]
    umbral_hipo, umbral_hiper = repo_consultas.umbrales_del_perfil(sesion, usuario_uuid) or (
        UMBRAL_HIPO_DEFECTO,
        UMBRAL_HIPER_DEFECTO,
    )

    por_hora: dict[datetime, list[float]] = defaultdict(list)
    por_dia: dict[datetime, list[float]] = defaultdict(list)
    for fila in filas:
        hora, dia = _inicio_local(fila)
        por_hora[hora].append(fila.mg_dl)
        por_dia[dia].append(fila.mg_dl)

    horarios = _filas(por_hora, desde, hasta, umbral_hipo, umbral_hiper)
    diarios = _filas(por_dia, desde, hasta, umbral_hipo, umbral_hiper)
    return (
        repo_agregados.reemplazar(sesion, usuario_uuid, AgregadoHorario, desde, hasta, horarios),
        repo_agregados.reemplazar(sesion, usuario_uuid, AgregadoDiario, desde, hasta, diarios),
    )


def _inicio_local(fila: SerieLimpia) -> tuple[datetime, datetime]:
    """El inicio de la hora y del día locales de la fila, en UTC."""
    zona = _zona(fila.zona_horaria)
    local = fila.ts_utc.astimezone(zona)
    hora = datetime(local.year, local.month, local.day, local.hour, tzinfo=zona)
    dia = datetime(local.year, local.month, local.day, tzinfo=zona)
    return hora.astimezone(UTC), dia.astimezone(UTC)


def _filas(
    grupos: dict[datetime, list[float]],
    desde: datetime,
    hasta: datetime,
    umbral_hipo: float,
    umbral_hiper: float,
) -> list[dict]:
    resultado = []
    for periodo, valores in sorted(grupos.items()):
        if not desde <= periodo < hasta:
            continue
        calculados = indicadores(valores, umbral_hipo, umbral_hiper)
        resultado.append(
            {
                "periodo": periodo,
                "promedio": calculados.promedio,
                # El mínimo y el máximo no son reglas clínicas: son el rango del grupo.
                "minimo": min(valores),
                "maximo": max(valores),
                "desviacion": calculados.desviacion,
                "tir": calculados.tir,
                "tbr": calculados.tbr,
                "tar": calculados.tar,
                "gmi": calculados.gmi if gmi_es_fiable(1) else None,
            }
        )
    return resultado


def _zona(nombre: str) -> tzinfo:
    try:
        return ZoneInfo(nombre)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return UTC
