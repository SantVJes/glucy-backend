"""El perfil clínico: un solo objeto y un upsert (C-7, decisiones 2.7 y 2.8 del paso 2).

No es un lote. Si el único objeto no pasa no hay «los demás» que salvar, así que el rechazo
es un `400` para el teléfono **y** una fila en `cuarentena`, porque un `400` solo vive en el
teléfono y RF-22 dice que nada se descarta en silencio.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.repositories import perfil as repo_perfil
from app.schemas.perfil import COLUMNAS_USUARIOS, PerfilEntrada, PerfilGuardado
from app.services.ingesta import a_cuarentena, motivo_de_validacion
from referencia.reglas_clinicas import ABSORCION_DEFECTO_MIN, validar_perfil

TABLA_USUARIOS = "usuarios"

# En el perfil, un campo de más casi siempre es algo que identifica a la persona.
_MOTIVOS_DEL_PERFIL = {
    "extra_forbidden": "no se acepta en el perfil: lo que identifica a la persona no sube "
    "(regla 3)",
}


class PerfilRechazado(Exception):
    """El perfil no se guardó. Lleva el motivo, que ya quedó en `cuarentena`."""

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


def guardar_perfil(
    sesion: Session, usuario_uuid: UUID, cuerpo: dict[str, Any], ahora: datetime
) -> PerfilGuardado:
    """Valida el perfil y lo guarda, o deja su rastro en `cuarentena` y levanta
    `PerfilRechazado`.

    `ahora` entra como parámetro por la misma razón que en `ingerir`: la edad sale del año
    presente, y una prueba necesita poder fijarlo.
    """
    motivo = _motivo_del_rechazo(cuerpo, ahora)
    if motivo is not None:
        a_cuarentena(sesion, cuerpo, motivo, ahora, TABLA_USUARIOS, COLUMNAS_USUARIOS)
        sesion.commit()
        raise PerfilRechazado(motivo)

    perfil = PerfilEntrada.model_validate(cuerpo)
    guardado = repo_perfil.guardar(sesion, usuario_uuid, perfil.model_dump(), ahora)
    sesion.commit()
    return PerfilGuardado.model_validate(guardado)


def _motivo_del_rechazo(cuerpo: dict[str, Any], ahora: datetime) -> str | None:
    """El esquema primero, después las reglas de la referencia (no reimplementadas)."""
    try:
        perfil = PerfilEntrada.model_validate(cuerpo)
    except ValidationError as error:
        return motivo_de_validacion(error, _MOTIVOS_DEL_PERFIL)

    # El perfil del servidor no lleva tiempo de absorción: la absorción viaja con cada comida.
    # Se pasa el valor por omisión, que siempre está en rango, para que esa comprobación de
    # `validar_perfil` no decida nada aquí.
    rechazo = validar_perfil(
        perfil.anio_nacimiento,
        perfil.umbral_hipo,
        perfil.umbral_hiper,
        perfil.duracion_accion_insulina,
        ABSORCION_DEFECTO_MIN,
        perfil.tipo_insulina_rapida,
        ahora,
    )
    return rechazo.motivo if rechazo else None
