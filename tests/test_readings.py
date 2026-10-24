"""Pruebas de `POST /readings`. Cada una apunta a su requisito o decisión del paso 1.

La afirmación que importa casi siempre es la cuenta de filas en la base, no solo la respuesta:
un servidor puede contestar bien y guardar mal.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tablas import Base, Cuarentena, LecturaGlucosa, Usuario
from tests.conftest import USUARIO, cabeceras, contar, token

UNA_HORA_ANTES = (datetime.now(UTC) - timedelta(hours=1)).isoformat()


def lectura(**cambios) -> dict:
    """Un renglón válido; `cambios` pisa o agrega campos."""
    renglon = {
        "uuid": str(uuid4()),
        "ts_utc": UNA_HORA_ANTES,
        "zona_horaria": "America/Monterrey",
        "mg_dl": 112,
        "origen": "foto_glucometro",
        "contexto_comida": "antes_de_comer",
    }
    renglon.update(cambios)
    return renglon


def subir(cliente: TestClient, items: list[dict], sub: UUID = USUARIO):
    return cliente.post("/readings", json={"items": items}, headers=cabeceras(sub))


def la_cuarentena(sesion: Session) -> list[Cuarentena]:
    sesion.expire_all()
    return list(sesion.scalars(select(Cuarentena)))


# 1 ---------------------------------------------------------------------------


def test_01_tres_lecturas_validas_se_aceptan(cliente, sesion):
    items = [lectura(), lectura(origen="manual"), lectura(origen="sensor", contexto_comida=None)]

    respuesta = subir(cliente, items)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["aceptados"] == [i["uuid"] for i in items]
    assert cuerpo["duplicados"] == [] and cuerpo["cuarentena"] == []
    assert contar(sesion, LecturaGlucosa) == 3
    assert contar(sesion, Cuarentena) == 0


# 2 ---------------------------------------------------------------------------


def test_02_P05_el_mismo_lote_dos_veces_no_crea_filas(cliente, sesion):
    """P-05 y RF-36c. La cuenta antes y después es la afirmación, no la respuesta."""
    items = [lectura(), lectura(), lectura()]
    assert subir(cliente, items).status_code == 200
    antes = contar(sesion, LecturaGlucosa)

    respuesta = subir(cliente, items)

    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "aceptados": [],
        "duplicados": [i["uuid"] for i in items],
        "cuarentena": [],
    }
    assert contar(sesion, LecturaGlucosa) == antes == 3


# 3 ---------------------------------------------------------------------------


def test_03_P06_marca_de_tiempo_futura_va_a_cuarentena(cliente, sesion):
    futura = lectura(ts_utc=(datetime.now(UTC) + timedelta(hours=1)).isoformat())

    respuesta = subir(cliente, [futura])

    assert respuesta.status_code == 200
    [renglon] = respuesta.json()["cuarentena"]
    assert renglon["uuid"] == futura["uuid"]
    assert "futura" in renglon["motivo"]
    [fila] = la_cuarentena(sesion)
    assert fila.tabla_destino == "glucose_readings"
    assert fila.carga_original == futura
    assert "futura" in fila.motivo_rechazo
    assert contar(sesion, LecturaGlucosa) == 0


# 4 ---------------------------------------------------------------------------


def test_04_P02_fuera_de_rango_a_cuarentena_y_600_exactos_se_aceptan(cliente, sesion):
    """El límite es inclusivo en la referencia; el servidor da el mismo número."""
    fuera = lectura(mg_dl=900)
    limite = lectura(mg_dl=600)

    cuerpo = subir(cliente, [fuera, limite]).json()

    assert cuerpo["aceptados"] == [limite["uuid"]]
    [renglon] = cuerpo["cuarentena"]
    assert renglon["uuid"] == fuera["uuid"]
    assert "20-600" in renglon["motivo"]


# 5 ---------------------------------------------------------------------------


def test_05_un_renglon_malo_no_tira_a_los_cuatro_buenos(cliente, sesion):
    """Decisión 2.5: el esquema es del sobre, las reglas son de cada renglón."""
    buenos = [lectura() for _ in range(4)]
    malo = lectura()
    del malo["mg_dl"]

    respuesta = subir(cliente, [buenos[0], buenos[1], malo, buenos[2], buenos[3]])

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["aceptados"] == [b["uuid"] for b in buenos]
    [renglon] = cuerpo["cuarentena"]
    assert renglon["uuid"] == malo["uuid"]
    assert "mg_dl" in renglon["motivo"]
    assert contar(sesion, LecturaGlucosa) == 4


# 6 ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cuerpo",
    [
        pytest.param({}, id="sin-items"),
        pytest.param({"items": []}, id="items-vacio"),
        pytest.param({"items": "no es una lista"}, id="items-no-es-lista"),
        pytest.param({"items": [lectura() for _ in range(501)]}, id="501-renglones"),
    ],
)
def test_06_sobre_roto_es_400_y_no_escribe_nada(cliente, sesion, cuerpo):
    respuesta = cliente.post("/readings", json=cuerpo, headers=cabeceras())

    assert respuesta.status_code == 400
    for tabla in Base.metadata.sorted_tables:
        assert contar(sesion, tabla) == 0, tabla.name


# 7 ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cabecera",
    [
        pytest.param({}, id="sin-token"),
        pytest.param(
            {"Authorization": f"Bearer {token(vence_en=timedelta(minutes=-1))}"}, id="vencido"
        ),
        pytest.param(
            {"Authorization": f"Bearer {token(secreto='otro-secreto-que-no-es-el-de-la-app')}"},
            id="otro-secreto",
        ),
        pytest.param({"Authorization": f"Bearer {token(sub='no-es-uuid')}"}, id="sub-no-uuid"),
    ],
)
def test_07_token_ausente_vencido_o_ajeno_es_401(cliente, sesion, cabecera):
    respuesta = cliente.post("/readings", json={"items": [lectura()]}, headers=cabecera)

    assert respuesta.status_code == 401
    assert contar(sesion, Usuario) == 0


# 8 ---------------------------------------------------------------------------


def test_08_marca_de_tiempo_sin_offset_va_a_cuarentena(cliente, sesion):
    """Decisión 2.10: suponer UTC desplazaría la serie seis horas sin que nada falle."""
    sin_offset = lectura(ts_utc="2026-10-13T14:32:00")

    [renglon] = subir(cliente, [sin_offset]).json()["cuarentena"]

    assert renglon["uuid"] == sin_offset["uuid"]
    assert "ts_utc" in renglon["motivo"] and "offset" in renglon["motivo"]


# 9 ---------------------------------------------------------------------------


def test_09_zona_horaria_que_no_existe_va_a_cuarentena(cliente, sesion):
    nowhere = lectura(zona_horaria="America/Nowhere")

    cuerpo = subir(cliente, [nowhere]).json()

    [renglon] = cuerpo["cuarentena"]
    assert renglon["uuid"] == nowhere["uuid"]
    assert "zona_horaria" in renglon["motivo"]
    assert contar(sesion, LecturaGlucosa) == 0


# 10 --------------------------------------------------------------------------


def test_10_usuario_uuid_ajeno_en_el_cuerpo_va_a_cuarentena(cliente, sesion):
    """Decisión 2.9: el mismo usuario que el token se ignora; otro, a cuarentena."""
    ajena = lectura(usuario_uuid=str(uuid4()))
    propia = lectura(usuario_uuid=str(USUARIO))

    cuerpo = subir(cliente, [ajena, propia]).json()

    assert cuerpo["aceptados"] == [propia["uuid"]]
    [renglon] = cuerpo["cuarentena"]
    assert renglon["uuid"] == ajena["uuid"]
    assert "usuario_uuid" in renglon["motivo"]
    [fila] = la_cuarentena(sesion)
    assert fila.carga_original["usuario_uuid"] == ajena["usuario_uuid"]


# 11 --------------------------------------------------------------------------


def test_11_una_nota_va_a_cuarentena_sin_guardar_su_texto(cliente, sesion):
    """Decisión 2.6: el nombre de la clave queda, el contenido no (regla 3)."""
    texto = "me sentí mareado después del desayuno"
    con_nota = lectura(nota=texto)

    [renglon] = subir(cliente, [con_nota]).json()["cuarentena"]

    assert renglon["uuid"] == con_nota["uuid"]
    assert "nota" in renglon["motivo"]
    [fila] = la_cuarentena(sesion)
    assert "nota" not in fila.carga_original
    assert texto not in str(fila.carga_original)
    assert fila.claves_descartadas == ["nota"]


# 12 --------------------------------------------------------------------------


def test_12_el_usuario_nace_solo_en_su_primer_lote(cliente, sesion):
    nuevo = uuid4()
    assert sesion.get(Usuario, nuevo) is None

    assert subir(cliente, [lectura()], sub=nuevo).status_code == 200

    sesion.expire_all()
    usuario = sesion.get(Usuario, nuevo)
    assert usuario is not None
    assert usuario.ts_alta is not None
    for columna in Usuario.__table__.columns:
        if columna.name not in {"uuid", "ts_alta"}:
            assert getattr(usuario, columna.name) is None, columna.name


# 13 --------------------------------------------------------------------------


def test_13_cada_renglon_sale_en_exactamente_una_lista(cliente, sesion):
    """«Nunca se descarta en silencio», escrito como prueba."""
    repetida = lectura()
    subir(cliente, [repetida])
    sin_uuid = lectura()
    del sin_uuid["uuid"]
    items = [
        lectura(),
        repetida,
        lectura(mg_dl=5),
        sin_uuid,
        lectura(origen="smartwatch"),
        lectura(),
        lectura(zona_horaria="Marte/Olympus"),
    ]

    cuerpo = subir(cliente, items).json()

    total = len(cuerpo["aceptados"]) + len(cuerpo["duplicados"]) + len(cuerpo["cuarentena"])
    assert total == len(items)
    vistos = cuerpo["aceptados"] + cuerpo["duplicados"] + [c["uuid"] for c in cuerpo["cuarentena"]]
    enviados = [i.get("uuid") for i in items]
    assert sorted(vistos, key=str) == sorted(enviados, key=str)
    assert cuerpo["duplicados"] == [repetida["uuid"]]
    assert len(cuerpo["aceptados"]) == 2 and len(cuerpo["cuarentena"]) == 4
    assert contar(sesion, Cuarentena) == 4
    assert contar(sesion, LecturaGlucosa) == 3


# Adicional -------------------------------------------------------------------


def test_sin_secreto_la_aplicacion_no_arranca(monkeypatch):
    """`jwt_secret` no tiene valor por omisión: un secreto por omisión acaba en producción."""
    from app.config import Ajustes

    monkeypatch.delenv("GLUCY_JWT_SECRET", raising=False)
    with pytest.raises(ValidationError):
        Ajustes(_env_file=None)
