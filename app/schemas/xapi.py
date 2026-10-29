"""El renglón de `POST /xapi` y el vocabulario de las sentencias (RF-19, RF-33).

El teléfono **no manda una sentencia xAPI**: manda un verbo, una actividad y hasta tres
números. La sentencia la arma el servidor.

Es la decisión que sostiene todo lo demás de este paso. Si el cuerpo trajera `actor`, `objeto`
y `resultado` como JSON libre —que es la forma natural de leer las columnas de `xapi_events`—,
cualquier campo del teléfono podría viajar al Learning Record Store por esa puerta: una `nota`,
un nombre, una cifra de glucosa. La regla 3 dice que eso nunca sale del teléfono, y una regla
que depende de que el cliente se porte bien no es una regla. Con un verbo de una lista cerrada,
una actividad de otra y tres números, **no hay forma de escribir texto libre en el LRS**.
"""

from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

# No se tiene dominio propio, y xAPI identifica actividades y actores con IRI. El repositorio
# es el identificador estable que sí existe, así que de ahí cuelgan los de Glucy. Queda anotado
# para el reporte: si algún día hay dominio, esta constante es el único lugar que cambia.
BASE_IRI = "https://github.com/SantVJes/glucy-backend/xapi"
PAGINA_DE_LA_CUENTA = f"{BASE_IRI}/usuarios"

IDIOMA = "es-MX"
VERSION_XAPI = "1.0.3"


class Verbo(StrEnum):
    """Los seis verbos del Documento 2. Son vocabulario de xAPI, así que van en inglés."""

    EXPERIENCED = "experienced"  # registró una lectura, una comida o una dosis
    RECEIVED = "received"  # recibió una alerta
    RESPONDED = "responded"  # respondió a una alerta
    LAUNCHED = "launched"  # abrió un módulo educativo
    COMPLETED = "completed"  # terminó un módulo educativo
    ANSWERED = "answered"  # contestó una evaluación


class Actividad(StrEnum):
    """Sobre qué. Lista cerrada: lo que no está aquí va a cuarentena con su motivo."""

    REGISTRO_DE_GLUCOSA = "registro-de-glucosa"
    REGISTRO_DE_COMIDA = "registro-de-comida"
    REGISTRO_DE_INSULINA = "registro-de-insulina"
    ALERTA_DE_HIPOGLUCEMIA = "alerta-de-hipoglucemia"
    MODULO_EDUCATIVO = "modulo-educativo"
    EVALUACION = "evaluacion"


class _Verbo(BaseModel):
    """Un verbo del vocabulario, con lo que hay que decir de él en el reporte."""

    iri: str
    display: str
    # Cotejado el 29/10/2026 contra `adl/adl.jsonld` de adlnet/xapi-authored-profiles, que es
    # el perfil que ADL publica. Los tres que salen en falso NO están ahí, y hay que decirlo
    # en el reporte en lugar de escribir «xAPI 1.0.3» y dejarlo pasar:
    #   - `completed` se usa con ese mismo IRI en el perfil cmi5, que es de ADL pero es otro
    #     documento;
    #   - `responded` es de uso corriente con ese IRI y no está en ninguno de los dos;
    #   - `received` no existe en el vocabulario de ADL, así que se toma el de Activity
    #     Streams 1.0, que es el que usa todo el mundo para «recibió».
    # Un verbo fuera del perfil es válido en xAPI —la especificación deja crear vocabulario—,
    # pero quien lea el reporte tiene derecho a saber cuál es cuál.
    en_el_perfil_de_adl: bool


VERBOS: dict[Verbo, _Verbo] = {
    Verbo.EXPERIENCED: _Verbo(
        iri="http://adlnet.gov/expapi/verbs/experienced",
        display="registró",
        en_el_perfil_de_adl=True,
    ),
    Verbo.RECEIVED: _Verbo(
        iri="http://activitystrea.ms/schema/1.0/receive",
        display="recibió",
        en_el_perfil_de_adl=False,
    ),
    Verbo.RESPONDED: _Verbo(
        iri="http://adlnet.gov/expapi/verbs/responded",
        display="respondió a",
        en_el_perfil_de_adl=False,
    ),
    Verbo.LAUNCHED: _Verbo(
        iri="http://adlnet.gov/expapi/verbs/launched",
        display="abrió",
        en_el_perfil_de_adl=True,
    ),
    Verbo.COMPLETED: _Verbo(
        iri="http://adlnet.gov/expapi/verbs/completed",
        display="terminó",
        en_el_perfil_de_adl=False,
    ),
    Verbo.ANSWERED: _Verbo(
        iri="http://adlnet.gov/expapi/verbs/answered",
        display="contestó",
        en_el_perfil_de_adl=True,
    ),
}


