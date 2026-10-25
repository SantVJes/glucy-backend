"""Pruebas 65 a 72: los dos juegos de características de RF-24 (decisiones 2.9 y 2.10).

Los nombres y el orden son un contrato con `glucy-ml`: si cambian, el modelo recibe las
columnas fuera de lugar y nada falla.
"""

import math
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.pipeline.caracteristicas import (
    CARACTERISTICAS_DENSAS,
    CARACTERISTICAS_DISPERSAS,
    CODIGOS_CONTEXTO,
    como_fila,
    vector_denso,
    vector_disperso,
)
from app.services.pipeline.limpieza import Punto
from referencia.reglas_clinicas import Origen, cob_total, iob

AHORA = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
MONTERREY = "America/Monterrey"


def punto(minutos_antes: float, mg_dl: float = 120, **extra) -> Punto:
    return Punto(
        AHORA - timedelta(minutes=minutos_antes),
        mg_dl,
        Origen.SENSOR,
        zona_horaria=extra.pop("zona_horaria", MONTERREY),
        **extra,
    )


def serie_completa(minutos: int = 60) -> list[Punto]:
    """Una lectura cada 5 minutos durante `minutos`, terminando en AHORA, subiendo 1 por min."""
    return [punto(m, 120 - m) for m in range(minutos, -1, -5)]


def comida(minutos_antes: float, carbs_g: float, absorcion: int = 180):
    return SimpleNamespace(
        ts_utc=AHORA - timedelta(minutes=minutos_antes),
        carbs_g=carbs_g,
        tiempo_absorcion_min=absorcion,
    )


def dosis(minutos_antes: float, unidades: float, tipo: str = "bolo"):
    return SimpleNamespace(
        ts_utc=AHORA - timedelta(minutes=minutos_antes), unidades=unidades, tipo=tipo
    )


# 65 --------------------------------------------------------------------------


def test_65_como_fila_respeta_el_orden_literal_del_contrato():
    """La tupla se escribe aquí a mano a propósito: si alguien reordena el módulo, esto falla."""
    literal = (
        "mg_dl", "rezago_5", "rezago_10", "rezago_15", "rezago_30", "rezago_60",
        "derivada_1", "derivada_2", "media_30", "media_60",
        "cob", "iob", "hora_sin", "hora_cos", "dia_semana",
    )  # fmt: skip
    assert CARACTERISTICAS_DENSAS == literal
    assert CARACTERISTICAS_DISPERSAS == (
        "mg_dl", "antiguedad_min", "carbs_g", "dosis_ui",
        "cob", "iob", "hora_sin", "hora_cos", "contexto_comida", "promedio_7d",
    )  # fmt: skip

    desordenado = {nombre: float(i) for i, nombre in reversed(list(enumerate(literal)))}

    assert como_fila(desordenado, CARACTERISTICAS_DENSAS) == [float(i) for i in range(15)]


def test_como_fila_no_acepta_un_vector_de_otro_juego():
    vector = vector_denso(AHORA, serie_completa(), [], [], None)

    with pytest.raises(ValueError):
        como_fila(vector, CARACTERISTICAS_DISPERSAS)
    with pytest.raises(ValueError):
        como_fila({**vector, "actividad": 1.0}, CARACTERISTICAS_DENSAS)


def test_el_vector_denso_sale_con_todos_sus_valores_cuando_hay_serie():
    vector = vector_denso(AHORA, serie_completa(), [], [], None)

    assert list(vector) == list(CARACTERISTICAS_DENSAS)
    assert vector["mg_dl"] == 120
    assert [vector[f"rezago_{m}"] for m in (5, 10, 15, 30, 60)] == [115, 110, 105, 90, 60]
    assert vector["derivada_1"] == 1  # sube 1 mg/dL por minuto
    assert vector["derivada_2"] == 0  # a ritmo constante
    assert vector["media_30"] == pytest.approx(sum(120 - m for m in range(0, 30, 5)) / 6)


# 66 --------------------------------------------------------------------------


def test_66_un_rezago_que_no_existe_es_nan_y_no_cero():
    corta = serie_completa(minutos=20)  # empieza hace 20 minutos

    vector = vector_denso(AHORA, corta, [], [], None)

    assert vector["rezago_15"] == 105
    assert math.isnan(vector["rezago_30"]) and math.isnan(vector["rezago_60"])
    sin_nada = vector_denso(AHORA, [], [], [], None)
    assert math.isnan(sin_nada["mg_dl"]) and math.isnan(sin_nada["derivada_1"])
    assert math.isnan(sin_nada["media_30"])


def test_una_atipica_no_cuenta_como_valor():
    serie = [*serie_completa()[:-1], punto(0, 400, atipica=True)]

    assert math.isnan(vector_denso(AHORA, serie, [], [], None)["mg_dl"])


# 67 --------------------------------------------------------------------------


def test_67_las_23_50_y_las_00_10_estan_cerca_en_la_hora_ciclica():
    dia = datetime(2026, 9, 1, tzinfo=UTC)
    antes = vector_denso(dia + timedelta(hours=23, minutes=50), [], [], [], None)
    despues = vector_denso(dia + timedelta(days=1, minutes=10), [], [], [], None)

    distancia = math.dist(
        (antes["hora_sin"], antes["hora_cos"]), (despues["hora_sin"], despues["hora_cos"])
    )

    assert distancia < 0.09
    assert abs((23 + 50 / 60) - (10 / 60)) == pytest.approx(23.67, abs=0.01)  # la hora cruda


