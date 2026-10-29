"""Las lecturas de la base para `/history` y `/stats`, siempre filtradas por dueño.

Desde el paso 3 el peor error posible es devolver los datos de alguien más, y son datos de
salud (decisión 2.1 del paso 3). Por eso cada función pública lleva `usuario_uuid` como primer
parámetro después de la sesión, **sin valor por omisión**: el `WHERE usuario_uuid = :usuario`
no se puede olvidar porque es parte de la firma, no un filtro opcional.

Nada de aquí escribe: un `GET` no crea el usuario, ni toca `cuarentena`, ni los agregados
(decisión 2.9).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.tablas import Comida, DosisInsulina, LecturaGlucosa, Usuario

Cursor = tuple[datetime, UUID]


def lecturas_del_periodo(
    sesion: Session,
    usuario_uuid: UUID,
    desde: datetime,
    hasta: datetime,
    limite: int | None = None,
    cursor: Cursor | None = None,
) -> list[LecturaGlucosa]:
    """Las lecturas del usuario en `[desde, hasta)`, ordenadas por `(ts_utc, uuid)`.

    Sin `limite` devuelve todo el periodo, que es lo que `/stats` necesita para contar días.
    """
    return _del_periodo(sesion, LecturaGlucosa, usuario_uuid, desde, hasta, limite, cursor)


def comidas_del_periodo(
    sesion: Session,
    usuario_uuid: UUID,
    desde: datetime,
    hasta: datetime,
    limite: int | None = None,
    cursor: Cursor | None = None,
) -> list[Comida]:
    """Las comidas del usuario en `[desde, hasta)`, ordenadas por `(ts_utc, uuid)`."""
    return _del_periodo(sesion, Comida, usuario_uuid, desde, hasta, limite, cursor)


def dosis_del_periodo(
    sesion: Session,
    usuario_uuid: UUID,
    desde: datetime,
    hasta: datetime,
    limite: int | None = None,
    cursor: Cursor | None = None,
) -> list[DosisInsulina]:
    """Las dosis del usuario en `[desde, hasta)`, ordenadas por `(ts_utc, uuid)`."""
    return _del_periodo(sesion, DosisInsulina, usuario_uuid, desde, hasta, limite, cursor)


def umbrales_del_perfil(sesion: Session, usuario_uuid: UUID) -> tuple[float, float] | None:
    """`(umbral_hipo, umbral_hiper)` del perfil, o `None` si el perfil no ha llegado.

    Un usuario nacido en un lote existe pero tiene los umbrales nulos hasta su `POST /perfil`;
    para quien consulta eso es lo mismo que no tener perfil.
    """
    fila = sesion.execute(
        select(Usuario.umbral_hipo, Usuario.umbral_hiper).where(Usuario.uuid == usuario_uuid)
    ).one_or_none()
    if fila is None or fila.umbral_hipo is None or fila.umbral_hiper is None:
        return None
    return fila.umbral_hipo, fila.umbral_hiper


def perfil(sesion: Session, usuario_uuid: UUID) -> Usuario | None:
    """La fila de `usuarios`, o `None` si el perfil no ha llegado.

    `/predict` necesita el perfil completo y no solo los umbrales: la duración de acción de la
    insulina entra en el IOB, que es una de las características del modelo (paso 5).
    """
    return sesion.get(Usuario, usuario_uuid)


def _del_periodo(sesion, modelo, usuario_uuid, desde, hasta, limite, cursor):
    """La consulta común, con el filtro por dueño siempre puesto.

    El periodo es semiabierto, `desde <= ts_utc < hasta`, para que dos periodos seguidos no
    cuenten dos veces la lectura de la frontera.

    La paginación es por llave `(ts_utc, uuid)` y no por `offset` (decisión 2.6): mientras
    alguien pagina el teléfono sigue subiendo lotes, y con `offset` eso repite o se salta
    renglones. Se escribe con `OR`/`AND` y no con una tupla para no depender de que el motor
    sepa comparar filas.
    """
    consulta = select(modelo).where(
        modelo.usuario_uuid == usuario_uuid,
        modelo.ts_utc >= desde,
        modelo.ts_utc < hasta,
    )
    if cursor is not None:
        ts_cursor, uuid_cursor = cursor
        consulta = consulta.where(
            or_(
                modelo.ts_utc > ts_cursor,
                and_(modelo.ts_utc == ts_cursor, modelo.uuid > uuid_cursor),
            )
        )
    consulta = consulta.order_by(modelo.ts_utc, modelo.uuid)
    if limite is not None:
        consulta = consulta.limit(limite)
    return list(sesion.scalars(consulta))
