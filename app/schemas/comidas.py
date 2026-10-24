"""El renglón de `POST /meals`."""

from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from referencia.reglas_clinicas import ABSORCION_DEFECTO_MIN, Origen


class ComidaEntrada(BaseModel):
    """Un renglón de `POST /meals`: las doce columnas de `meals` menos `usuario_uuid`, que
    sale del token (decisión 2.5 del paso 2).

    **`carbs_g` son los gramos totales, ya multiplicados por las porciones.** `porciones`
    viaja solo como información: si el servidor volviera a multiplicar, el COB del pipeline
    saldría al doble o al triple y nadie lo notaría hasta ver las métricas raras.

    `proteina_g`, `grasa_g` y `fibra_g` van a ser siempre nulas en esta fase porque la app no
    las captura. Se aceptan igual: son columnas del Documento 3, y el día que la app las
    capture el servidor no cambia.

    `descripcion`, `nombre_producto`, `porcion_g` y `nota` se quedan en el teléfono:
    `extra="forbid"` las manda a cuarentena con un motivo legible.
    """

    model_config = ConfigDict(extra="forbid")

    uuid: UUID
    ts_utc: AwareDatetime  # con offset obligatorio (decisión 2.10 del paso 1)
    zona_horaria: str
    carbs_g: float
    origen: Origen
    tiempo_absorcion_min: int = ABSORCION_DEFECTO_MIN  # D-8
    porciones: float = 1
    codigo_barras: str | None = None
    proteina_g: float | None = None
    grasa_g: float | None = None
    fibra_g: float | None = None


# Las claves que son columnas de `meals`, para filtrar la carga de la cuarentena (decisión 2.6
# del paso 1). `usuario_uuid` es columna aunque no se acepte del cuerpo (decisión 2.9).
COLUMNAS_MEALS = frozenset(ComidaEntrada.model_fields) | {"usuario_uuid"}
