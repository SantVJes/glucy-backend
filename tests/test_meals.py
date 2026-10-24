"""Pruebas 18 a 25: `POST /meals`. Cada una apunta a su requisito o decisión del paso 2.

Como en el paso 1, la afirmación que importa casi siempre es la cuenta de filas en la base.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tablas import Comida, Cuarentena
from tests.conftest import cabeceras, contar

UNA_HORA_ANTES = (datetime.now(UTC) - timedelta(hours=1)).isoformat()


def comida(**cambios) -> dict:
    """Un renglón válido; `cambios` pisa o agrega campos."""
    renglon = {
        "uuid": str(uuid4()),
        "ts_utc": UNA_HORA_ANTES,
        "zona_horaria": "America/Monterrey",
        "carbs_g": 60,
        "tiempo_absorcion_min": 180,
        "porciones": 1,
        "codigo_barras": "7501055300014",
        "origen": "barcode",
    }
    renglon.update(cambios)
    return renglon


def subir(cliente: TestClient, items: list[dict]):
    return cliente.post("/meals", json={"items": items}, headers=cabeceras())


def la_cuarentena(sesion: Session) -> list[Cuarentena]:
    sesion.expire_all()
    return list(sesion.scalars(select(Cuarentena)))


def fila(sesion: Session, uuid: str) -> Comida:
    sesion.expire_all()
    return sesion.get(Comida, UUID(uuid))


# 18 --------------------------------------------------------------------------


def test_18_tres_comidas_validas_se_aceptan(cliente, sesion):
    items = [comida(), comida(origen="manual", codigo_barras=None), comida(origen="ocr_etiqueta")]

    respuesta = subir(cliente, items)

    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "aceptados": [i["uuid"] for i in items],
        "duplicados": [],
        "cuarentena": [],
    }
    assert contar(sesion, Comida) == 3
    assert contar(sesion, Cuarentena) == 0


# 19 --------------------------------------------------------------------------


def test_19_P05_el_mismo_lote_dos_veces_no_crea_filas(cliente, sesion):
    items = [comida(), comida()]
    assert subir(cliente, items).status_code == 200
    antes = contar(sesion, Comida)

    respuesta = subir(cliente, items)

    assert respuesta.status_code == 200
    assert respuesta.json()["duplicados"] == [i["uuid"] for i in items]
    assert respuesta.json()["aceptados"] == []
    assert contar(sesion, Comida) == antes == 2


# 20 --------------------------------------------------------------------------


def test_20_301_gramos_a_cuarentena_y_300_exactos_se_aceptan(cliente, sesion):
    fuera, limite = comida(carbs_g=301), comida(carbs_g=300)

    cuerpo = subir(cliente, [fuera, limite]).json()

    assert cuerpo["aceptados"] == [limite["uuid"]]
    [renglon] = cuerpo["cuarentena"]
    assert renglon["uuid"] == fuera["uuid"]
    assert "0-300 g" in renglon["motivo"]
    [guardada] = la_cuarentena(sesion)
    assert guardada.tabla_destino == "meals"


# 21 --------------------------------------------------------------------------


def test_21_absorcion_fuera_de_30_300_a_cuarentena_y_los_extremos_se_aceptan(cliente, sesion):
    cortas, larga = comida(tiempo_absorcion_min=20), comida(tiempo_absorcion_min=400)
    rapida, lenta = comida(tiempo_absorcion_min=30), comida(tiempo_absorcion_min=300)

    cuerpo = subir(cliente, [cortas, larga, rapida, lenta]).json()

    assert cuerpo["aceptados"] == [rapida["uuid"], lenta["uuid"]]
    assert [c["uuid"] for c in cuerpo["cuarentena"]] == [cortas["uuid"], larga["uuid"]]
    assert all("30-300 min" in c["motivo"] for c in cuerpo["cuarentena"])


# 22 --------------------------------------------------------------------------


def test_22_porciones_en_cero_a_cuarentena(cliente, sesion):
    cero = comida(porciones=0)

    [renglon] = subir(cliente, [cero]).json()["cuarentena"]

    assert renglon["uuid"] == cero["uuid"]
    assert "porciones" in renglon["motivo"]
    assert contar(sesion, Comida) == 0


# 23 --------------------------------------------------------------------------


def test_23_sin_absorcion_la_fila_queda_con_180(cliente, sesion):
    sin_absorcion = comida()
    del sin_absorcion["tiempo_absorcion_min"]

    assert subir(cliente, [sin_absorcion]).json()["aceptados"] == [sin_absorcion["uuid"]]

    assert fila(sesion, sin_absorcion["uuid"]).tiempo_absorcion_min == 180


def test_carbs_g_se_guarda_tal_cual_sin_multiplicar_por_las_porciones(cliente, sesion):
    """Decisión 2.5: `carbs_g` ya es el total. Multiplicar otra vez duplicaría el COB."""
    doble = comida(carbs_g=90, porciones=2)

    subir(cliente, [doble])

    guardada = fila(sesion, doble["uuid"])
    assert (guardada.carbs_g, guardada.porciones) == (90, 2)


# 24 --------------------------------------------------------------------------


@pytest.mark.parametrize("clave", ["descripcion", "nota"])
def test_24_descripcion_o_nota_a_cuarentena_sin_guardar_el_texto(cliente, sesion, clave):
    texto = "tacos de la esquina con mi hermana"
    con_texto = comida(**{clave: texto})

    [renglon] = subir(cliente, [con_texto]).json()["cuarentena"]

    assert renglon["uuid"] == con_texto["uuid"]
    assert clave in renglon["motivo"]
    [guardada] = la_cuarentena(sesion)
    assert clave not in guardada.carga_original
    assert texto not in str(guardada.carga_original)
    assert guardada.claves_descartadas == [clave]
    assert contar(sesion, Comida) == 0


# 25 --------------------------------------------------------------------------


def test_25_proteina_grasa_y_fibra_ausentes_quedan_nulas(cliente, sesion):
    sin_macros = comida()

    subir(cliente, [sin_macros])

    guardada = fila(sesion, sin_macros["uuid"])
    assert (guardada.proteina_g, guardada.grasa_g, guardada.fibra_g) == (None, None, None)
