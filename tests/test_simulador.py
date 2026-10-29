"""El simulador de la fase 4.

Se prueba `simulador/escenario.py`, que es donde está todo lo que decide algo. La pantalla de
Streamlit no se prueba aquí a propósito: si hiciera falta probarla, sería porque calcula, y no
debe calcular. Lo único que se comprueba de ella es justamente eso.
"""

import json
import math
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest
import xgboost

from app.services.explicacion.servicio import vaciar_cache
from app.services.explicacion.validacion import revisar
from app.services.pipeline.caracteristicas import (
    CARACTERISTICAS_DENSAS,
    CARACTERISTICAS_DISPERSAS,
)
from app.services.prediccion.artefacto import cargar
from referencia.reglas_clinicas import ABSORCION_DEFECTO_MIN, Modo
from simulador.escenario import PASO_MIN, Escenario, calcular, motivo_sin_modelo

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _cache_limpia():
    """La caché de explicaciones es del proceso: compartida entre pruebas las vuelve
    dependientes del orden."""
    vaciar_cache()
    yield
    vaciar_cache()


@pytest.fixture
def artefactos(tmp_path: Path):
    """Dos modelos de juguete, uno por horizonte, con la forma que escribe glucy-ml."""
    generador = np.random.default_rng(7)
    filas = generador.uniform(70, 220, size=(400, len(CARACTERISTICAS_DENSAS)))
    for modelo, horizonte in (("m1", 30), ("m2", 60)):
        booster = xgboost.train(
            {"max_depth": 3, "seed": 1},
            xgboost.DMatrix(
                filas, label=filas[:, 0] * 1.05, feature_names=list(CARACTERISTICAS_DENSAS)
            ),
            num_boost_round=10,
        )
        base = tmp_path / f"{modelo}-v0.1.0"
        booster.save_model(f"{base}.ubj")
        Path(f"{base}.json").write_text(
            json.dumps(
                {
                    "modelo": modelo,
                    "version": "v0.1.0",
                    "horizonte_min": horizonte,
                    "juego": "denso",
                    "caracteristicas": list(CARACTERISTICAS_DENSAS),
                    "origen_datos": "ohiot1dm",
                    "metricas": {"rmse": 18.0},
                }
            )
        )
    return cargar(str(tmp_path))


# ---------------------------------------------------------------------------
# Los límites del escenario: los mismos que valida la app y que revalida la API.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "campo, valor",
    [
        ("glucosa_actual", 900),  # P-02
        ("glucosa_actual", 10),
        ("carbs_g", 400),
        ("dosis_ui", 60),
        ("umbral_hipo", 40),
        ("umbral_hiper", 400),
        ("duracion_accion_h", 12),
        ("hora_local", 24),
    ],
)
def test_01_un_escenario_imposible_no_se_puede_armar(campo, valor):
    """El simulador es lo que se enseña en la defensa: un control que deje poner 900 mg/dL
    enseñaría una predicción sobre un valor que el sistema de verdad habría rechazado."""
    with pytest.raises(ValueError, match="fuera de rango"):
        Escenario(**{campo: valor})


def test_02_una_antiguedad_negativa_tampoco():
    with pytest.raises(ValueError, match="negativa"):
        Escenario(minutos_desde_comida=-5)


# ---------------------------------------------------------------------------
# Modo sensor: el vector, las predicciones y los factores.
# ---------------------------------------------------------------------------


def test_10_con_sensor_el_vector_es_exactamente_el_juego_denso():
    """El orden y los nombres son el contrato con el modelo (decisión 2.9)."""
    resultado = calcular(Escenario(glucosa_actual=140, tendencia_mg_dl_min=-0.5))

    assert resultado.modo is Modo.SENSOR
    assert resultado.juego == "denso"
    assert tuple(resultado.vector) == CARACTERISTICAS_DENSAS


