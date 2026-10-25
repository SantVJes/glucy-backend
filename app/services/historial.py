"""`/history`: las tres series del periodo, paginadas por cursor (paso 3).

Las series pedidas se mezclan en un solo orden `(ts_utc, uuid)` y el límite es del total, así
que un único cursor sirve para las tres: es el `(ts_utc, uuid)` del último renglón devuelto,
sea de la serie que sea. Los `uuid` los genera el teléfono y no se repiten entre tablas, así
que el desempate está bien definido.
"""

import heapq
from itertools import islice
from uuid import UUID

from sqlalchemy.orm import Session

from app.repositories import consultas as repo_consultas
from app.schemas.consultas import (
    ComidaGuardada,
    ConsultaHistorial,
    DosisGuardada,
    LecturaGuardada,
    RespuestaHistorial,
    codificar_cursor,
    decodificar_cursor,
)

# Qué función del repositorio y qué forma de renglón tiene cada serie.
_SERIES = {
    "lecturas": (repo_consultas.lecturas_del_periodo, LecturaGuardada),
    "comidas": (repo_consultas.comidas_del_periodo, ComidaGuardada),
    "dosis": (repo_consultas.dosis_del_periodo, DosisGuardada),
}


def consultar(
    sesion: Session, usuario_uuid: UUID, consulta: ConsultaHistorial
) -> RespuestaHistorial:
    """Arma una página de /history. No escribe nada (decisión 2.9).

    Cada serie pedida trae a lo más `limite + 1` renglones posteriores al cursor; con eso la
    mezcla de los primeros `limite` es exacta, y el renglón de más dice si hay otra página. Las
    series que no se pidieron **no se consultan**.
    """
    cursor = decodificar_cursor(consulta.cursor) if consulta.cursor else None

    por_serie = {
        nombre: leer(
            sesion,
            usuario_uuid,
            consulta.desde,
            consulta.hasta,
            limite=consulta.limite + 1,
            cursor=cursor,
        )
        for nombre, (leer, _) in _SERIES.items()
        if nombre in consulta.series
    }

    mezcla = heapq.merge(
        *(
            [(fila.ts_utc, fila.uuid, nombre, fila) for fila in filas]
            for nombre, filas in por_serie.items()
        ),
    )
    pagina = list(islice(mezcla, consulta.limite + 1))
    hay_mas = len(pagina) > consulta.limite
    pagina = pagina[: consulta.limite]

    series: dict[str, list] = {nombre: [] for nombre in _SERIES}
    for _, _, nombre, fila in pagina:
        series[nombre].append(_SERIES[nombre][1].model_validate(fila))

    ultimo = pagina[-1] if pagina and hay_mas else None
    return RespuestaHistorial(
        **series,
        siguiente=codificar_cursor(ultimo[0], ultimo[1]) if ultimo else None,
    )
