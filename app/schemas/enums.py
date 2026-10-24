"""Los valores cerrados que viajan desde el teléfono.

Son las mismas cadenas que los enums de Swift en `glucy-ios/Glucy/Domain/Enums/`. No se
inventan variantes en inglés: si una deja de coincidir, el servidor rechaza lo que la app
manda sin que nada más falle. `Origen` no está aquí porque vive en la referencia.
"""

from enum import StrEnum


class ContextoComida(StrEnum):
    """Las mismas cadenas que `ContextoComida` en Swift."""

    EN_AYUNAS = "en_ayunas"
    ANTES_DE_COMER = "antes_de_comer"
    DOS_HORAS_DESPUES = "dos_horas_despues"
    ANTES_DE_DORMIR = "antes_de_dormir"
    OTRO = "otro"


class TipoInsulina(StrEnum):
    """Bolo o basal, y nunca «rápida» (C-4): «rápida (bolo)» es una etiqueta de la interfaz
    del teléfono y no viaja."""

    BOLO = "bolo"
    BASAL = "basal"


class MotivoDosis(StrEnum):
    """Por qué se aplicó la dosis, según lo que la persona declara. Si no lo dijo viaja nulo y
    no se adivina. El sistema registra el motivo; nunca calcula ni sugiere una dosis (regla 7).
    """

    COMIDA = "comida"
    CORRECCION = "correccion"
    PROGRAMADA = "programada"


class TipoUsuario(StrEnum):
    """Los cuatro de `TipoUsuario` en Swift, no tres (C-3)."""

    TIPO1 = "tipo1"
    TIPO2_INSULINODEPENDIENTE = "tipo2_insulinodependiente"
    PREDIABETES = "prediabetes"
    RESISTENCIA_INSULINA = "resistencia_insulina"
