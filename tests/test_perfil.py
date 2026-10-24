"""Pruebas 30 a 34: `POST /perfil`, el octavo endpoint (C-7).

Lo interesante es lo que no acepta: un perfil que no pasa es `400` y además una fila en
`cuarentena`, filtrada para que nada que identifique a la persona quede en la base.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.tablas import Base, Cuarentena, Usuario
from tests.conftest import USUARIO, cabeceras, contar

SEIS = {
    "tipo_usuario": "tipo1",
    "anio_nacimiento": 2001,
    "umbral_hipo": 70,
    "umbral_hiper": 180,
    "tipo_insulina_rapida": "lispro",
    "duracion_accion_insulina": 5,
}


def perfil(**cambios) -> dict:
    return {**SEIS, **cambios}


def subir(cliente, cuerpo: dict):
    return cliente.post("/perfil", json=cuerpo, headers=cabeceras())


def el_usuario(sesion: Session) -> Usuario:
    sesion.expire_all()
    return sesion.get(Usuario, USUARIO)


# 30 --------------------------------------------------------------------------


def test_30_los_seis_campos_se_guardan_y_vuelven_como_quedaron(cliente, sesion):
    respuesta = subir(cliente, perfil())

    assert respuesta.status_code == 200
    usuario = el_usuario(sesion)
    guardado = {campo: getattr(usuario, campo) for campo in SEIS}
    assert respuesta.json() == guardado == SEIS
    assert contar(sesion, Cuarentena) == 0


# 31 --------------------------------------------------------------------------


def test_31_el_segundo_envio_actualiza_y_no_toca_ts_alta(cliente, sesion):
    subir(cliente, perfil())
    ts_alta = el_usuario(sesion).ts_alta

    nuevo = perfil(umbral_hipo=80, umbral_hiper=200, duracion_accion_insulina=4.5)
    respuesta = subir(cliente, nuevo)

    assert respuesta.status_code == 200
    assert respuesta.json() == nuevo
    assert contar(sesion, Usuario) == 1
    usuario = el_usuario(sesion)
    assert (usuario.umbral_hipo, usuario.umbral_hiper, usuario.duracion_accion_insulina) == (
        80,
        200,
        4.5,
    )
    assert usuario.ts_alta == ts_alta


def test_un_usuario_que_nacio_en_un_lote_conserva_su_ts_alta(cliente, sesion):
    """Decisión 2.7 del paso 1: el usuario puede existir antes de mandar su perfil."""
    lectura = {
        "uuid": "6f3a1b2c-0000-4000-8000-000000000001",
        "ts_utc": "2026-10-13T14:32:00Z",
        "zona_horaria": "America/Monterrey",
        "mg_dl": 112,
        "origen": "manual",
    }
    cliente.post("/readings", json={"items": [lectura]}, headers=cabeceras())
    ts_alta = el_usuario(sesion).ts_alta

    assert subir(cliente, perfil()).status_code == 200

    assert el_usuario(sesion).ts_alta == ts_alta
    assert contar(sesion, Usuario) == 1


# 32 --------------------------------------------------------------------------


def test_32_nombre_es_400_y_su_texto_no_queda_en_ninguna_parte(cliente, sesion, motor):
    texto = "Jesusito Pruebas"

    respuesta = subir(cliente, perfil(nombre=texto))

    assert respuesta.status_code == 400
    assert "nombre" in respuesta.json()["detail"]
    assert "regla 3" in respuesta.json()["detail"]
    sesion.expire_all()
    [fila] = sesion.scalars(select(Cuarentena)).all()
    assert fila.tabla_destino == "usuarios"
    assert fila.claves_descartadas == ["nombre"]
    assert fila.carga_original == SEIS
    # El texto en ninguna parte de la base: se revisan todas las tablas, columna por columna.
    with motor.connect() as conexion:
        for tabla in Base.metadata.sorted_tables:
            for renglon in conexion.execute(text(f"select * from {tabla.name}")):
                assert texto not in str(tuple(renglon)), tabla.name
    # Y no se guardó nada del perfil.
    assert el_usuario(sesion) is None


@pytest.mark.parametrize("clave", ["apellidos", "peso_kg", "nota"])
def test_apellidos_peso_y_nota_tambien_son_400(cliente, sesion, clave):
    respuesta = subir(cliente, perfil(**{clave: "x"}))

    assert respuesta.status_code == 400
    assert clave in respuesta.json()["detail"]
    sesion.expire_all()
    [fila] = sesion.scalars(select(Cuarentena)).all()
    assert fila.claves_descartadas == [clave]


# 33 --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cambios", "fragmento"),
    [
        pytest.param({"umbral_hipo": 40}, "50-90", id="hipo-40"),
        pytest.param({"umbral_hiper": 320}, "140-300", id="hiper-320"),
        pytest.param({"duracion_accion_insulina": 9}, "2-8 h", id="duracion-9h"),
        pytest.param(
            {"anio_nacimiento": datetime.now(UTC).year - 14}, "menor que 15", id="14-anios"
        ),
    ],
)
def test_33_fuera_de_rango_es_400_con_su_motivo(cliente, sesion, cambios, fragmento):
    respuesta = subir(cliente, perfil(**cambios))

    assert respuesta.status_code == 400
    assert fragmento in respuesta.json()["detail"]
    sesion.expire_all()
    [fila] = sesion.scalars(select(Cuarentena)).all()
    assert fila.tabla_destino == "usuarios"
    assert fragmento in fila.motivo_rechazo
    assert contar(sesion, Usuario) == 0


def test_un_campo_obligatorio_que_falta_es_400(cliente, sesion):
    sin_umbral = perfil()
    del sin_umbral["umbral_hipo"]

    respuesta = subir(cliente, sin_umbral)

    assert respuesta.status_code == 400
    assert "umbral_hipo" in respuesta.json()["detail"]
    assert contar(sesion, Cuarentena) == 1


# 34 --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tipo", ["tipo1", "tipo2_insulinodependiente", "prediabetes", "resistencia_insulina"]
)
def test_34_los_cuatro_tipo_usuario_se_aceptan(cliente, sesion, tipo):
    """C-3: son cuatro, no tres. Quien no se aplica insulina no manda tipo de insulina."""
    cuerpo = perfil(tipo_usuario=tipo, tipo_insulina_rapida=None)

    respuesta = subir(cliente, cuerpo)

    assert respuesta.status_code == 200
    assert respuesta.json()["tipo_usuario"] == tipo
    assert el_usuario(sesion).tipo_usuario == tipo


def test_sin_token_es_401(cliente, sesion):
    assert cliente.post("/perfil", json=perfil()).status_code == 401
    assert contar(sesion, Usuario) == 0
