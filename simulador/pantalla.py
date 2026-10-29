"""El simulador de Glucy en Streamlit (fase 4). **Esta vista no calcula nada.**

Mueve controles, llama a `escenario.calcular` y dibuja lo que contesta. Ni una regla clínica
aquí, por la misma razón que en la app: lo que puede lastimar a alguien vive en una capa que se
prueba sin interfaz.

Se corre con:

    GLUCY_JWT_SECRET=cualquiera streamlit run simulador/pantalla.py

La variable hace falta solo porque `app.config` se niega a arrancar sin ella; el simulador no
firma ningún token y **no abre la base de datos ni la red**: todo sale del escenario que se
teclea en la pantalla.

Este archivo **no puede llamarse `app.py`**, y la razón no se ve hasta que se corre: Streamlit
mete la carpeta del script al frente de `sys.path`, así que un `simulador/app.py` se convierte
en el módulo `app` y tapa al paquete `app/` del backend. El error que sale es
`No module named 'app.services'; 'app' is not a package`, que no apunta a la causa. Por eso
`pantalla.py`.
"""

import sys
from datetime import timedelta
from pathlib import Path

# La raíz del repositorio, para que `import app...` y `import referencia...` funcionen corra
# Streamlit desde donde sea. Streamlit solo garantiza la carpeta del script en `sys.path`.
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import altair as alt
import pandas as pd
import streamlit as st

from app.services.prediccion.artefacto import ORIGEN_REPORTABLE, cargar
from simulador.escenario import (
    NOTA_LINEA_BASE,
    ZONA,
    Escenario,
    calcular,
    nombres_del_juego,
)

# El orden manda en la gráfica: el primero es el trazo continuo. Lo medido va primero siempre.
SERIES = ["Medido", "Estimado", "Línea base"]

AVISO_MEDICO = (
    "Glucy no es un dispositivo médico certificado. Informa; no prescribe ni administra, y "
    "**jamás calcula ni sugiere una dosis de insulina**."
)

st.set_page_config(page_title="Simulador de Glucy", page_icon="📈", layout="wide")


@st.cache_resource
def _artefactos(ruta: str):
    """Los modelos, cargados una vez por sesión de Streamlit, con el mismo cargador que la API."""
    return cargar(ruta or None)


st.title("Simulador de Glucy")
st.caption(
    "Un escenario a mano y lo que el sistema contestaría con él. Los números salen del mismo "
    "pipeline, el mismo artefacto y el mismo explicador que usa la API: el simulador no "
    "calcula por su cuenta."
)

with st.sidebar:
    st.header("El escenario")
    ruta = st.text_input(
        "Carpeta de artefactos",
        value="",
        help="La misma de GLUCY_RUTA_ARTEFACTO_MODELO. Vacía: se enseña la línea base.",
    )
    con_sensor = st.toggle("Sensor conectado", value=True)
    glucosa = st.slider("Glucosa de ahora (mg/dL)", 20, 600, 120, step=1)
    tendencia = st.slider(
        "Tendencia (mg/dL por minuto)",
        -3.0,
        3.0,
        0.0,
        step=0.1,
        help="Negativa, va bajando. Es lo que arma la pendiente de la serie.",
        disabled=not con_sensor,
    )
    antiguedad = st.slider(
        "Antigüedad de la última lectura (min)",
        0,
        240,
        0 if con_sensor else 120,
        step=5,
        help="Con sensor, pasados 15 minutos el modo se degrada solo.",
    )
    hora = st.slider("Hora del día", 0, 23, 8, help=f"Hora local de {ZONA}.")

    st.subheader("La comida")
    carbs = st.slider("Carbohidratos (g)", 0, 300, 0, step=5, help="Cero: no hubo comida.")
    desde_comida = st.slider("Hace cuánto (min)", 0, 300, 0, step=5, key="comida")
    absorcion = st.select_slider(
        "Tiempo de absorción (min)", options=[30, 60, 120, 180, 240, 300], value=180
    )

    st.subheader("La insulina")
    st.caption("Se registra lo que la persona dice haberse aplicado. Nunca se sugiere una dosis.")
    dosis = st.slider("Bolo (UI)", 0.0, 50.0, 0.0, step=0.5, help="Cero: no hubo dosis.")
    desde_dosis = st.slider("Hace cuánto (min)", 0, 480, 0, step=5, key="dosis")
    duracion = st.slider("Duración de acción (h)", 2.0, 8.0, 5.0, step=0.5)

    st.subheader("El perfil")
    umbral_hipo = st.slider("Umbral de hipoglucemia", 50, 90, 70)
    umbral_hiper = st.slider("Umbral de hiperglucemia", 140, 300, 180)

    st.subheader("La explicación")
    asistente = st.toggle("Asistente activo", value=True)
    url_ollama = st.text_input(
        "Ollama", value="", help="Vacío: la plantilla determinista, que no llama a nada."
    )
    modelo_lenguaje = st.text_input("Modelo de lenguaje", value="qwen3:8b")

