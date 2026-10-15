"""Las doce tablas del backend, tal como las fija el Documento 3.

Los nombres de las tablas no se traducen ni se renombran, aunque estén en dos idiomas: así
están documentados y cambiarlos rompería la correspondencia con el reporte.

Las doce se crean de una vez aunque el paso 1 solo escriba en tres (decisión 2.4). Ninguna
guarda nombre, apellidos, peso, correo, notas ni fotografías: no es un olvido (regla 3).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    # Todas las marcas de tiempo se guardan con su zona: el servidor trabaja en UTC.
    type_annotation_map = {datetime: DateTime(timezone=True)}


# ---------------------------------------------------------------------------
# Las que escribe el paso 1.
# ---------------------------------------------------------------------------


class Usuario(Base):
    """El usuario nace en su primer lote, con `uuid` y `ts_alta` y nada más (decisión 2.7).

    Los parámetros clínicos del perfil todavía no tienen por dónde llegar (C-7, paso 2).
    """

    __tablename__ = "usuarios"

    uuid: Mapped[UUID] = mapped_column(primary_key=True)
    tipo_usuario: Mapped[str | None]
    anio_nacimiento: Mapped[int | None]
    umbral_hipo: Mapped[float | None]
    umbral_hiper: Mapped[float | None]
    tipo_insulina_rapida: Mapped[str | None]
    duracion_accion_insulina: Mapped[float | None]
    ts_alta: Mapped[datetime]
    # Sin nombre, sin apellidos, sin peso, sin correo. No es un olvido (regla 3).


class LecturaGlucosa(Base):
    """Una lectura de glucosa. El `uuid` lo genera el teléfono y es la llave de idempotencia."""

    __tablename__ = "glucose_readings"

    uuid: Mapped[UUID] = mapped_column(primary_key=True)  # UNIQUE por ser PK (RF-36c)
    usuario_uuid: Mapped[UUID] = mapped_column(ForeignKey("usuarios.uuid"), index=True)
    ts_utc: Mapped[datetime] = mapped_column(index=True)
    zona_horaria: Mapped[str]
    mg_dl: Mapped[float]
    contexto_comida: Mapped[str | None]
    origen: Mapped[str]
    # Sin la nota (regla 3).


class Cuarentena(Base):
    """Lo que no pasó la validación, con su motivo y su carga original (RF-22).

    `claves_descartadas` es la única columna que no está en el Documento 3 (decisión 2.6):
    guarda los nombres de las claves que no son columnas, nunca su contenido.
    """

    __tablename__ = "cuarentena"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts_recepcion: Mapped[datetime]
    tabla_destino: Mapped[str]
    carga_original: Mapped[dict[str, Any]] = mapped_column(JSON)
    claves_descartadas: Mapped[list[str]] = mapped_column(JSON, default=list)
    motivo_rechazo: Mapped[str]


# ---------------------------------------------------------------------------
# Las otras nueve: todas nulas salvo las claves, hasta que su paso las llene.
# ---------------------------------------------------------------------------


class Comida(Base):
    """`proteina_g`, `grasa_g` y `fibra_g` siempre son nulas en la fase 2: la app de la
    fase 1 no las captura (decisión 2.2). Existen porque el Documento 3 las fija.
    """

    __tablename__ = "meals"

    uuid: Mapped[UUID] = mapped_column(primary_key=True)
    usuario_uuid: Mapped[UUID] = mapped_column(ForeignKey("usuarios.uuid"), index=True)
    ts_utc: Mapped[datetime | None] = mapped_column(index=True)
    zona_horaria: Mapped[str | None]
    carbs_g: Mapped[float | None]
    tiempo_absorcion_min: Mapped[int | None]
    proteina_g: Mapped[float | None]
    grasa_g: Mapped[float | None]
    fibra_g: Mapped[float | None]
    codigo_barras: Mapped[str | None]
    porciones: Mapped[float | None]
    origen: Mapped[str | None]


class DosisInsulina(Base):
    """Una dosis que la persona registró. El sistema nunca calcula ni sugiere una."""

    __tablename__ = "insulin_doses"

    uuid: Mapped[UUID] = mapped_column(primary_key=True)
    usuario_uuid: Mapped[UUID] = mapped_column(ForeignKey("usuarios.uuid"), index=True)
    ts_utc: Mapped[datetime | None] = mapped_column(index=True)
    zona_horaria: Mapped[str | None]
    unidades: Mapped[float | None]
    tipo: Mapped[str | None]
    motivo: Mapped[str | None]


class EventoContexto(Base):
    __tablename__ = "context_events"

    uuid: Mapped[UUID] = mapped_column(primary_key=True)
    usuario_uuid: Mapped[UUID] = mapped_column(ForeignKey("usuarios.uuid"), index=True)
    ts_inicio: Mapped[datetime | None] = mapped_column(index=True)
    ts_fin: Mapped[datetime | None]
    clase: Mapped[str | None]
    intensidad: Mapped[str | None]
    calidad: Mapped[str | None]
    origen: Mapped[str | None]


class Prediccion(Base):
    """De esta tabla el backend es la autoridad, no el teléfono."""

    __tablename__ = "predictions"

    uuid: Mapped[UUID] = mapped_column(primary_key=True)
    usuario_uuid: Mapped[UUID] = mapped_column(ForeignKey("usuarios.uuid"), index=True)
    ts_utc: Mapped[datetime | None] = mapped_column(index=True)
    horizonte_min: Mapped[int | None]
    valor_predicho: Mapped[float | None]
    modo: Mapped[str | None]
    modelo_version: Mapped[str | None]
    confianza: Mapped[float | None]


class Alerta(Base):
    __tablename__ = "alerts"

    uuid: Mapped[UUID] = mapped_column(primary_key=True)
    usuario_uuid: Mapped[UUID] = mapped_column(ForeignKey("usuarios.uuid"), index=True)
    prediccion_uuid: Mapped[UUID | None] = mapped_column(ForeignKey("predictions.uuid"))
    ts_emision: Mapped[datetime | None]
    tipo: Mapped[str | None]
    ts_respuesta: Mapped[datetime | None]
    accion: Mapped[str | None]
    resulto_real: Mapped[bool | None]


class Modelo(Base):
    __tablename__ = "modelos"

    version: Mapped[str] = mapped_column(primary_key=True)
    algoritmo: Mapped[str | None]
    horizonte: Mapped[int | None]
    fecha_entrenamiento: Mapped[datetime | None]
    rmse: Mapped[float | None]
    mae: Mapped[float | None]
    mard: Mapped[float | None]
    clarke_ab: Mapped[float | None]
    ruta_artefacto: Mapped[str | None]


class _ColumnasAgregado:
    """Las mismas columnas para los dos agregados.

    En PostgreSQL serán *continuous aggregates* de TimescaleDB (paso 4); mientras tanto son
    tablas normales y vacías (decisión 2.4).
    """

    usuario_uuid: Mapped[UUID] = mapped_column(ForeignKey("usuarios.uuid"), primary_key=True)
    periodo: Mapped[datetime] = mapped_column(primary_key=True)
    promedio: Mapped[float | None]
    minimo: Mapped[float | None]
    maximo: Mapped[float | None]
    desviacion: Mapped[float | None]
    tir: Mapped[float | None]
    tbr: Mapped[float | None]
    tar: Mapped[float | None]
    gmi: Mapped[float | None]


class AgregadoHorario(_ColumnasAgregado, Base):
    __tablename__ = "agregados_horarios"


class AgregadoDiario(_ColumnasAgregado, Base):
    __tablename__ = "agregados_diarios"


class EventoXapi(Base):
    __tablename__ = "xapi_events"

    uuid: Mapped[UUID] = mapped_column(primary_key=True)
    usuario_uuid: Mapped[UUID] = mapped_column(ForeignKey("usuarios.uuid"), index=True)
    ts_utc: Mapped[datetime | None]
    actor: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    verbo: Mapped[str | None]
    objeto: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    resultado: Mapped[dict[str, Any] | None] = mapped_column(JSON)
