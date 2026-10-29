"""Lo que entra y lo que sale de `POST /explain` (paso 6).

El cuerpo lleva **la predicción y sus valores SHAP**, no un identificador: la tabla
`predictions` no tiene columna para las contribuciones SHAP, así que el teléfono manda lo que
`/predict` le devolvió.

Y lleva **solo lo que el modelo de lenguaje necesita ver**. Con `extra="forbid"`, un `nombre`,
una `nota` o el `usuario_uuid` que la app mandara por error son un `400` con motivo legible, en
lugar de un campo que se ignora en silencio y acaba en el prompt. La regla 3 deja de depender de
que la app se porte bien.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Las cinco contribuciones más grandes, ni más ni menos: es lo que la pantalla de factores
# dibuja y lo que el prompt lleva.
CONTRIBUCIONES_SHAP = 5

Modo = Literal["sensor", "sin_sensor"]
Origen = Literal["modelo", "plantilla"]
MotivoPlantilla = Literal[
    "sin_asistente",  # la persona lo desactivó, o no hay Ollama configurado
    "sin_respuesta",  # se pasó de los 10 s, o el modelo de lenguaje no contestó (P-13)
    "no_paso_validacion",  # inventó una cifra o insinuó una dosis
]


class ContribucionShap(BaseModel):
    """Una variable y lo que aportó, en mg/dL y con signo."""

    model_config = ConfigDict(extra="forbid")

    variable: str = Field(max_length=40)
    mg_dl: float


class ExplicacionEntrada(BaseModel):
    """Lo que se le manda al modelo de lenguaje, y nada más.

    No hay `usuario_uuid`, ni nombre, ni notas, ni peso, ni año de nacimiento, ni ubicación, ni
    historial: nada de eso sale del teléfono ni entra al prompt.
    """

    model_config = ConfigDict(extra="forbid")

    valor_actual: float
    valor_predicho: float
    horizonte_min: int
    modo: Modo
    umbral_hipo: float
    umbral_hiper: float
    cob_g: float
    iob_ui: float
    hora_local: int = Field(ge=0, le=23)
    shap: list[ContribucionShap] = Field(min_length=1, max_length=CONTRIBUCIONES_SHAP)
    # La persona puede apagar el asistente en Ajustes: entonces se arma la plantilla y no se
    # llama a ningún modelo de lenguaje. El teléfono lo dice en cada petición en lugar de que
    # el servidor guarde la preferencia, porque la preferencia es del teléfono (regla 1).
    asistente_activo: bool = True


class RespuestaExplicacion(BaseModel):
    """La explicación, y **de dónde salió**.

    `origen` no es un detalle de implementación: el reporte tiene que poder decir cuántas
    explicaciones salieron del modelo y cuántas de la plantilla, y la app puede querer marcarlo.
    """

    explicacion: str
    origen: Origen
    motivo: MotivoPlantilla | None = None
    modelo: str | None = None