def test_11_la_serie_tiene_la_pendiente_que_se_pidio():
    """Bajando a 1 mg/dL por minuto, hace una hora estaba 60 mg/dL más arriba."""
    resultado = calcular(Escenario(glucosa_actual=120, tendencia_mg_dl_min=-1.0))

    momentos = dict(resultado.serie_medida)
    ahora = max(momentos)
    assert momentos[ahora] == pytest.approx(120, abs=1)
    assert momentos[ahora - timedelta(minutes=60)] == pytest.approx(180, abs=2)
    # La rejilla es la del sensor: cinco minutos entre filas.
    orden = sorted(momentos)
    assert (orden[1] - orden[0]).total_seconds() / 60 == PASO_MIN


def test_12_con_modelo_hay_dos_horizontes_con_sus_factores(artefactos):
    resultado = calcular(Escenario(glucosa_actual=150, tendencia_mg_dl_min=0.4), artefactos)

    assert [h.horizonte_min for h in resultado.horizontes] == [30, 60]
    assert all(h.de_donde == "modelo" for h in resultado.horizontes)
    assert [h.modelo_version for h in resultado.horizontes] == ["m1-v0.1.0", "m2-v0.1.0"]
    assert all(len(h.shap) == 5 for h in resultado.horizontes)
    assert resultado.nota is None


def test_13_la_alerta_se_deriva_del_valor_y_del_umbral(artefactos):
    """El modelo predice un número; la alerta sale de compararlo con el umbral del perfil."""
    alto = calcular(Escenario(glucosa_actual=280, umbral_hiper=180), artefactos)
    assert alto.horizontes[0].alerta == "hiperglucemia"

    # Con el umbral subido, el mismo número ya no dispara nada.
    tranquilo = calcular(Escenario(glucosa_actual=280, umbral_hiper=300), artefactos)
    assert tranquilo.horizontes[0].alerta is None


def test_14_una_cifra_de_datos_sinteticos_no_se_puede_reportar(artefactos, tmp_path: Path):
    manifiesto = next(p for p in tmp_path.glob("m1-*.json") if "ubj" not in p.name)
    datos = json.loads(manifiesto.read_text())
    datos["origen_datos"] = "sintetico"
    manifiesto.write_text(json.dumps(datos))

    resultado = calcular(Escenario(), cargar(str(tmp_path)))

    treinta = resultado.horizontes[0]
    assert treinta.de_donde == "modelo"
    assert treinta.origen_datos == "sintetico"
    assert treinta.se_puede_reportar is False


# ---------------------------------------------------------------------------
# Lo que el simulador NO hace. Son las reglas, no detalles.
# ---------------------------------------------------------------------------


def test_20_sin_sensor_no_hay_prediccion_y_se_declara():
    """RF-10b, caso P-04: no se rellena con algo que parezca una predicción."""
    resultado = calcular(Escenario(con_sensor=False, antiguedad_min=180, glucosa_actual=95))

    assert resultado.modo is Modo.SIN_SENSOR
    assert resultado.horizontes == []
    assert resultado.puede_alertar_hipoglucemia is False
    assert "no se puede anticipar" in resultado.aviso
    assert resultado.juego == "disperso"
    assert tuple(resultado.vector) == CARACTERISTICAS_DISPERSAS


def test_21_una_lectura_vieja_degrada_el_modo_sola(artefactos):
    """Caso P-03: pasados 15 minutos la lectura ya no sirve para predecir."""
    fresca = calcular(Escenario(antiguedad_min=10), artefactos)
    rancia = calcular(Escenario(antiguedad_min=20), artefactos)

    assert fresca.modo is Modo.SENSOR
    assert rancia.modo is Modo.SIN_SENSOR
    assert rancia.horizontes == []
    assert rancia.aviso


def test_22_sin_modelo_se_enseña_la_linea_base_y_se_dice_que_lo_es():
    resultado = calcular(Escenario(glucosa_actual=110))

    assert all(h.de_donde == "linea_base" for h in resultado.horizontes)
    assert all(h.valor == 110 for h in resultado.horizontes)
    # La persistencia repite el valor de ahora: no puede anticipar nada, así que no alerta.
    assert all(h.alerta is None for h in resultado.horizontes)
    assert all(h.se_puede_reportar is False for h in resultado.horizontes)
    assert "no es una predicción" in resultado.nota.lower()


