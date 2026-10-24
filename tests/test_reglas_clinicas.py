"""
Pruebas de las reglas clínicas de Glucy.

Cada prueba apunta a un caso del punto 22.2 del reporte o a un requisito concreto. Son las
reglas donde un error tiene consecuencia clínica, y por eso se prueban sin interfaz, sin
cámara y sin dispositivo. Correr con:  pytest -q
"""

from datetime import UTC, datetime, timedelta

import pytest

from referencia.reglas_clinicas import (
    Modo,
    Origen,
    cob,
    cob_total,
    debe_sincronizar,
    es_atipica_por_tasa,
    fraccion_insulina_activa,
    gmi_es_fiable,
    hay_suficientes_dias,
    indicadores,
    iob,
    modo_actual,
    plantilla_explicacion,
    porcentaje_clarke_ab,
    puede_alertar_hipoglucemia,
    se_puede_interpolar,
    sensibilidad_hipoglucemia,
    tasa_falsas_alarmas,
    validar_comida,
    validar_dosis,
    validar_lectura,
    validar_perfil,
    zona_clarke,
)

AHORA = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)


# --- Validación -------------------------------------------------------------

def test_P01_ocr_sin_confirmar_no_se_guarda():
    """P-01: el OCR lee con alta confianza y el usuario no confirma → no se guarda nada.
    No existe umbral que decida por el usuario (D-11)."""
    r = validar_lectura(112, AHORA, AHORA, Origen.FOTO_GLUCOMETRO, confirmada_por_usuario=False)
    assert r is not None and "sin confirmar" in r.motivo


def test_P02_valor_fuera_de_rango_no_se_guarda():
    """P-02: 900 mg/dL es error de captura, no fisiología."""
    r = validar_lectura(900, AHORA, AHORA, Origen.MANUAL)
    assert r is not None and "rango fisiológico" in r.motivo


def test_limites_del_rango_si_se_aceptan():
    assert validar_lectura(20, AHORA, AHORA, Origen.MANUAL) is None
    assert validar_lectura(600, AHORA, AHORA, Origen.MANUAL) is None


def test_marca_de_tiempo_futura_se_rechaza():
    r = validar_lectura(110, AHORA + timedelta(minutes=1), AHORA, Origen.MANUAL)
    assert r is not None and "futura" in r.motivo


def test_lectura_valida_pasa():
    assert validar_lectura(112, AHORA - timedelta(minutes=2), AHORA, Origen.SENSOR) is None


def test_tasa_imposible_solo_aplica_a_la_serie_continua():
    # 50 mg/dL en 5 minutos = 10 mg/dL por minuto
    assert es_atipica_por_tasa(100, AHORA - timedelta(minutes=5), 150, AHORA, Origen.SENSOR)
    # el mismo salto entre dos pinchazos no es atípico: cualquier tasa es posible
    assert not es_atipica_por_tasa(100, AHORA - timedelta(minutes=5), 150, AHORA, Origen.MANUAL)


def test_interpolacion_solo_hasta_15_minutos_y_solo_en_sensor():
    assert se_puede_interpolar(15, Origen.SENSOR)
    assert not se_puede_interpolar(16, Origen.SENSOR)
    assert not se_puede_interpolar(10, Origen.MANUAL)


# --- COB --------------------------------------------------------------------

def test_P11_cob_60g_180min_a_los_90min_son_30g():
    """P-11, el caso escrito en el reporte."""
    assert cob(60, 90, 180) == pytest.approx(30.0)


def test_cob_es_cero_pasado_el_tiempo_de_absorcion():
    assert cob(60, 180, 180) == 0.0
    assert cob(60, 400, 180) == 0.0


def test_36_cob_con_minutos_negativos_devuelve_cero():
    """Paso 2, decisión 2.3: antes lanzaba ValueError y el Swift devolvía los gramos completos.
    Una comida que todavía no ocurre no tiene carbohidratos activos."""
    assert cob(60, -1, 180) == 0.0
    assert cob(60, -0.001, 180) == 0.0
    assert cob_total([(60, -30, 180), (60, 90, 180)]) == pytest.approx(30.0)


def test_cob_con_los_presets_de_30_y_300():
    assert cob(20, 15, 30) == pytest.approx(10.0)
    assert cob(90, 150, 300) == pytest.approx(45.0)


