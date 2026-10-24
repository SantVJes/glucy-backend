"""Pruebas 26 a 29: `POST /insulin`, y P-06 en los dos lotes nuevos.

Se valida que la dosis sea anotable, nunca que sea la correcta (regla 7).
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tablas import Comida, Cuarentena, DosisInsulina
from tests.conftest import cabeceras, contar
from tests.test_meals import comida

UNA_HORA_ANTES = (datetime.now(UTC) - timedelta(hours=1)).isoformat()


def dosis(**cambios) -> dict:
    """Un renglón válido; `cambios` pisa o agrega campos."""
    renglon = {
        "uuid": str(uuid4()),
        "ts_utc": UNA_HORA_ANTES,
        "zona_horaria": "America/Monterrey",
        "unidades": 6.5,
        "tipo": "bolo",
        "motivo": "comida",
    }
    renglon.update(cambios)
    return renglon


def subir(cliente: TestClient, items: list[dict]):
    return cliente.post("/insulin", json={"items": items}, headers=cabeceras())


def fila(sesion: Session, uuid: str) -> DosisInsulina:
    sesion.expire_all()
    return sesion.get(DosisInsulina, UUID(uuid))


# 26 --------------------------------------------------------------------------


def test_26_dos_dosis_validas_se_aceptan(cliente, sesion):
    items = [dosis(), dosis(tipo="basal", unidades=12, motivo="programada")]

    respuesta = subir(cliente, items)

    assert respuesta.status_code == 200
    assert respuesta.json()["aceptados"] == [i["uuid"] for i in items]
    assert contar(sesion, DosisInsulina) == 2
    assert contar(sesion, Cuarentena) == 0


def test_P05_en_dosis_el_mismo_lote_dos_veces_no_crea_filas(cliente, sesion):
    items = [dosis(), dosis()]
    subir(cliente, items)

    respuesta = subir(cliente, items)

    assert respuesta.json()["duplicados"] == [i["uuid"] for i in items]
    assert contar(sesion, DosisInsulina) == 2


# 27 --------------------------------------------------------------------------


def test_27_cero_rango_y_resolucion(cliente, sesion):
    cero, mucha, fina, media = (
        dosis(unidades=0),
        dosis(unidades=50.5),
        dosis(unidades=2.3),
        dosis(unidades=2.5),
    )

    cuerpo = subir(cliente, [cero, mucha, fina, media]).json()

    assert cuerpo["aceptados"] == [media["uuid"]]
    motivos = {c["uuid"]: c["motivo"] for c in cuerpo["cuarentena"]}
    assert "mayor que cero" in motivos[cero["uuid"]]
    assert "0-50 UI" in motivos[mucha["uuid"]]
    assert "resolución" in motivos[fina["uuid"]]
    assert contar(sesion, DosisInsulina) == 1


# 28 --------------------------------------------------------------------------


@pytest.mark.parametrize("tipo", ["rapida", "rápida (bolo)", "BOLO"])
def test_28_tipo_que_no_es_bolo_ni_basal_a_cuarentena(cliente, sesion, tipo):
    """C-4: «rápida» es una etiqueta de la interfaz del teléfono y no viaja."""
    otra = dosis(tipo=tipo)

    [renglon] = subir(cliente, [otra]).json()["cuarentena"]

    assert renglon["uuid"] == otra["uuid"]
    assert "tipo" in renglon["motivo"]


def test_28_sin_motivo_la_fila_queda_con_nulo(cliente, sesion):
    sin_motivo = dosis()
    del sin_motivo["motivo"]

    assert subir(cliente, [sin_motivo]).json()["aceptados"] == [sin_motivo["uuid"]]

    assert fila(sesion, sin_motivo["uuid"]).motivo is None


def test_ningun_campo_de_dosificacion_se_acepta(cliente, sesion):
    """Regla 7 y C-2: ni relación insulina/carbohidratos ni factor de sensibilidad."""
    for clave in ("ratio_insulina_carbohidratos", "factor_sensibilidad"):
        [renglon] = subir(cliente, [dosis(**{clave: 10})]).json()["cuarentena"]
        assert clave in renglon["motivo"]
    assert contar(sesion, DosisInsulina) == 0


# 29 --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ruta", "renglon", "tabla", "modelo"),
    [
        pytest.param("/meals", comida, "meals", Comida, id="meals"),
        pytest.param("/insulin", dosis, "insulin_doses", DosisInsulina, id="insulin"),
    ],
)
def test_29_P06_marca_de_tiempo_futura_a_cuarentena(cliente, sesion, ruta, renglon, tabla, modelo):
    futura = renglon(ts_utc=(datetime.now(UTC) + timedelta(hours=1)).isoformat())

    respuesta = cliente.post(ruta, json={"items": [futura]}, headers=cabeceras())

    assert respuesta.status_code == 200
    [en_cuarentena] = respuesta.json()["cuarentena"]
    assert en_cuarentena["uuid"] == futura["uuid"]
    assert "futura" in en_cuarentena["motivo"]
    sesion.expire_all()
    [guardada] = sesion.scalars(select(Cuarentena)).all()
    assert guardada.tabla_destino == tabla
    assert guardada.carga_original == futura
    assert contar(sesion, modelo) == 0
