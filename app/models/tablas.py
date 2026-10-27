"""Las doce tablas del backend, tal como las fija el Documento 3.

Los nombres de las tablas no se traducen ni se renombran, aunque estén en dos idiomas: así
están documentados y cambiarlos rompería la correspondencia con el reporte.

Las doce se crean de una vez aunque el paso 1 solo escriba en tres (decisión 2.4). Ninguna
guarda nombre, apellidos, peso, correo, notas ni fotografías: no es un olvido (regla 3).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.models.tipos import FechaUtc


class Base(DeclarativeBase):
    # Todas las marcas de tiempo se guardan en UTC y vuelven con su zona (decisión 2.1 del
    # paso 2). Cada columna lo declara explícito; el mapa es la red para la que se olvide.
    type_annotation_map = {datetime: FechaUtc}


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
    ts_alta: Mapped[datetime] = mapped_column(FechaUtc)
    # Sin nombre, sin apellidos, sin peso, sin correo. No es un olvido (regla 3).


class LecturaGlucosa(Base):
    """Una lectura de glucosa. El `uuid` lo genera el teléfono y es la llave de idempotencia."""

    __tablename__ = "glucose_readings"

    uuid: Mapped[UUID] = mapped_column(primary_key=True)  # UNIQUE por ser PK (RF-36c)
    usuario_uuid: Mapped[UUID] = mapped_column(ForeignKey("usuarios.uuid"), index=True)
    ts_utc: Mapped[datetime] = mapped_column(FechaUtc, index=True)
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
    ts_recepcion: Mapped[datetime] = mapped_column(FechaUtc)
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
    ts_utc: Mapped[datetime | None] = mapped_column(FechaUtc, index=True)
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
    ts_utc: Mapped[datetime | None] = mapped_column(FechaUtc, index=True)
    zona_horaria: Mapped[str | None]
    unidades: Mapped[float | None]
    tipo: Mapped[str | None]
    motivo: Mapped[str | None]


class EventoContexto(Base):
    __tablename__ = "context_events"

    uuid: Mapped[UUID] = mapped_column(primary_key=True)
    usuario_uuid: Mapped[UUID] = mapped_column(ForeignKey("usuarios.uuid"), index=True)
    ts_inicio: Mapped[datetime | None] = mapped_column(FechaUtc, index=True)
    ts_fin: Mapped[datetime | None] = mapped_column(FechaUtc)
    clase: Mapped[str | None]
    intensidad: Mapped[str | None]
    calidad: Mapped[str | None]
    origen: Mapped[str | None]


class Prediccion(Base):
    """De esta tabla el backend es la autoridad, no el teléfono."""

    __tablename__ = "predictions"

    uuid: Mapped[UUID] = mapped_column(primary_key=True)
    usuario_uuid: Mapped[UUID] = mapped_column(ForeignKey("usuarios.uuid"), index=True)
    ts_utc: Mapped[datetime | None] = mapped_column(FechaUtc, index=True)
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
    ts_emision: Mapped[datetime | None] = mapped_column(FechaUtc)
    tipo: Mapped[str | None]
    ts_respuesta: Mapped[datetime | None] = mapped_column(FechaUtc)
    accion: Mapped[str | None]
    resulto_real: Mapped[bool | None]


class Modelo(Base):
    __tablename__ = "modelos"

    version: Mapped[str] = mapped_column(primary_key=True)
    algoritmo: Mapped[str | None]
    horizonte: Mapped[int | None]
    fecha_entrenamiento: Mapped[datetime | None] = mapped_column(FechaUtc)
    rmse: Mapped[float | None]
    mae: Mapped[float | None]
    mard: Mapped[float | None]
    clarke_ab: Mapped[float | None]
    ruta_artefacto: Mapped[str | None]


class _ColumnasAgregado:
    """Las mismas columnas para los dos agregados.

    Son tablas normales en los dos motores y las llena el pipeline con `indicadores()` de la
    referencia (decisión 2.6 del paso 4). **No son *continuous aggregates*:** esos son de la
    edición Community de TimescaleDB, que no es software libre, y no existen en la edición
    Apache 2 que usa el proyecto. Además calcularían el TIR y el GMI en SQL, una cuarta
    implementación de las reglas clínicas sin nada que la compare con la referencia.
    """

    usuario_uuid: Mapped[UUID] = mapped_column(ForeignKey("usuarios.uuid"), primary_key=True)
    periodo: Mapped[datetime] = mapped_column(FechaUtc, primary_key=True)
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
    ts_utc: Mapped[datetime | None] = mapped_column(FechaUtc)
    actor: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    verbo: Mapped[str | None]
    objeto: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    resultado: Mapped[dict[str, Any] | None] = mapped_column(JSON)


# ---------------------------------------------------------------------------
# La tabla trece (C-9): no está en el Documento 3.
# ---------------------------------------------------------------------------


class SerieLimpia(Base):
    """La señal ya depurada por el pipeline (RF-23, decisión 2.5 del paso 4).

    No está en el Documento 3 y hay que decirlo en el reporte (C-9). Sin ella el pipeline no
    tiene dónde dejar lo que limpia, y escribir encima de `glucose_readings.mg_dl` perdería el
    dato crudo, que es del teléfono (regla 1).

    La llave es `(usuario_uuid, ts_utc)` y no lleva `uuid`: una fila interpolada no viene de
    ninguna lectura y no tiene uno. Como la llave incluye la columna de tiempo, en PostgreSQL
    esta sí puede ser hipertabla, y es la única: `glucose_readings` se queda como tabla normal
    porque su llave de idempotencia es el `uuid` solo (decisión 2.4).

    `atipica` e `interpolada` viajan en la fila porque una métrica sobre datos interpolados no
    vale lo mismo que una sobre lecturas reales, y quien entrene tiene que poder distinguirlas.
    `zona_horaria` viaja también, por la regla 5: los agregados agrupan por día local.
    """

    __tablename__ = "serie_limpia"

    usuario_uuid: Mapped[UUID] = mapped_column(ForeignKey("usuarios.uuid"), primary_key=True)
    ts_utc: Mapped[datetime] = mapped_column(FechaUtc, primary_key=True)
    zona_horaria: Mapped[str]
    mg_dl: Mapped[float]
    origen: Mapped[str]
    atipica: Mapped[bool] = mapped_column(default=False)
    interpolada: Mapped[bool] = mapped_column(default=False)