def test_23_la_linea_base_no_alerta_aunque_la_persona_ya_este_baja():
    """Comparar el valor de ahora contra el umbral diría «hipoglucemia» por la lectura actual,
    y eso sería pasar por alerta predictiva lo que es una medición."""
    resultado = calcular(Escenario(glucosa_actual=55, umbral_hipo=70))

    assert resultado.valor_actual == 55
    assert all(h.alerta is None for h in resultado.horizontes)


def test_24_la_nota_dice_cual_horizonte_le_falta_modelo(artefactos):
    """Tener el de 30 y no el de 60 es el caso normal mientras se entrena."""
    del artefactos[("denso", 60)]
    resultado = calcular(Escenario(), artefactos)

    assert resultado.horizontes[0].de_donde == "modelo"
    assert resultado.horizontes[1].de_donde == "linea_base"
    assert "60 min" in resultado.nota and "30 min" not in resultado.nota


def test_25_sin_comida_registrada_no_se_inventa_ninguna():
    """D-9 y RF-37. Cero gramos es «no hubo», no una comida de cero."""
    resultado = calcular(Escenario(glucosa_actual=200, carbs_g=0))

    assert resultado.cob_g == 0
    # En el juego disperso, lo que no hay es NaN y no cero.
    sin_sensor = calcular(Escenario(con_sensor=False, antiguedad_min=60, carbs_g=0))
    assert math.isnan(sin_sensor.vector["carbs_g"])


def test_26_ni_la_pantalla_ni_el_calculo_sugieren_una_dosis():
    """Regla 7, la frontera con un dispositivo médico regulado.

    Se revisa el texto de los dos archivos con el mismo validador que filtra lo que contesta
    el modelo de lenguaje: si alguna vez aparece ahí un patrón de dosificación, esta prueba lo
    detiene antes de que llegue a una pantalla.
    """
    revisadas = 0
    for archivo in ("simulador/escenario.py", "simulador/pantalla.py"):
        texto = (RAIZ / archivo).read_text(encoding="utf-8")
        # Sin números permitidos: cualquier cifra en una frase de dosificación saltaría.
        for linea in texto.splitlines():
            if "dosis" not in linea.lower() and "unidades" not in linea.lower():
                continue
            revisadas += 1
            rechazo = revisar(linea, [])
            assert rechazo is None or rechazo.motivo != "patron_de_dosificacion", linea
    # Si un día nadie menciona una dosis en esos archivos, esta prueba pasaría sin revisar
    # nada y nadie se enteraría. Los dos archivos hablan de dosis; si dejan de hacerlo, mejor
    # que la prueba se caiga y alguien la mire.
    assert revisadas > 5


# ---------------------------------------------------------------------------
# Los números tienen que ser los mismos que los de la referencia y los de la API.
# ---------------------------------------------------------------------------


def test_30_cob_de_60_g_con_180_min_a_los_90_min_son_30_g():
    """Caso P-11, el que más se cita del proyecto. Absorción lineal, D-8."""
    resultado = calcular(
        Escenario(carbs_g=60, minutos_desde_comida=90, tiempo_absorcion_min=ABSORCION_DEFECTO_MIN)
    )

    assert resultado.cob_g == pytest.approx(30.0)
    assert resultado.vector["cob"] == pytest.approx(30.0)


def test_31_pasado_el_tiempo_de_absorcion_el_cob_es_cero():
    resultado = calcular(Escenario(carbs_g=60, minutos_desde_comida=200))
    assert resultado.cob_g == 0


def test_32_el_iob_baja_con_el_tiempo_y_depende_de_la_duracion_de_accion():
    temprano = calcular(Escenario(dosis_ui=6, minutos_desde_dosis=30))
    tarde = calcular(Escenario(dosis_ui=6, minutos_desde_dosis=240))
    larga = calcular(Escenario(dosis_ui=6, minutos_desde_dosis=240, duracion_accion_h=8))

    assert temprano.iob_ui > tarde.iob_ui
    assert larga.iob_ui > tarde.iob_ui


