"""El cuerpo y la respuesta de `POST /perfil` (C-7, decisión 2.7 del paso 2)."""

from pydantic import BaseModel, ConfigDict

from app.schemas.enums import TipoUsuario


class PerfilEntrada(BaseModel):
    """Los seis parámetros clínicos que el pipeline necesita, y ni uno más.

    Es la «carga aparte y reducida» que anticipa `PerfilDato.swift`. Con `extra="forbid"`,
    `nombre`, `apellidos`, `peso_kg` y `nota` son un rechazo con motivo legible, no un campo
    que se ignora en silencio: la regla 3 deja de depender de que la app se porte bien.

    `tipo_insulina_rapida` es opcional porque quien no se aplica insulina no lo tiene. Ningún
    campo de relación insulina/carbohidratos ni de factor de sensibilidad (regla 7).
    """

    model_config = ConfigDict(extra="forbid")

    tipo_usuario: TipoUsuario  # los cuatro de Swift (C-3)
    anio_nacimiento: int  # el año solo, sin mes ni día (minimización)
    umbral_hipo: float
    umbral_hiper: float
    tipo_insulina_rapida: str | None = None
    duracion_accion_insulina: float  # en horas


class PerfilGuardado(BaseModel):
    """Los seis valores tal como quedaron guardados, para que el teléfono confirme contra lo
    que mandó y no contra lo que creía haber mandado."""

    tipo_usuario: TipoUsuario
    anio_nacimiento: int
    umbral_hipo: float
    umbral_hiper: float
    tipo_insulina_rapida: str | None
    duracion_accion_insulina: float


# Las columnas de `usuarios`, para filtrar la carga de la cuarentena igual que en el paso 1
# (decisión 2.8 del paso 2). Un `nombre` que llegue por error deja el nombre de su clave en
# `claves_descartadas` y su contenido en ninguna parte.
COLUMNAS_USUARIOS = frozenset(PerfilEntrada.model_fields) | {"uuid", "ts_alta"}
