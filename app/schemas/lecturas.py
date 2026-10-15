"""El renglón de `POST /readings`."""

from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from referencia.reglas_clinicas import Origen


class ContextoComida(StrEnum):
    """Las mismas cadenas que `ContextoComida` en Swift. No se inventan variantes en inglés."""

    EN_AYUNAS = "en_ayunas"
    ANTES_DE_COMER = "antes_de_comer"
    DOS_HORAS_DESPUES = "dos_horas_despues"
    ANTES_DE_DORMIR = "antes_de_dormir"
    OTRO = "otro"


class LecturaEntrada(BaseModel):
    """Un renglón de `POST /readings`. Son exactamente las columnas de `glucose_readings`
    que el teléfono llena; `usuario_uuid` sale del token (decisión 2.9).

    `extra="forbid"` convierte una `nota` que llegue de más en un renglón en cuarentena con un
    motivo legible, en lugar de un campo que se ignora sin que nadie se entere.
    """

    model_config = ConfigDict(extra="forbid")

    uuid: UUID
    ts_utc: AwareDatetime  # con offset obligatorio (decisión 2.10)
    zona_horaria: str
    mg_dl: float
    origen: Origen  # el StrEnum de referencia/reglas_clinicas.py
    contexto_comida: ContextoComida | None = None


# Las claves que pueden aparecer en un renglón y son columnas de `glucose_readings`. Sirve para
# filtrar la carga que se guarda en cuarentena (decisión 2.6). `usuario_uuid` es columna aunque
# no se acepte del cuerpo: conservarlo es justo lo que permite ver un intento de escribir en la
# serie de otra persona (decisión 2.9).
COLUMNAS_GLUCOSE_READINGS = frozenset(LecturaEntrada.model_fields) | {"usuario_uuid"}
