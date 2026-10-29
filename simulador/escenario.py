"""El escenario del simulador y su cálculo. **Aquí no se dibuja nada.**

Mismo reparto que en la app: la vista no calcula. `app.py` mueve controles y pinta; todo lo que
decide algo está en este archivo. Dos razones, y la segunda es la que importa:

1. Se prueba sin navegador y sin levantar nada, y la integración continua no tiene que instalar
   Streamlit.
2. **El simulador tiene que contestar exactamente lo mismo que `GET /predict`.** Un simulador
   que calcula por su cuenta es una demostración de sí mismo: enseñaría una curva bonita que el
   sistema de verdad no produce. Por eso aquí no hay ni una regla propia. La serie se arma y se
   pasa por `limpiar()`, el vector lo construye `vector_denso` del pipeline, el modo lo decide
   `modo_actual` de la referencia, la predicción la hace el mismo artefacto que carga la API y
   la explicación sale del mismo servicio. Lo único propio es traducir unos controles a esas
   entradas.

Lo que el simulador **no** hace, por las mismas razones que la app: no calcula ni sugiere una
dosis (regla 7), no infiere una comida que no se registró (D-9, RF-37) y en modo sin sensor no
anticipa una hipoglucemia (RF-10b): lo declara.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.schemas.explicacion import (
    ContribucionShap,
    ExplicacionEntrada,
    RespuestaExplicacion,
)
from app.schemas.prediccion import AVISO_SIN_SENSOR
from app.services.explicacion.servicio import explicar
from app.services.pipeline.caracteristicas import (
    CARACTERISTICAS_DENSAS,
    CARACTERISTICAS_DISPERSAS,
    como_fila,
    vector_denso,
    vector_disperso,
)
from app.services.pipeline.limpieza import Punto, limpiar
from app.services.prediccion.artefacto import ORIGEN_REPORTABLE, Artefacto
from app.services.prediccion.servicio import HORIZONTES, VENTANA_MIN, alerta_de
from referencia.reglas_clinicas import (
    ABSORCION_DEFECTO_MIN,
    CARBS_MAX_G,
    CARBS_MIN_G,
    DIA_DEFECTO_H,
    DIA_RANGO_H,
    GLUCOSA_MAX,
    GLUCOSA_MIN,
    INSULINA_MAX_UI,
    INSULINA_MIN_UI,
    UMBRAL_HIPER_DEFECTO,
    UMBRAL_HIPER_RANGO,
    UMBRAL_HIPO_DEFECTO,
    UMBRAL_HIPO_RANGO,
    Modo,
    Origen,
    modo_actual,
    puede_alertar_hipoglucemia,
)

# La zona de los escenarios. El proyecto es para México y la hora del día entra al modelo
# (`hora_sin`, `hora_cos`), así que no puede quedarse en UTC: una bajada de las 03:00 metida al
# modelo como las 09:00 es otra cosa.
ZONA = "America/Mexico_City"

# El sensor comercial reporta cada cinco minutos. La serie del escenario se arma en esa rejilla
# porque es la que el pipeline espera y la que produce los rezagos del juego denso.
PASO_MIN = 5


def motivo_sin_modelo(horizontes_sin_modelo: list[int]) -> str:
    """Por qué una cifra salió de la línea base y no del modelo, diciendo de cuáles se habla.

    Importa que diga «a 60 minutos» y no «no hay modelo» cuando el de 30 sí está cargado: el
    caso normal mientras se entrena es tener uno y no el otro, y un aviso que exagera se deja
    de leer.
    """
    cuales = " y ".join(f"{h} min" for h in horizontes_sin_modelo)
    return (
        f"A {cuales} no hay modelo cargado, así que lo que se enseña es la línea base de "
        "persistencia: «dentro de ese rato será igual que ahora». No es una predicción y no se "
        "puede presentar como tal; es la marca que el modelo tiene que superar para justificar "
        "su existencia."
    )


# Por construcción la persistencia nunca anticipa nada: repite el valor de ahora. Conviene que
# el simulador lo diga con palabras, porque es justo lo que hace evidente para qué sirve el
# modelo.
NOTA_LINEA_BASE = (
    "La línea base repite el valor actual, así que no puede avisar de una bajada que no haya "
    "empezado. Esa es la diferencia que el modelo tiene que aportar."
)


@dataclass(frozen=True)
class _Comida:
    """Lo mínimo que `vector_denso` le pide a una comida. No es la tabla, es el escenario."""

    ts_utc: datetime
    carbs_g: float
    tiempo_absorcion_min: int


@dataclass(frozen=True)
class _Dosis:
    ts_utc: datetime
    unidades: float
    tipo: str = "bolo"


@dataclass(frozen=True)
class _Perfil:
    umbral_hipo: float
    umbral_hiper: float
    duracion_accion_insulina: float


@dataclass(frozen=True)
class Escenario:
    """Lo que la persona mueve en la pantalla del simulador.

    `minutos_desde_comida` y `minutos_desde_dosis` son «hace cuánto», no una hora: es lo que se
    puede mover con un control y lo único que el COB y el IOB necesitan.

    `carbs_g` o `dosis_ui` en cero significan **que no hubo**, y entonces no entra ninguna
    comida ni ninguna dosis al cálculo. No es una comida de cero gramos: una comida que no se
    registró no existe (D-9, RF-37).
    """

    glucosa_actual: float = 120.0
    # mg/dL por minuto. Negativa = va bajando. Es lo que arma la pendiente de la serie, y de
    # ahí salen `derivada_1`, `derivada_2` y los rezagos.
    tendencia_mg_dl_min: float = 0.0
    hora_local: int = 8
    con_sensor: bool = True
    # Con sensor, la antigüedad de la última lectura: pasados 15 minutos el modo se degrada
    # solo (P-03). Sin sensor, la antigüedad del último pinchazo.
    antiguedad_min: float = 0.0
    carbs_g: float = 0.0
    minutos_desde_comida: float = 0.0
    tiempo_absorcion_min: int = ABSORCION_DEFECTO_MIN
    dosis_ui: float = 0.0
    minutos_desde_dosis: float = 0.0
    duracion_accion_h: float = DIA_DEFECTO_H
    umbral_hipo: float = UMBRAL_HIPO_DEFECTO
    umbral_hiper: float = UMBRAL_HIPER_DEFECTO
    asistente_activo: bool = True

    def __post_init__(self) -> None:
        """Los mismos rangos que valida la app y que vuelve a validar la API.

        No es ceremonia: el simulador es lo que se va a enseñar en la defensa del proyecto, y un
        control que deje poner 900 mg/dL enseñaría una predicción sobre un valor que el sistema
        de verdad habría rechazado.
        """
        self._entre("glucosa_actual", self.glucosa_actual, GLUCOSA_MIN, GLUCOSA_MAX)
        self._entre("carbs_g", self.carbs_g, CARBS_MIN_G, CARBS_MAX_G)
        self._entre("dosis_ui", self.dosis_ui, INSULINA_MIN_UI, INSULINA_MAX_UI)
        self._entre("umbral_hipo", self.umbral_hipo, *UMBRAL_HIPO_RANGO)
        self._entre("umbral_hiper", self.umbral_hiper, *UMBRAL_HIPER_RANGO)
        self._entre("duracion_accion_h", self.duracion_accion_h, *DIA_RANGO_H)
        self._entre("hora_local", self.hora_local, 0, 23)
        if self.antiguedad_min < 0 or self.minutos_desde_comida < 0 or self.minutos_desde_dosis < 0:
            raise ValueError("una antigüedad no puede ser negativa")

    @staticmethod
    def _entre(nombre: str, valor: float, minimo: float, maximo: float) -> None:
        if not minimo <= valor <= maximo:
            raise ValueError(f"{nombre} fuera de rango: {valor} (válido {minimo}-{maximo})")


@dataclass(frozen=True)
class Horizonte:
    """Lo que el simulador puede decir de un horizonte, y de dónde salió la cifra."""

    horizonte_min: int
    valor: float
    # «modelo» o «linea_base». No es un detalle: una cifra de la línea base presentada como
    # predicción sería la mentira más fácil de contar de todo el proyecto.
    de_donde: str
    alerta: str | None
    modelo_version: str | None = None
    origen_datos: str | None = None
    shap: list[tuple[str, float]] = field(default_factory=list)

    @property
    def se_puede_reportar(self) -> bool:
        """Si esta cifra puede ir al documento final: solo del modelo y con datos reales."""
        return self.de_donde == "modelo" and self.origen_datos == ORIGEN_REPORTABLE


@dataclass(frozen=True)
class Resultado:
    """Lo que el simulador enseña. Es, campo por campo, lo que contestaría `GET /predict`."""

    ahora: datetime
    modo: Modo
    valor_actual: float | None
    antiguedad_min: float | None
    cob_g: float
    iob_ui: float
    puede_alertar_hipoglucemia: bool
    horizontes: list[Horizonte]
    serie_medida: list[tuple[datetime, float]]
    vector: dict[str, float]
    juego: str
    aviso: str | None = None
    nota: str | None = None
    explicacion: RespuestaExplicacion | None = None


def _serie(escenario: Escenario, ahora: datetime) -> list[Punto]:
    """La serie que el escenario implica, en la rejilla de cinco minutos.

    Con sensor se arma la ventana completa hacia atrás con la pendiente que se pidió, porque el
    juego denso necesita los rezagos de 5 a 60 minutos y las medias de 30 y 60. Sin sensor hay
    **un solo punto**, el último pinchazo, que es justo lo que hace que el modo disperso exista:
    no hay serie de la que sacar una derivada.
    """
    zona = ZoneInfo(ZONA)
    if not escenario.con_sensor:
        instante = ahora - timedelta(minutes=escenario.antiguedad_min)
        return [
            Punto(
                ts_utc=instante,
                mg_dl=escenario.glucosa_actual,
                origen=Origen.MANUAL,
                zona_horaria=str(zona),
            )
        ]

    ultima = ahora - timedelta(minutes=escenario.antiguedad_min)
    puntos: list[Punto] = []
    atras = 0
    while atras <= VENTANA_MIN:
        instante = ultima - timedelta(minutes=atras)
        # La pendiente se aplica hacia atrás: si ahora baja 1 mg/dL por minuto, hace una hora
        # estaba 60 mg/dL más arriba. Se recorta al rango válido en lugar de dejar que la
        # pendiente invente una glucosa de 600 tres horas antes.
        valor = escenario.glucosa_actual - escenario.tendencia_mg_dl_min * atras
        valor = min(max(valor, GLUCOSA_MIN), GLUCOSA_MAX)
        puntos.append(
            Punto(
                ts_utc=instante,
                mg_dl=valor,
                origen=Origen.SENSOR,
                zona_horaria=str(zona),
            )
        )
        atras += PASO_MIN
    return sorted(puntos, key=lambda p: p.ts_utc)


def _ahora_con_la_hora(escenario: Escenario) -> datetime:
    """Un instante real cuya hora local es la que se pidió con el control.

    Hace falta un instante de verdad, no uno inventado, porque la hora cíclica y el día de la
    semana se calculan convirtiendo a la zona: una fecha a mano con la zona equivocada mete al
    modelo una hora que no es la que se eligió.
    """
    zona = ZoneInfo(ZONA)
    hoy = datetime.now(tz=zona)
    local = hoy.replace(hour=escenario.hora_local, minute=0, second=0, microsecond=0)
    return local.astimezone(UTC)


def _contexto(escenario: Escenario, ahora: datetime):
    """Las comidas, las dosis y el perfil del escenario. Cero gramos o cero unidades = no hubo."""
    comidas = (
        [
            _Comida(
                ts_utc=ahora - timedelta(minutes=escenario.minutos_desde_comida),
                carbs_g=escenario.carbs_g,
                tiempo_absorcion_min=escenario.tiempo_absorcion_min,
            )
        ]
        if escenario.carbs_g > 0
        else []
    )
    dosis = (
        [
            _Dosis(
                ts_utc=ahora - timedelta(minutes=escenario.minutos_desde_dosis),
                unidades=escenario.dosis_ui,
            )
        ]
        if escenario.dosis_ui > 0
        else []
    )
    perfil = _Perfil(
        umbral_hipo=escenario.umbral_hipo,
        umbral_hiper=escenario.umbral_hiper,
        duracion_accion_insulina=escenario.duracion_accion_h,
    )
    return comidas, dosis, perfil


def calcular(
    escenario: Escenario,
    artefactos: dict[tuple[str, int], Artefacto] | None = None,
    *,
    url_ollama: str | None = None,
    modelo_lenguaje: str = "",
    timeout_s: float = 10.0,
) -> Resultado:
    """Lo que el sistema contestaría con este escenario.

    `artefactos` es el mismo diccionario que la API tiene en memoria, el que devuelve
    `app.services.prediccion.artefacto.cargar`. Vacío, el simulador enseña la línea base de
    persistencia **diciendo que lo es**.

    Sin `url_ollama` la explicación es la plantilla determinista, que no llama a nada. Con ella,
    el simulador pasa por el mismo servicio que la API y queda sujeto a la misma validación: si
    la respuesta trae un número que no se le dio, o un patrón de dosificación, se descarta y
    cae a la plantilla.
    """
    artefactos = artefactos or {}
    ahora = _ahora_con_la_hora(escenario)
    comidas, dosis, perfil = _contexto(escenario, ahora)

    serie = limpiar(_serie(escenario, ahora))
    del_sensor = [p for p in serie if p.origen is Origen.SENSOR and not p.atipica]
    ts_ultima_sensor = del_sensor[-1].ts_utc if del_sensor else None
    modo = modo_actual(bool(del_sensor), ts_ultima_sensor, ahora)
    ultima = serie[-1] if serie else None

    if modo is Modo.SENSOR:
        juego = "denso"
        vector = vector_denso(ahora, serie, comidas, dosis, perfil)
    else:
        juego = "disperso"
        vector = vector_disperso(ahora, ultima, comidas, dosis, perfil, serie=serie)

    base = {
        "ahora": ahora,
        "modo": modo,
        "valor_actual": round(ultima.mg_dl, 1) if ultima else None,
        "antiguedad_min": (
            round((ahora - ultima.ts_utc).total_seconds() / 60, 1) if ultima else None
        ),
        "cob_g": round(vector["cob"], 1),
        "iob_ui": round(vector["iob"], 2),
        "puede_alertar_hipoglucemia": puede_alertar_hipoglucemia(modo),
        "serie_medida": [(p.ts_utc, round(p.mg_dl, 1)) for p in serie if not p.atipica],
        "vector": vector,
        "juego": juego,
    }

    if modo is not Modo.SENSOR:
        # RF-10b, caso P-04. Se declara y no se rellena con algo que parezca una predicción,
        # igual que en la API: el modo disperso existe para el pico postprandial (M-3), no para
        # anticipar una bajada.
        return Resultado(**base, horizontes=[], aviso=AVISO_SIN_SENSOR)

    horizontes = [
        _del_modelo(artefactos[("denso", h)], vector, escenario, h)
        if ("denso", h) in artefactos
        else _de_la_linea_base(escenario, h)
        for h in HORIZONTES
    ]
    sin_modelo = [h.horizonte_min for h in horizontes if h.de_donde != "modelo"]

    return Resultado(
        **base,
        horizontes=horizontes,
        nota=motivo_sin_modelo(sin_modelo) if sin_modelo else None,
        explicacion=_explicacion(
            escenario, horizontes, base, url_ollama, modelo_lenguaje, timeout_s
        ),
    )


def _del_modelo(
    artefacto: Artefacto, vector: dict[str, float], escenario: Escenario, horizonte: int
) -> Horizonte:
    valor, contribuciones = artefacto.predecir(como_fila(vector, CARACTERISTICAS_DENSAS))
    return Horizonte(
        horizonte_min=horizonte,
        valor=round(valor, 1),
        de_donde="modelo",
        alerta=alerta_de(valor, escenario.umbral_hipo, escenario.umbral_hiper),
        modelo_version=artefacto.version,
        origen_datos=artefacto.origen_datos,
        shap=[(nombre, round(aporte, 1)) for nombre, aporte in contribuciones],
    )


def _de_la_linea_base(escenario: Escenario, horizonte: int) -> Horizonte:
    """La persistencia: el valor de ahora, sin alerta y sin factores.

    `alerta=None` a propósito. Comparar el valor de ahora contra el umbral diría «hipoglucemia»
    cuando la persona **ya** está baja, y eso no es anticipar nada: sería pasar por alerta
    predictiva lo que es la lectura actual.
    """
    return Horizonte(
        horizonte_min=horizonte,
        valor=round(escenario.glucosa_actual, 1),
        de_donde="linea_base",
        alerta=None,
    )


def _explicacion(
    escenario: Escenario,
    horizontes: list[Horizonte],
    base: dict,
    url_ollama: str | None,
    modelo_lenguaje: str,
    timeout_s: float,
) -> RespuestaExplicacion | None:
    """La explicación del primer horizonte, por el mismo servicio que usa `POST /explain`.

    Sin modelo no hay valores SHAP, y sin SHAP no hay explicación: el texto se arma **a partir
    de las contribuciones**, nunca de la nada. Inventar una frase para la línea base sería darle
    la apariencia de una predicción explicada.
    """
    primero = next((h for h in horizontes if h.de_donde == "modelo" and h.shap), None)
    if primero is None:
        return None
    entrada = ExplicacionEntrada(
        valor_actual=base["valor_actual"],
        valor_predicho=primero.valor,
        horizonte_min=primero.horizonte_min,
        modo=base["modo"],
        umbral_hipo=escenario.umbral_hipo,
        umbral_hiper=escenario.umbral_hiper,
        cob_g=base["cob_g"],
        iob_ui=base["iob_ui"],
        hora_local=escenario.hora_local,
        shap=[ContribucionShap(variable=n, mg_dl=v) for n, v in primero.shap],
        asistente_activo=escenario.asistente_activo,
    )
    return explicar(entrada, url_ollama, modelo_lenguaje, timeout_s)


def nombres_del_juego(juego: str) -> tuple[str, ...]:
    """Los nombres del juego, en su orden, para que la vista los enseñe sin inventarlos."""
    return CARACTERISTICAS_DENSAS if juego == "denso" else CARACTERISTICAS_DISPERSAS