def test_cob_total_suma_varias_comidas_y_no_inventa_ninguna():
    assert cob_total([(60, 90, 180), (30, 0, 180)]) == pytest.approx(60.0)
    assert cob_total([]) == 0.0  # sin registro no hay dato (D-9, RF-37)


# --- IOB --------------------------------------------------------------------

def test_iob_empieza_completa_y_termina_en_cero():
    assert fraccion_insulina_activa(0) == 1.0
    assert fraccion_insulina_activa(300) == 0.0   # DIA de 5 h
    assert fraccion_insulina_activa(999) == 0.0


def test_iob_decrece_de_forma_monotona():
    valores = [fraccion_insulina_activa(m) for m in range(0, 301, 15)]
    assert all(a >= b for a, b in zip(valores, valores[1:], strict=False))


def test_iob_a_una_hora_queda_entre_el_60_y_el_85_por_ciento():
    """Con pico a los 75 min todavía queda la mayor parte de la dosis activa a la hora."""
    assert 0.60 < fraccion_insulina_activa(60) < 0.85


def test_iob_respeta_la_duracion_de_accion_del_perfil():
    """El perfil pregunta la duración de acción porque cambia la curva entera:
    con 2 h, a las 2 h ya no queda nada activo."""
    assert fraccion_insulina_activa(120, dia_h=2) == 0.0
    # con una duración más larga queda más insulina activa a la misma hora
    assert fraccion_insulina_activa(120, dia_h=8) > fraccion_insulina_activa(120, dia_h=5)


def test_iob_suma_varias_dosis():
    assert iob([(4, 0), (2, 300)]) == pytest.approx(4.0)


# --- Indicadores ------------------------------------------------------------

def test_gmi_y_tir():
    ind = indicadores([70, 100, 180, 200, 50])
    assert ind.promedio == pytest.approx(120.0)
    assert ind.tir == pytest.approx(60.0)      # 70, 100 y 180 están en 70-180
    assert ind.tbr == pytest.approx(20.0)      # 50 está por debajo de 70
    assert ind.tar == pytest.approx(20.0)      # 200 está por encima de 180
    assert ind.gmi == pytest.approx(3.31 + 0.02392 * 120)


def test_los_umbrales_del_perfil_mueven_tbr_y_tar_pero_no_el_tir():
    valores = [80, 100, 160]
    por_omision = indicadores(valores)
    assert por_omision.tbr == 0.0 and por_omision.tar == 0.0
    ajustados = indicadores(valores, umbral_hipo=90, umbral_hiper=140)
    assert ajustados.tbr == pytest.approx(33.333, abs=0.01)   # 80 está por debajo de 90
    assert ajustados.tar == pytest.approx(33.333, abs=0.01)   # 160 está por encima de 140
    assert ajustados.tir == por_omision.tir == 100.0          # el TIR sigue siendo 70-180


def test_sin_lecturas_no_se_muestra_cero_sino_que_falta_dato():
    with pytest.raises(ValueError):
        indicadores([])


# --- Modo y alerta ----------------------------------------------------------

def test_P03_lectura_vieja_degrada_a_modo_sin_sensor():
    """P-03: pasado el umbral de frescura la app no sigue prediciendo con datos viejos."""
    assert modo_actual(True, AHORA - timedelta(minutes=5), AHORA) is Modo.SENSOR
    assert modo_actual(True, AHORA - timedelta(minutes=15), AHORA) is Modo.SENSOR
    assert modo_actual(True, AHORA - timedelta(minutes=16), AHORA) is Modo.SIN_SENSOR


def test_sin_permiso_de_healthkit_siempre_es_modo_sin_sensor():
    assert modo_actual(False, AHORA, AHORA) is Modo.SIN_SENSOR
    assert modo_actual(True, None, AHORA) is Modo.SIN_SENSOR


def test_P04_sin_sensor_no_hay_alerta_anticipada():
    """P-04, RF-10b, riesgo R-6."""
    assert puede_alertar_hipoglucemia(Modo.SENSOR)
    assert not puede_alertar_hipoglucemia(Modo.SIN_SENSOR)


# --- Sincronización ---------------------------------------------------------

def test_P08_no_sincroniza_con_datos_moviles_salvo_que_el_usuario_lo_fuerce():
    assert not debe_sincronizar(hay_wifi=False, pendientes=12)
    assert debe_sincronizar(hay_wifi=False, pendientes=12, forzado_por_usuario=True)
    assert debe_sincronizar(hay_wifi=True, pendientes=12)
    assert not debe_sincronizar(hay_wifi=True, pendientes=0)


