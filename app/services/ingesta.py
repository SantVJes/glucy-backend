"""Ingesta de lotes: el reparto en aceptados, duplicados y cuarentena.

Aquí vive la regla y no en el router. Este paso guarda lo que llega y nada más: limpiar la
señal, construir características, COB e IOB son del pipeline del paso 4.

`/readings`, `/meals` y `/insulin` tienen el mismo comportamiento, así que hay una sola
función, `ingerir`, y lo que cambia entre los tres está en su `DescriptorDeLote` (decisión 2.4
del paso 2).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.models.tablas import Base, Comida, DosisInsulina, LecturaGlucosa
from app.repositories import cuarentena as repo_cuarentena
from app.repositories import lotes as repo_lotes
from app.repositories import usuarios as repo_usuarios
from app.schemas.comidas import COLUMNAS_MEALS, ComidaEntrada
from app.schemas.dosis import COLUMNAS_INSULIN_DOSES, DosisEntrada
from app.schemas.lecturas import COLUMNAS_GLUCOSE_READINGS, LecturaEntrada
from app.schemas.lotes import RenglonEnCuarentena
from referencia.reglas_clinicas import validar_comida, validar_dosis, validar_lectura

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
class DescriptorDeLote:
    """Lo que cambia entre /readings, /meals y /insulin. Lo que no cambia es `ingerir`.

    `validar` recibe el renglón ya validado por `esquema` y el presente, y devuelve el motivo
    del rechazo o `None`. Es siempre una función de la referencia envuelta, nunca una regla
    escrita aquí (decisión 2.3 del paso 1).
    """

    tabla: str
    esquema: type[BaseModel]
    columnas: frozenset[str]
    modelo: type[Base]
    validar: Callable[[Any, datetime], str | None]


@dataclass(frozen=True)
class Resultado:
    aceptados: list[UUID]
    duplicados: list[UUID]
    cuarentena: list[RenglonEnCuarentena]


def _validar_lectura(lectura: LecturaEntrada, ahora: datetime) -> str | None:
    """`glucose_readings` no guarda la confirmación del OCR, así que el servidor no puede
    volver a comprobarla: en el teléfono nada se guarda sin confirmar (C-8)."""
    rechazo = validar_lectura(
        lectura.mg_dl, lectura.ts_utc, ahora, lectura.origen, confirmada_por_usuario=True
    )
    return rechazo.motivo if rechazo else None


LOTE_LECTURAS = DescriptorDeLote(
    tabla="glucose_readings",
    esquema=LecturaEntrada,
    columnas=COLUMNAS_GLUCOSE_READINGS,
    modelo=LecturaGlucosa,
    validar=_validar_lectura,
)


def _validar_comida(comida: ComidaEntrada, ahora: datetime) -> str | None:
    """`carbs_g` ya es el total: la referencia no vuelve a multiplicar por las porciones."""
    rechazo = validar_comida(
        comida.carbs_g, comida.tiempo_absorcion_min, comida.porciones, comida.ts_utc, ahora
    )
    return rechazo.motivo if rechazo else None


LOTE_COMIDAS = DescriptorDeLote(
    tabla="meals",
    esquema=ComidaEntrada,
    columnas=COLUMNAS_MEALS,
    modelo=Comida,
    validar=_validar_comida,
)


def _validar_dosis(dosis: DosisEntrada, ahora: datetime) -> str | None:
    """Que la dosis sea anotable, no que sea la adecuada (regla 7)."""
    rechazo = validar_dosis(dosis.unidades, dosis.ts_utc, ahora)
    return rechazo.motivo if rechazo else None


LOTE_DOSIS = DescriptorDeLote(
    tabla="insulin_doses",
    esquema=DosisEntrada,
    columnas=COLUMNAS_INSULIN_DOSES,
    modelo=DosisInsulina,
    validar=_validar_dosis,
)


def ingerir(
    sesion: Session,
    usuario_uuid: UUID,
    renglones: list[dict],
    ahora: datetime,
    lote: DescriptorDeLote,
) -> Resultado:
    """Reparte un lote en aceptados, duplicados y cuarentena. Aquí vive la regla.

    El mismo reparto del paso 1, con el descriptor del lote como único parámetro nuevo.

    `ahora` entra como parámetro y no se lee de dentro: una prueba de marca de tiempo futura
    necesita poder fijar el presente.

    Cada renglón termina en exactamente una de las tres listas: nada se descarta en silencio
    (RF-22). El lote entero es una sola transacción, así que un error del servidor a la mitad
    no deja la mitad escrita y el teléfono puede reintentarlo completo.
    """
    # 1. El usuario nace en su primer contacto (decisión 2.7).
    repo_usuarios.asegurar_que_existe(sesion, usuario_uuid, ts_alta=ahora)

    cuarentena: list[RenglonEnCuarentena] = []
    sobrevivientes: list[BaseModel] = []

    for renglon in renglones:
        validado = _validar_renglon(renglon, usuario_uuid, ahora, lote)
        if isinstance(validado, str):
            a_cuarentena(sesion, renglon, validado, ahora, lote.tabla, lote.columnas)
            cuarentena.append(RenglonEnCuarentena(uuid=_uuid_legible(renglon), motivo=validado))
        else:
            sobrevivientes.append(validado)

    # 6. Lo que sobrevive se inserta; lo que la base no dejó entrar es duplicado (RF-36c).
    entraron = set(
        repo_lotes.insertar_ignorando_duplicados(
            sesion, lote.modelo, [_fila(entrada, usuario_uuid) for entrada in sobrevivientes]
        )
    )
    aceptados: list[UUID] = []
    duplicados: list[UUID] = []
    for entrada in sobrevivientes:
        # Un uuid repetido dentro del mismo lote entra una vez: la segunda es duplicado.
        if entrada.uuid in entraron:
            entraron.discard(entrada.uuid)
            aceptados.append(entrada.uuid)
        else:
            duplicados.append(entrada.uuid)

    sesion.commit()
    return Resultado(aceptados=aceptados, duplicados=duplicados, cuarentena=cuarentena)


def _validar_renglon(
    renglon: dict[str, Any], usuario_uuid: UUID, ahora: datetime, lote: DescriptorDeLote
) -> BaseModel | str:
    """Pasos 2 a 5: devuelve el renglón validado, o el motivo por el que va a cuarentena."""
    # `usuario_uuid` es columna pero no campo de entrada: sale del token (decisión 2.9).
    sin_usuario = {k: v for k, v in renglon.items() if k != "usuario_uuid"}

    # 2. El esquema del renglón.
    try:
        entrada = lote.esquema.model_validate(sin_usuario)
    except ValidationError as error:
        return motivo_de_validacion(error)

    # 3. Un usuario_uuid en el cuerpo igual al del token se ignora; distinto, a cuarentena.
    if "usuario_uuid" in renglon and str(renglon["usuario_uuid"]).lower() != str(usuario_uuid):
        return "usuario_uuid del cuerpo distinto del token: solo se escribe en la serie propia"

    # 4. Sin una zona resoluble la hora local es irrecuperable, y alimenta hora_sin y hora_cos.
    # ZoneInfo levanta ValueError u OSError con nombres raros («../», un directorio), no solo
    # ZoneInfoNotFoundError.
    try:
        ZoneInfo(entrada.zona_horaria)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return f"zona_horaria que no existe: {entrada.zona_horaria!r}"

    # 5. Las reglas clínicas, importadas de la referencia y no reimplementadas (decisión 2.3).
    motivo = lote.validar(entrada, ahora)
    if motivo is not None:
        return motivo

    return entrada


def motivo_de_validacion(error: ValidationError, propios: dict[str, str] | None = None) -> str:
    """Un motivo legible por campo, sin repetir el valor recibido.

    `propios` cambia el texto de algunos tipos de error para un caso concreto: el perfil lo
    usa para que un campo de más diga que es la regla 3.
    """
    motivos = {**_MOTIVOS_POR_TIPO_DE_ERROR, **(propios or {})}
    partes = []
    for detalle in error.errors():
        campo = ".".join(str(parte) for parte in detalle["loc"]) or "renglón"
        partes.append(f"{campo}: {motivos.get(detalle['type'], detalle['msg'])}")
    return "; ".join(partes)


def a_cuarentena(
    sesion: Session,
    renglon: dict[str, Any],
    motivo: str,
    ahora: datetime,
    tabla: str,
    columnas: frozenset[str],
) -> None:
    """Guarda solo las claves que son columnas; de las demás, solo el nombre (decisión 2.6).

    Si una versión de la app manda una `nota` por error, guardar el renglón entero metería
    texto libre en el servidor por la puerta de atrás de una tabla de diagnóstico.
    """
    repo_cuarentena.guardar(
        sesion,
        ts_recepcion=ahora,
        tabla_destino=tabla,
        carga_original={k: v for k, v in renglon.items() if k in columnas},
        claves_descartadas=sorted(k for k in renglon if k not in columnas),
        motivo_rechazo=motivo,
    )


def _uuid_legible(renglon: dict[str, Any]) -> UUID | None:
    try:
        return UUID(str(renglon["uuid"]))
    except (KeyError, ValueError):
        return None


def _fila(entrada: BaseModel, usuario_uuid: UUID) -> dict[str, Any]:
    """La fila de la tabla destino: los campos del esquema, que son sus columnas, más el
    `usuario_uuid` del token. La marca de tiempo se lleva a UTC en la columna (`FechaUtc`), no
    aquí: en dos sitios acabaría divergiendo."""
    return {**entrada.model_dump(), "usuario_uuid": usuario_uuid}