try:
    escenario = Escenario(
        glucosa_actual=float(glucosa),
        tendencia_mg_dl_min=float(tendencia) if con_sensor else 0.0,
        hora_local=int(hora),
        con_sensor=con_sensor,
        antiguedad_min=float(antiguedad),
        carbs_g=float(carbs),
        minutos_desde_comida=float(desde_comida),
        tiempo_absorcion_min=int(absorcion),
        dosis_ui=float(dosis),
        minutos_desde_dosis=float(desde_dosis),
        duracion_accion_h=float(duracion),
        umbral_hipo=float(umbral_hipo),
        umbral_hiper=float(umbral_hiper),
        asistente_activo=asistente,
    )
except ValueError as error:
    st.error(str(error))
    st.stop()

resultado = calcular(
    escenario,
    _artefactos(ruta),
    url_ollama=url_ollama or None,
    modelo_lenguaje=modelo_lenguaje,
)

# ---------------------------------------------------------------------------
# El aviso del modo sin sensor va arriba, fijo y no descartable (RF-10b, P-04). Es la primera
# cosa que se lee, antes de cualquier cifra.
# ---------------------------------------------------------------------------
if resultado.aviso:
    st.warning(f"⚠️ **Sin sensor.** {resultado.aviso}", icon="⚠️")

izquierda, derecha = st.columns([2, 1])

with izquierda:
    st.subheader("Lo medido y lo estimado")

    medidas = pd.DataFrame(
        [{"momento": ts, "mg_dl": v, "serie": "Medido"} for ts, v in resultado.serie_medida]
    )
    estimadas = pd.DataFrame(
        [
            {
                "momento": resultado.ahora + timedelta(minutes=h.horizonte_min),
                "mg_dl": h.valor,
                "serie": "Estimado" if h.de_donde == "modelo" else "Línea base",
            }
            for h in resultado.horizontes
        ]
    )
    if not estimadas.empty and not medidas.empty:
        # Un puente **por serie** desde el último punto medido. Sin él, un horizonte solo
        # —el caso normal mientras falta uno de los dos modelos— sale como un punto suelto en
        # el aire, sin línea que lo ate a lo medido y sin que se vea de dónde parte.
        puentes = []
        for serie in estimadas["serie"].unique():
            puente = medidas.iloc[[-1]].copy()
            puente["serie"] = serie
            puentes.append(puente)
        estimadas = pd.concat([*puentes, estimadas], ignore_index=True)

    datos = pd.concat([medidas, estimadas], ignore_index=True)

    # La regla de interfaz que no se puede perder: lo medido es línea **continua** y lo estimado
    # es **punteada**, y el color no es el único portador de la diferencia. Una persona medio
    # dormida tiene que distinguirlas sin leer la leyenda.
    #
    # El dominio y el rango van escritos a mano, y no es manía: sin ellos Altair reparte los
    # trazos por orden alfabético de la serie, y «Estimado» y «Línea base» van antes que
    # «Medido». Lo medido salía punteado y la estimación continua, justo al revés de la regla.
    # Se vio corriendo la pantalla, no leyendo el código.
    base_grafica = alt.Chart(datos).encode(
        x=alt.X("momento:T", title="Hora"),
        y=alt.Y("mg_dl:Q", title="mg/dL", scale=alt.Scale(zero=False)),
        color=alt.Color(
            "serie:N",
            title="",
            scale=alt.Scale(
                domain=SERIES,
                range=["#1f4e79", "#c2410c", "#6b7280"],
            ),
        ),
        strokeDash=alt.StrokeDash(
            "serie:N",
            title="",
            scale=alt.Scale(domain=SERIES, range=[[1, 0], [6, 4], [2, 3]]),
        ),
    )
    bandas = (
        alt.Chart(pd.DataFrame([{"desde": escenario.umbral_hipo, "hasta": escenario.umbral_hiper}]))
        .mark_rect(opacity=0.08)
        .encode(y="desde:Q", y2="hasta:Q")
    )
    st.altair_chart(
        bandas + base_grafica.mark_line(point=True, strokeWidth=3),
        use_container_width=True,
    )
    st.caption(
        f"La banda es el rango objetivo, {escenario.umbral_hipo:.0f}–"
        f"{escenario.umbral_hiper:.0f} mg/dL. Línea continua: lo medido. Punteada: lo estimado."
    )

