"""Ingesta de lotes: el reparto en aceptados, duplicados y cuarentena.

Aquí vive la regla y no en el router. Este paso guarda lo que llega y nada más: limpiar la
señal, construir características, COB e IOB son del pipeline del paso 4.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.repositories import cuarentena as repo_cuarentena
from app.repositories import lecturas as repo_lecturas
from app.repositories import usuarios as repo_usuarios
from app.schemas.lecturas import COLUMNAS_GLUCOSE_READINGS, LecturaEntrada
from app.schemas.lotes import RenglonEnCuarentena
from referencia.reglas_clinicas import Rechazo, validar_lectura

TABLA_LECTURAS = "glucose_readings"

# Los motivos que la app y el panel del paso 4 van a leer, en español y diciendo qué arreglar.
# Lo que no está aquí sale con el mensaje de Pydantic tal cual.
_MOTIVOS_POR_TIPO_DE_ERROR = {
    "missing": "falta el campo",
    "extra_forbidden": "no es columna de la tabla: se queda en el teléfono (decisión 2.2)",
    "timezone_aware": "marca de tiempo sin offset: tiene que traer Z o ±hh:mm (decisión 2.10)",
    "datetime_from_date_parsing": "marca de tiempo ilegible: tiene que ser ISO 8601 con offset",
    "datetime_parsing": "marca de tiempo ilegible: tiene que ser ISO 8601 con offset",
    "uuid_parsing": "uuid ilegible",
    "uuid_type": "uuid ilegible",
    "enum": "valor no permitido",
}


@dataclass(frozen=True)
class Resultado:
    aceptados: list[UUID]
    duplicados: list[UUID]
    cuarentena: list[RenglonEnCuarentena]


def ingerir_lecturas(
    sesion: Session, usuario_uuid: UUID, renglones: list[dict], ahora: datetime
) -> Resultado:
    """Reparte un lote en aceptados, duplicados y cuarentena. Aquí vive la regla.

    `ahora` entra como parámetro y no se lee de dentro: una prueba de marca de tiempo futura
    necesita poder fijar el presente.

    Cada renglón termina en exactamente una de las tres listas: nada se descarta en silencio
    (RF-22). El lote entero es una sola transacción, así que un error del servidor a la mitad
    no deja la mitad escrita y el teléfono puede reintentarlo completo.
    """
    # 1. El usuario nace en su primer contacto (decisión 2.7).
    repo_usuarios.asegurar_que_existe(sesion, usuario_uuid, ts_alta=ahora)

    cuarentena: list[RenglonEnCuarentena] = []
    sobrevivientes: list[LecturaEntrada] = []

    for renglon in renglones:
        validado = _validar_renglon(renglon, usuario_uuid, ahora)
        if isinstance(validado, str):
            _a_cuarentena(sesion, renglon, validado, ahora)
            cuarentena.append(RenglonEnCuarentena(uuid=_uuid_legible(renglon), motivo=validado))
        else:
            sobrevivientes.append(validado)

    # 6. Lo que sobrevive se inserta; lo que la base no dejó entrar es duplicado (RF-36c).
    entraron = set(
        repo_lecturas.insertar_ignorando_duplicados(
            sesion, [_fila(lectura, usuario_uuid) for lectura in sobrevivientes]
        )
    )
    aceptados: list[UUID] = []
    duplicados: list[UUID] = []
    for lectura in sobrevivientes:
        # Un uuid repetido dentro del mismo lote entra una vez: la segunda es duplicado.
        if lectura.uuid in entraron:
            entraron.discard(lectura.uuid)
            aceptados.append(lectura.uuid)
        else:
            duplicados.append(lectura.uuid)

    sesion.commit()
    return Resultado(aceptados=aceptados, duplicados=duplicados, cuarentena=cuarentena)


def _validar_renglon(
    renglon: dict[str, Any], usuario_uuid: UUID, ahora: datetime
) -> LecturaEntrada | str:
    """Pasos 2 a 5: devuelve la lectura validada, o el motivo por el que va a cuarentena."""
    # `usuario_uuid` es columna pero no campo de entrada: sale del token (decisión 2.9).
    sin_usuario = {k: v for k, v in renglon.items() if k != "usuario_uuid"}

    # 2. El esquema del renglón.
    try:
        lectura = LecturaEntrada.model_validate(sin_usuario)
    except ValidationError as error:
        return _motivo_de_validacion(error)

    # 3. Un usuario_uuid en el cuerpo igual al del token se ignora; distinto, a cuarentena.
    if "usuario_uuid" in renglon and str(renglon["usuario_uuid"]).lower() != str(usuario_uuid):
        return "usuario_uuid del cuerpo distinto del token: solo se escribe en la serie propia"

    # 4. Sin una zona resoluble la hora local es irrecuperable, y alimenta hora_sin y hora_cos.
    # ZoneInfo levanta ValueError u OSError con nombres raros («../», un directorio), no solo
    # ZoneInfoNotFoundError.
    try:
        ZoneInfo(lectura.zona_horaria)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return f"zona_horaria que no existe: {lectura.zona_horaria!r}"

    # 5. Las reglas clínicas, importadas de la referencia y no reimplementadas (decisión 2.3).
    # `glucose_readings` no guarda la confirmación del OCR, así que el servidor no puede
    # volver a comprobarla: en el teléfono nada se guarda sin confirmar (C-8).
    rechazo: Rechazo | None = validar_lectura(
        lectura.mg_dl, lectura.ts_utc, ahora, lectura.origen, confirmada_por_usuario=True
    )
    if rechazo is not None:
        return rechazo.motivo

    return lectura


def _motivo_de_validacion(error: ValidationError) -> str:
    """Un motivo legible por campo, sin repetir el valor recibido."""
    partes = []
    for detalle in error.errors():
        campo = ".".join(str(parte) for parte in detalle["loc"]) or "renglón"
        partes.append(f"{campo}: {_MOTIVOS_POR_TIPO_DE_ERROR.get(detalle['type'], detalle['msg'])}")
    return "; ".join(partes)


def _a_cuarentena(sesion: Session, renglon: dict[str, Any], motivo: str, ahora: datetime) -> None:
    """Guarda solo las claves que son columnas; de las demás, solo el nombre (decisión 2.6).

    Si una versión de la app manda una `nota` por error, guardar el renglón entero metería
    texto libre en el servidor por la puerta de atrás de una tabla de diagnóstico.
    """
    repo_cuarentena.guardar(
        sesion,
        ts_recepcion=ahora,
        tabla_destino=TABLA_LECTURAS,
        carga_original={k: v for k, v in renglon.items() if k in COLUMNAS_GLUCOSE_READINGS},
        claves_descartadas=sorted(k for k in renglon if k not in COLUMNAS_GLUCOSE_READINGS),
        motivo_rechazo=motivo,
    )


def _uuid_legible(renglon: dict[str, Any]) -> UUID | None:
    try:
        return UUID(str(renglon["uuid"]))
    except (KeyError, ValueError):
        return None


def _fila(lectura: LecturaEntrada, usuario_uuid: UUID) -> dict[str, Any]:
    """La fila de `glucose_readings`. La marca de tiempo se lleva a UTC en la columna
    (`FechaUtc`), no aquí: en dos sitios acabaría divergiendo."""
    return {
        "uuid": lectura.uuid,
        "usuario_uuid": usuario_uuid,
        "ts_utc": lectura.ts_utc,
        "zona_horaria": lectura.zona_horaria,
        "mg_dl": lectura.mg_dl,
        "contexto_comida": lectura.contexto_comida,
        "origen": lectura.origen,
    }