class _Actividad(BaseModel):
    nombre: str
    tipo: str


_PERFORMANCE = "http://adlnet.gov/expapi/activities/performance"

ACTIVIDADES: dict[Actividad, _Actividad] = {
    Actividad.REGISTRO_DE_GLUCOSA: _Actividad(nombre="una medición de glucosa", tipo=_PERFORMANCE),
    Actividad.REGISTRO_DE_COMIDA: _Actividad(nombre="una comida", tipo=_PERFORMANCE),
    Actividad.REGISTRO_DE_INSULINA: _Actividad(nombre="una dosis de insulina", tipo=_PERFORMANCE),
    Actividad.ALERTA_DE_HIPOGLUCEMIA: _Actividad(
        nombre="un aviso de glucosa baja", tipo=_PERFORMANCE
    ),
    Actividad.MODULO_EDUCATIVO: _Actividad(
        nombre="un módulo educativo", tipo="http://adlnet.gov/expapi/activities/module"
    ),
    Actividad.EVALUACION: _Actividad(
        nombre="una evaluación", tipo="http://adlnet.gov/expapi/activities/assessment"
    ),
}

# Qué verbo tiene sentido sobre qué actividad. Sin esta tabla, «contestó una medición de
# glucosa» entraría al LRS como una sentencia válida y los indicadores de aprendizaje saldrían
# con basura dentro que nadie podría explicar después.
COMBINACIONES: dict[Verbo, frozenset[Actividad]] = {
    Verbo.EXPERIENCED: frozenset(
        {
            Actividad.REGISTRO_DE_GLUCOSA,
            Actividad.REGISTRO_DE_COMIDA,
            Actividad.REGISTRO_DE_INSULINA,
        }
    ),
    Verbo.RECEIVED: frozenset({Actividad.ALERTA_DE_HIPOGLUCEMIA}),
    Verbo.RESPONDED: frozenset({Actividad.ALERTA_DE_HIPOGLUCEMIA}),
    Verbo.LAUNCHED: frozenset({Actividad.MODULO_EDUCATIVO}),
    Verbo.COMPLETED: frozenset({Actividad.MODULO_EDUCATIVO}),
    Verbo.ANSWERED: frozenset({Actividad.EVALUACION}),
}


class EventoXapiEntrada(BaseModel):
    """Un renglón de `POST /xapi`: lo que el teléfono tiene en su `ColaXapi`.

    `extra="forbid"` es la mitad de la protección: un `actor`, un `objeto` o una `nota` que
    llegue de más es un renglón en cuarentena con su motivo, no un campo que se ignora. La otra
    mitad es que no hay ningún campo de texto libre que aceptar.
    """

    model_config = ConfigDict(extra="forbid")

    uuid: UUID
    ts_utc: AwareDatetime  # con offset obligatorio, igual que los tres lotes clínicos
    verbo: Verbo
    actividad: Actividad
    # Los tres opcionales son el `result` de xAPI, y solo tienen sentido en algunos verbos.
    exito: bool | None = None
    puntaje: float | None = Field(default=None, ge=0.0, le=1.0)  # `score.scaled` de xAPI
    duracion_s: float | None = Field(default=None, ge=0.0)


# Las claves que son columnas de `xapi_events`, para filtrar lo que se guarda en cuarentena
# (decisión 2.6 del paso 2). `actor`, `objeto`, `resultado` y `verbo` son columnas de la tabla
# pero **no** campos de entrada: las llena el servidor, así que no entran aquí y un intento de
# mandarlas se queda solo con el nombre de la clave.
COLUMNAS_XAPI_EVENTS = frozenset({"uuid", "ts_utc", "usuario_uuid"})