# 68 --------------------------------------------------------------------------


def test_68_dia_semana_es_el_dia_local_y_no_el_utc():
    # Viernes 23 de octubre de 2026, 19:00 en Monterrey = sábado 24, 01:00 UTC.
    viernes_noche = datetime(2026, 10, 23, 19, 0, tzinfo=timezone(timedelta(hours=-6)))
    instante = viernes_noche.astimezone(UTC)
    serie = [Punto(instante, 110, Origen.SENSOR, zona_horaria=MONTERREY)]

    vector = vector_denso(instante, serie, [], [], None)

    assert instante.weekday() == 5  # sábado en UTC
    assert vector["dia_semana"] == 4  # viernes, lunes = 0
    assert vector["hora_sin"] == pytest.approx(math.sin(2 * math.pi * 19 * 60 / 1440))


# 69 --------------------------------------------------------------------------


def test_69_cob_es_el_de_la_referencia_y_p11_da_30():
    comidas = [comida(90, 60, 180)]  # P-11: 60 g, 180 min, a los 90 min

    vector = vector_denso(AHORA, serie_completa(), comidas, [], None)

    assert vector["cob"] == pytest.approx(30.0)
    varias = [comida(90, 60, 180), comida(20, 45, 30), comida(400, 80, 300), comida(-10, 50)]
    esperado = cob_total([(60, 90, 180), (45, 20, 30), (80, 400, 300)])  # la futura no cuenta
    assert vector_denso(AHORA, [], varias, [], None)["cob"] == pytest.approx(esperado)


# 70 --------------------------------------------------------------------------


def test_70_iob_ignora_la_basal_y_coincide_con_la_referencia():
    todas = [dosis(60, 4), dosis(120, 20, "basal"), dosis(30, 2)]
    perfil = SimpleNamespace(duracion_accion_insulina=4)

    vector = vector_denso(AHORA, [], [], todas, perfil)

    assert vector["iob"] == pytest.approx(iob([(4, 60), (2, 30)], dia_h=4))
    solo_basal = vector_denso(AHORA, [], [], [dosis(30, 20, "basal")], perfil)
    assert solo_basal["iob"] == 0


def test_sin_perfil_la_duracion_de_accion_es_la_de_omision():
    vector = vector_denso(AHORA, [], [], [dosis(60, 4)], None)

    assert vector["iob"] == pytest.approx(iob([(4, 60)]))


# 71 --------------------------------------------------------------------------


def test_71_sin_comida_registrada_carbs_es_nan_y_cob_es_cero():
    """La glucosa puede subir sin comida registrada; no se infiere ninguna (D-9, RF-37, P-12)."""
    sube = [punto(m, 100 + (60 - m) * 2) for m in range(60, -1, -5)]
    ultima = sube[-1]

    disperso = vector_disperso(AHORA, ultima, [], [], None, serie=sube)
    denso = vector_denso(AHORA, sube, [], [], None)

    assert math.isnan(disperso["carbs_g"]) and math.isnan(disperso["dosis_ui"])
    assert disperso["cob"] == 0 and denso["cob"] == 0


def test_el_vector_disperso_con_ultima_lectura_comida_y_dosis():
    ultima = punto(90, 140, contexto_comida="antes_de_comer")
    semana = [punto(60 * 24 * d, 100 + d) for d in range(1, 7)] + [ultima]

    vector = vector_disperso(
        AHORA, ultima, [comida(30, 50)], [dosis(25, 5), dosis(26, 10, "basal")], None, serie=semana
    )

    assert list(vector) == list(CARACTERISTICAS_DISPERSAS)
    assert vector["mg_dl"] == 140 and vector["antiguedad_min"] == 90
    assert vector["carbs_g"] == 50 and vector["dosis_ui"] == 5
    assert vector["contexto_comida"] == CODIGOS_CONTEXTO["antes_de_comer"]
    assert vector["promedio_7d"] == pytest.approx(sum([101, 102, 103, 104, 105, 106, 140]) / 7)


def test_sin_ninguna_lectura_el_disperso_es_nan_y_no_cero():
    vector = vector_disperso(AHORA, None, [], [], None, serie=[])

    for nombre in ("mg_dl", "antiguedad_min", "contexto_comida", "promedio_7d"):
        assert math.isnan(vector[nombre]), nombre


def test_sin_contexto_es_un_codigo_propio():
    assert CODIGOS_CONTEXTO[None] not in {
        codigo for clave, codigo in CODIGOS_CONTEXTO.items() if clave is not None
    }
    assert len(set(CODIGOS_CONTEXTO.values())) == len(CODIGOS_CONTEXTO)


# 72 --------------------------------------------------------------------------


def test_72_el_juego_denso_no_tiene_actividad_ni_sueno():
    """C-10 y C-11: ningún endpoint las sube, la app no las captura y las escalas no coinciden."""
    vector = vector_denso(AHORA, serie_completa(), [], [], None)

    for juego in (CARACTERISTICAS_DENSAS, CARACTERISTICAS_DISPERSAS, tuple(vector)):
        assert not {"actividad", "sueno", "sueño"} & set(juego)