def test_33_el_simulador_contesta_lo_mismo_que_el_endpoint(artefactos):
    """El punto del simulador: no calcula por su cuenta.

    Se arma el vector con el simulador y se alimenta el **mismo** artefacto a mano. Si algún día
    el simulador empieza a hacer su propia cuenta, este número deja de coincidir.
    """
    from app.services.pipeline.caracteristicas import como_fila

    resultado = calcular(Escenario(glucosa_actual=165, tendencia_mg_dl_min=-0.6), artefactos)
    a_mano, _ = artefactos[("denso", 30)].predecir(
        como_fila(resultado.vector, CARACTERISTICAS_DENSAS)
    )

    assert resultado.horizontes[0].valor == pytest.approx(round(a_mano, 1))


# ---------------------------------------------------------------------------
# La explicación.
# ---------------------------------------------------------------------------


def test_40_la_explicacion_sale_de_la_plantilla_cuando_no_hay_modelo_de_lenguaje(artefactos):
    resultado = calcular(Escenario(glucosa_actual=130), artefactos)

    assert resultado.explicacion is not None
    assert resultado.explicacion.origen == "plantilla"
    assert "estimación" in resultado.explicacion.explicacion


def test_41_sin_factores_no_hay_explicacion():
    """Sin SHAP no hay de qué armar el texto. Inventar una frase para la línea base le daría
    la apariencia de una predicción explicada."""
    assert calcular(Escenario()).explicacion is None


def test_42_la_explicacion_nunca_trae_un_patron_de_dosificacion(artefactos):
    resultado = calcular(Escenario(glucosa_actual=65, umbral_hipo=70), artefactos)

    texto = resultado.explicacion.explicacion.lower()
    for prohibido in ("unidades", " ui", "te inyectes", "inyéctate", "toma "):
        assert prohibido not in texto


def test_43_con_el_asistente_apagado_tampoco_se_llama_a_nadie(artefactos):
    """La persona puede apagarlo en Ajustes y entonces se arma la plantilla, sin red."""
    resultado = calcular(
        Escenario(asistente_activo=False), artefactos, url_ollama="http://no-existe:1"
    )

    assert resultado.explicacion.origen == "plantilla"
    assert resultado.explicacion.motivo == "sin_asistente"


# ---------------------------------------------------------------------------
# La pantalla: lo único que se le exige es no calcular.
# ---------------------------------------------------------------------------


def test_50_la_pantalla_no_importa_ninguna_regla():
    """Misma regla que en la app: la vista dibuja y recoge gestos, no calcula.

    Si un día la pantalla importa `referencia.reglas_clinicas` o el pipeline, la regla se fue
    a un archivo que no se puede probar sin navegador.
    """
    texto = (RAIZ / "simulador" / "pantalla.py").read_text(encoding="utf-8")
    lineas = [ln for ln in texto.splitlines() if ln.startswith(("import ", "from "))]

    prohibidos = ("referencia", "app.services.pipeline", "app.services.explicacion")
    assert not [ln for ln in lineas if any(p in ln for p in prohibidos)]


def test_51_la_pantalla_no_se_llama_app_py():
    """Streamlit mete la carpeta del script al frente de `sys.path`, así que un
    `simulador/app.py` se vuelve el módulo `app` y tapa al paquete del backend. El error que
    sale —«'app' is not a package»— no apunta a la causa, y costó un rato encontrarlo."""
    assert not (RAIZ / "simulador" / "app.py").exists()
    assert (RAIZ / "simulador" / "pantalla.py").exists()


def test_52_el_motivo_sin_modelo_nombra_los_horizontes():
    assert "30 min y 60 min" in motivo_sin_modelo([30, 60])
    assert motivo_sin_modelo([60]).startswith("A 60 min")


def test_53_la_hora_del_escenario_es_la_hora_local_y_no_la_utc():
    """La hora entra al modelo (`hora_sin`, `hora_cos`). Una bajada de las 03:00 metida como
    las 09:00 es otra cosa, y en México son seis horas de diferencia."""
    from zoneinfo import ZoneInfo

    from simulador.escenario import ZONA

    resultado = calcular(Escenario(hora_local=3))

    assert resultado.ahora.astimezone(ZoneInfo(ZONA)).hour == 3
    # Y se guarda en UTC, que es la regla 5: UTC más la zona, nunca una hora suelta.
    assert resultado.ahora.utcoffset() == timedelta(0)
    assert resultado.ahora.astimezone(ZoneInfo(ZONA)).hour != resultado.ahora.hour
