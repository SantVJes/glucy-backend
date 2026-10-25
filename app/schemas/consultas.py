"""Los parámetros y las respuestas de `GET /history` y `GET /stats` (paso 3).

Ningún modelo de entrada tiene un `usuario_uuid`, y todos llevan `extra="forbid"`: un
`usuario_uuid` en la consulta es un `400`, nunca la serie de otra persona (decisión 2.1). El
filtro por dueño sale del token y de ningún otro sitio.
"""

import base64
import binascii
import json
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.comidas import ComidaEntrada
from app.schemas.dosis import DosisEntrada
from app.schemas.lecturas import LecturaEntrada

MAX_DIAS_PERIODO = 90
LIMITE_POR_OMISION = 200
LIMITE_MAXIMO = 1000

Serie = Literal["lecturas", "comidas", "dosis"]
SERIES: tuple[Serie, ...] = ("lecturas", "comidas", "dosis")


# ---------------------------------------------------------------------------
# Parámetros de consulta.
# ---------------------------------------------------------------------------


class Periodo(BaseModel):
    """Los parámetros comunes a las dos consultas. Los dos extremos son obligatorios: sin
    `desde`, la primera consulta del panel pide la serie completa (decisión 2.5).

    El periodo es semiabierto, `[desde, hasta)`. Las dos fechas llevan offset, igual que al
    subir (decisión 2.10 del paso 1). Un `hasta` futuro se acepta: es un extremo de consulta,
    no un dato que se guarde.
    """

    model_config = ConfigDict(extra="forbid")

    desde: AwareDatetime
    hasta: AwareDatetime

    @model_validator(mode="after")
    def comprobar(self) -> "Periodo":
        if self.desde >= self.hasta:
            raise ValueError("desde tiene que ser anterior a hasta")
        if self.hasta - self.desde > timedelta(days=MAX_DIAS_PERIODO):
            raise ValueError(f"el periodo no puede pasar de {MAX_DIAS_PERIODO} días")
        return self


class ConsultaHistorial(Periodo):
    """`Periodo` más lo propio de `/history`: qué series, cuántos renglones y desde dónde.

    `que` evita bajar las tres series cuando la pantalla solo dibuja una. `cursor` es el
    `siguiente` de la página anterior, tal cual: es opaco para quien consume.
    """

    que: str = Field(
        default=",".join(SERIES),
        description="Series a devolver, separadas por coma: lecturas, comidas, dosis.",
    )
    limite: int = Field(default=LIMITE_POR_OMISION, ge=1, le=LIMITE_MAXIMO)
    cursor: str | None = Field(
        default=None, description="El valor de `siguiente` de la página anterior, tal cual."
    )

    @field_validator("que")
    @classmethod
    def series_conocidas(cls, valor: str) -> str:
        pedidas = [parte.strip() for parte in valor.split(",") if parte.strip()]
        desconocidas = sorted(set(pedidas) - set(SERIES))
        if not pedidas or desconocidas:
            raise ValueError(f"que admite {', '.join(SERIES)}; no: {', '.join(desconocidas)}")
        return ",".join(pedidas)

    @field_validator("cursor")
    @classmethod
    def cursor_legible(cls, valor: str | None) -> str | None:
        if valor is not None:
            decodificar_cursor(valor)
        return valor

    @property
    def series(self) -> frozenset[Serie]:
        return frozenset(self.que.split(","))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# El cursor: (ts_utc, uuid) del último renglón devuelto (decisión 2.6).
# ---------------------------------------------------------------------------


def codificar_cursor(ts_utc: datetime, uuid: UUID) -> str:
    """Base64 de un JSON pequeño. Opaco para quien consume, legible para quien depura."""
    crudo = json.dumps({"ts": ts_utc.isoformat(), "uuid": str(uuid)}).encode()
    return base64.urlsafe_b64encode(crudo).decode()


def decodificar_cursor(cursor: str) -> tuple[datetime, UUID]:
    """Levanta `ValueError` si el cursor no es uno que este servidor haya dado."""
    try:
        datos = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        ts_utc = datetime.fromisoformat(datos["ts"])
        uuid = UUID(datos["uuid"])
    except (binascii.Error, ValueError, KeyError, TypeError) as error:
        raise ValueError("cursor ilegible: manda el valor de siguiente tal cual") from error
    if ts_utc.tzinfo is None:
        raise ValueError("cursor ilegible: manda el valor de siguiente tal cual")
    return ts_utc, uuid


# ---------------------------------------------------------------------------
# Respuestas.
# ---------------------------------------------------------------------------


class Indicadores(BaseModel):
    """Los de `referencia.reglas_clinicas.indicadores`, campo por campo."""

    n: int
    promedio: float
    desviacion: float
    coeficiente_variacion: float
    tir: float
    tbr: float
    tar: float
    gmi: float | None  # None con menos de 14 días (decisión 2.2)


class RespuestaStats(BaseModel):
    """`indicadores: None` y `gmi: None` son dos cosas distintas y las dos viajan: «no hay con
    qué calcular» y «calculé todo menos el GMI»."""

    desde: datetime
    hasta: datetime
    dias_con_lecturas: int
    indicadores: Indicadores | None  # None con menos de 3 días: faltan datos, no un cero
    umbrales_del_perfil: bool  # False si se usaron los de omisión (decisión 2.4)
    umbral_hipo: float
    umbral_hiper: float


# Los renglones del historial son las columnas que se aceptaron al subir, con la misma forma
# (decisión 2.7): el teléfono y el panel ya saben leerla, y un campo de más sería un dato que
# el servidor se inventó. Ni `nota`, ni nombre, ni foto: el servidor no los tiene.


class LecturaGuardada(LecturaEntrada):
    """Un renglón de `glucose_readings`, tal como se subió."""

    model_config = ConfigDict(from_attributes=True)


class ComidaGuardada(ComidaEntrada):
    """Un renglón de `meals`, tal como se subió."""

    model_config = ConfigDict(from_attributes=True)


class DosisGuardada(DosisEntrada):
    """Un renglón de `insulin_doses`, tal como se subió."""

    model_config = ConfigDict(from_attributes=True)


class RespuestaHistorial(BaseModel):
    """Las tres series siempre presentes; la que no se pidió viene vacía.

    `siguiente` es `null` cuando ya no hay más. Esa es la señal de fin, y no «vino menos de
    `limite`»: con un límite exacto, la última página trae `limite` renglones legítimamente.
    """

    lecturas: list[LecturaGuardada]
    comidas: list[ComidaGuardada]
    dosis: list[DosisGuardada]
    siguiente: str | None