# --- Métricas del modelo ----------------------------------------------------

def test_clarke_zona_a_cuando_el_error_es_menor_al_20_por_ciento():
    assert zona_clarke(100, 110) == "A"
    assert zona_clarke(60, 65) == "A"      # los dos por debajo de 70


def test_clarke_zona_e_es_la_inversion_peligrosa():
    assert zona_clarke(60, 200) == "E"     # dice hiper cuando hay hipo
    assert zona_clarke(200, 60) == "E"


def test_clarke_no_confunde_un_error_grande_en_zona_alta_con_uno_peligroso():
    """Un error de 30 mg/dL cerca de 200 no tiene la misma consecuencia que cerca de 70."""
    assert zona_clarke(200, 230) == "A"
    assert zona_clarke(70, 100) == "D"


def test_porcentaje_clarke_ab():
    reales = [100, 120, 60, 200]
    predichos = [105, 130, 65, 210]
    assert porcentaje_clarke_ab(reales, predichos) == pytest.approx(100.0)


def test_sensibilidad_y_falsas_alarmas():
    reales = [60, 65, 90, 120]
    predichos = [62, 80, 68, 130]
    # dos episodios reales por debajo de 70; solo uno se anticipó
    assert sensibilidad_hipoglucemia(reales, predichos) == pytest.approx(50.0)
    # dos alertas emitidas (62 y 68); la del real 90 es falsa
    assert tasa_falsas_alarmas(reales, predichos) == pytest.approx(50.0)


def test_sin_alertas_la_tasa_de_falsas_alarmas_es_cero():
    assert tasa_falsas_alarmas([120, 130], [125, 128]) == 0.0


# --- Plantilla determinista -------------------------------------------------

def test_P13_la_plantilla_no_depende_de_nada_externo_y_no_sugiere_dosis():
    """P-13: si el modelo de lenguaje no responde en 10 s, entra esta plantilla."""
    texto = plantilla_explicacion(
        120, 85, [("insulina activa", -22), ("carbohidratos activos", 6), ("tendencia", -9)]
    )
    assert "insulina activa" in texto and "-22" in texto
    assert "confirmar con una medición" in texto
    for prohibido in ("unidades", "UI", "inyect", "toma "):
        assert prohibido not in texto


# --- Validación de comidas, dosis y perfil (paso 2, prueba 35) --------------
# Los dos extremos de cada rango y el primer valor de cada lado que ya no pasa. Los casos con
# varias fallas a la vez fijan el orden de las comprobaciones, que es el del Swift.

ANTES = AHORA - timedelta(minutes=5)
FUTURA = AHORA + timedelta(minutes=1)


@pytest.mark.parametrize(
    ("carbs", "absorcion", "porciones", "ts", "fragmento"),
    [
        (0, 180, 1, ANTES, None),
        (300, 180, 1, ANTES, None),
        (-0.1, 180, 1, ANTES, "0-300 g"),
        (300.1, 180, 1, ANTES, "0-300 g"),
        (60, 30, 1, ANTES, None),
        (60, 300, 1, ANTES, None),
        (60, 29, 1, ANTES, "30-300 min"),
        (60, 301, 1, ANTES, "30-300 min"),
        (60, 180, 0.5, ANTES, None),
        (60, 180, 0, ANTES, "porciones"),
        (60, 180, -1, ANTES, "porciones"),
        (60, 180, 1, AHORA, None),
        (60, 180, 1, FUTURA, "futura"),
        # Varias fallas: gana la que el Swift revisa primero.
        (301, 20, 0, FUTURA, "0-300 g"),
        (60, 20, 0, FUTURA, "30-300 min"),
        (60, 180, 0, FUTURA, "porciones"),
    ],
)
def test_35_validar_comida(carbs, absorcion, porciones, ts, fragmento):
    r = validar_comida(carbs, absorcion, porciones, ts, AHORA)
    if fragmento is None:
        assert r is None
    else:
        assert r is not None and fragmento in r.motivo


