"""El renglón de `POST /insulin`."""

from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from app.schemas.enums import MotivoDosis, TipoInsulina


class DosisEntrada(BaseModel):
    """Un renglón de `POST /insulin`: las siete columnas de `insulin_doses` menos
    `usuario_uuid`, que sale del token (decisión 2.6 del paso 2).

    Es una dosis que la persona **dice haberse aplicado**. El sistema la registra y nunca
    calcula ni sugiere una (regla 7): no hay aquí ningún campo de relación
    insulina/carbohidratos ni de factor de sensibilidad, ni lo habrá.
    """

    model_config = ConfigDict(extra="forbid")

    uuid: UUID
    ts_utc: AwareDatetime  # con offset obligatorio (decisión 2.10 del paso 1)
    zona_horaria: str
    unidades: float
    tipo: TipoInsulina
    motivo: MotivoDosis | None = None  # nulo si la persona no lo dijo; no se adivina


COLUMNAS_INSULIN_DOSES = frozenset(DosisEntrada.model_fields) | {"usuario_uuid"}