with derecha:
    st.subheader("Ahora")
    st.metric(
        "Glucosa",
        f"{resultado.valor_actual:.0f} mg/dL" if resultado.valor_actual else "sin dato",
        delta=(
            f"hace {resultado.antiguedad_min:.0f} min"
            if resultado.antiguedad_min is not None
            else None
        ),
        delta_color="off",
    )
    st.metric("Carbohidratos que siguen activos", f"{resultado.cob_g:.0f} g")
    st.metric("Insulina que sigue activa", f"{resultado.iob_ui:.1f} UI")
    st.write(f"**Modo:** {resultado.modo.value.replace('_', ' ')} · juego {resultado.juego}")
    if not resultado.puede_alertar_hipoglucemia:
        st.write("**No puede anticipar una glucosa baja.**")

st.divider()

if resultado.nota:
    st.info(resultado.nota)
    st.caption(NOTA_LINEA_BASE)

if resultado.horizontes:
    st.subheader("A media hora y a una hora")
    columnas = st.columns(len(resultado.horizontes))
    for columna, h in zip(columnas, resultado.horizontes, strict=True):
        with columna:
            etiqueta = "estimado" if h.de_donde == "modelo" else "línea base"
            columna.metric(f"En {h.horizonte_min} min ({etiqueta})", f"{h.valor:.0f} mg/dL")
            if h.alerta:
                # Palabra, no solo color: la app se revisa en escala de grises.
                columna.error(f"Alerta de {h.alerta}")
            if h.modelo_version:
                columna.caption(f"Modelo {h.modelo_version}")
            if h.origen_datos and h.origen_datos != ORIGEN_REPORTABLE:
                columna.caption(
                    f"⚠️ entrenado con datos «{h.origen_datos}»: estas cifras no van al "
                    "documento final."
                )

    con_factores = [h for h in resultado.horizontes if h.shap]
    if con_factores:
        st.subheader("Por qué")
        primero = con_factores[0]
        st.dataframe(
            pd.DataFrame([{"variable": n, "aporte (mg/dL)": v} for n, v in primero.shap]).set_index(
                "variable"
            ),
            use_container_width=True,
        )
        st.caption(
            "Contribuciones TreeSHAP del propio modelo, las cinco más grandes. Son los mismos "
            "números que recibe el explicador: el modelo de lenguaje redacta, no calcula."
        )

if resultado.explicacion:
    st.subheader("En palabras")
    st.success(resultado.explicacion.explicacion)
    detalle = f"Origen: {resultado.explicacion.origen}"
    if resultado.explicacion.motivo:
        detalle += f" · motivo: {resultado.explicacion.motivo}"
    if resultado.explicacion.modelo:
        detalle += f" · {resultado.explicacion.modelo}"
    st.caption(detalle)

with st.expander("El vector que recibe el modelo"):
    st.caption(
        "En este orden y con estos nombres. Un nombre de más o de menos alimenta al modelo con "
        "las columnas cambiadas de lugar, y eso da números plausibles y equivocados."
    )
    st.dataframe(
        pd.DataFrame(
            [
                {"característica": nombre, "valor": resultado.vector[nombre]}
                for nombre in nombres_del_juego(resultado.juego)
            ]
        ).set_index("característica"),
        use_container_width=True,
    )
    st.caption("Lo que falta es NaN y nunca cero: un rezago que no existe no es una glucosa de 0.")

st.divider()
st.caption(AVISO_MEDICO)