@pytest.mark.parametrize(
    ("unidades", "ts", "fragmento"),
    [
        (0.5, ANTES, None),
        (50, ANTES, None),
        (2.5, ANTES, None),
        (0, ANTES, "mayor que cero"),
        (-1, ANTES, "mayor que cero"),
        (50.5, ANTES, "0-50 UI"),
        (2.3, ANTES, "resolución"),
        (0.1, ANTES, "resolución"),
        (6, AHORA, None),
        (6, FUTURA, "futura"),
        # Varias fallas: gana la que el Swift revisa primero.
        (0, FUTURA, "mayor que cero"),
        (50.3, FUTURA, "0-50 UI"),
        (2.3, FUTURA, "resolución"),
    ],
)
def test_35_validar_dosis(unidades, ts, fragmento):
    r = validar_dosis(unidades, ts, AHORA)
    if fragmento is None:
        assert r is None
    else:
        assert r is not None and fragmento in r.motivo


PERFIL_VALIDO = {
    "anio_nacimiento": 2001,
    "umbral_hipo": 70,
    "umbral_hiper": 180,
    "duracion_accion_h": 5,
    "tiempo_absorcion_min": 180,
    "tipo_insulina_rapida": "lispro",
}


@pytest.mark.parametrize(
    ("cambios", "fragmento"),
    [
        ({}, None),
        # AHORA es 2026: 2011 da 15 años y 1906 da 120, los dos extremos.
        ({"anio_nacimiento": 2011}, None),
        ({"anio_nacimiento": 1906}, None),
        ({"anio_nacimiento": 2012}, "menor que 15"),
        ({"anio_nacimiento": 1905}, "más de 120"),
        ({"anio_nacimiento": 2027}, "futuro"),
        ({"umbral_hipo": 50}, None),
        ({"umbral_hipo": 90}, None),
        ({"umbral_hipo": 49.9}, "50-90"),
        ({"umbral_hipo": 90.1}, "50-90"),
        ({"umbral_hiper": 140}, None),
        ({"umbral_hiper": 300}, None),
        ({"umbral_hiper": 139}, "140-300"),
        ({"umbral_hiper": 301}, "140-300"),
        ({"duracion_accion_h": 2}, None),
        ({"duracion_accion_h": 8}, None),
        ({"duracion_accion_h": 1.9}, "2-8 h"),
        ({"duracion_accion_h": 9}, "2-8 h"),
        ({"tiempo_absorcion_min": 30}, None),
        ({"tiempo_absorcion_min": 300}, None),
        ({"tiempo_absorcion_min": 29}, "30-300 min"),
        ({"tiempo_absorcion_min": 301}, "30-300 min"),
        ({"tipo_insulina_rapida": None}, None),
        ({"tipo_insulina_rapida": "x" * 40}, None),
        ({"tipo_insulina_rapida": "x" * 41}, "40 caracteres"),
        # Varias fallas: gana la que el Swift revisa primero.
        ({"anio_nacimiento": 2020, "umbral_hipo": 40}, "menor que 15"),
        ({"umbral_hipo": 40, "umbral_hiper": 320}, "50-90"),
        ({"tipo_insulina_rapida": "x" * 41, "duracion_accion_h": 9}, "40 caracteres"),
        ({"duracion_accion_h": 9, "tiempo_absorcion_min": 20}, "2-8 h"),
    ],
)
def test_35_validar_perfil(cambios, fragmento):
    r = validar_perfil(**{**PERFIL_VALIDO, **cambios}, ahora=AHORA)
    if fragmento is None:
        assert r is None
    else:
        assert r is not None and fragmento in r.motivo


def test_validar_perfil_no_acepta_nombre_apellidos_ni_peso():
    """Regla 3 hecha firma: no hay manera de pasárselos por accidente."""
    for campo in ("nombre", "apellidos", "peso_kg"):
        with pytest.raises(TypeError):
            validar_perfil(**PERFIL_VALIDO, ahora=AHORA, **{campo: "x"})


# --- Cuándo se enseña cada cifra (paso 3, prueba 54) ------------------------
# Los límites exactos, no valores cómodos.


@pytest.mark.parametrize(("dias", "esperado"), [(2, False), (3, True), (4, True)])
def test_54_hay_suficientes_dias_desde_tres(dias, esperado):
    assert hay_suficientes_dias(dias) is esperado


@pytest.mark.parametrize(("dias", "esperado"), [(13, False), (14, True), (15, True)])
def test_54_gmi_es_fiable_desde_catorce(dias, esperado):
    assert gmi_es_fiable(dias) is esperado


def test_indicadores_no_cambia_de_firma_y_sigue_calculando_con_un_dia():
    """La puerta es aditiva: `indicadores` calcula igual que antes y no decide nada."""
    assert indicadores([100, 120]).n == 2
