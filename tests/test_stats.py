"""Pruebas 40 a 46: `GET /stats`, y cuándo una cifra significa algo (decisiones 2.2 a 2.4).

Un indicador bien calculado puede engañar: con dos días de lecturas un tiempo en rango
describe un día suelto, y un GMI sobre seis pinchazos sale igual de bonito y no significa nada.
"""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

from app.models.tablas import Base
from referencia.reglas_clinicas import (
    UMBRAL_HIPER_DEFECTO,
    UMBRAL_HIPO_DEFECTO,
    indicadores,
)
from tests.conftest import cabeceras, contar

INICIO = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
PERIODO = {"desde": "2026-09-01T00:00:00Z", "hasta": "2026-10-01T00:00:00Z"}
MONTERREY = timezone(timedelta(hours=-6))  # sin horario de verano desde 2022


def lectura(ts: datetime, mg_dl: float = 110, zona: str = "America/Monterrey") -> dict:
    return {
        "uuid": str(uuid4()),
        "ts_utc": ts.isoformat(),
        "zona_horaria": zona,
        "mg_dl": mg_dl,
        "origen": "manual",
    }


def subir(cliente, items: list[dict]) -> None:
    cuerpo = cliente.post("/readings", json={"items": items}, headers=cabeceras()).json()
    assert len(cuerpo["aceptados"]) == len(items), cuerpo


def en_dias(dias: int, valores: list[float]) -> list[dict]:
    """Los `valores`, repartidos uno por renglón y en `dias` días distintos."""
    return [
        lectura(INICIO + timedelta(days=i % dias, minutes=i), mg_dl=valor)
        for i, valor in enumerate(valores)
    ]


def stats(cliente) -> dict:
    respuesta = cliente.get("/stats", params=PERIODO, headers=cabeceras())
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


# 40 --------------------------------------------------------------------------


def test_40_con_dos_dias_no_hay_indicadores(cliente):
    subir(cliente, en_dias(2, [100, 120, 140, 160, 180, 90]))

    cuerpo = stats(cliente)

    assert cuerpo["dias_con_lecturas"] == 2
    assert cuerpo["indicadores"] is None


# 41 --------------------------------------------------------------------------


def test_41_con_tres_dias_hay_indicadores_pero_no_gmi(cliente):
    subir(cliente, en_dias(3, [100, 120, 140]))

    cuerpo = stats(cliente)

    assert cuerpo["dias_con_lecturas"] == 3
    assert cuerpo["indicadores"] is not None
    assert cuerpo["indicadores"]["n"] == 3
    assert cuerpo["indicadores"]["promedio"] == 120
    assert cuerpo["indicadores"]["gmi"] is None


# 42 --------------------------------------------------------------------------


def test_42_con_catorce_dias_hay_gmi(cliente):
    subir(cliente, en_dias(14, [100 + 5 * i for i in range(14)]))

    cuerpo = stats(cliente)["indicadores"]

    assert cuerpo["gmi"] == 3.31 + 0.02392 * cuerpo["promedio"]


def test_trece_dias_todavia_no_dan_gmi(cliente):
    subir(cliente, en_dias(13, [110] * 13))

    assert stats(cliente)["indicadores"]["gmi"] is None


# 43 --------------------------------------------------------------------------


def test_43_los_indicadores_son_los_de_la_referencia_campo_por_campo(cliente):
    valores = [55, 68, 70, 95, 130, 180, 181, 215, 260, 72, 101, 149, 66, 190, 88]
    subir(cliente, en_dias(15, valores))

    cuerpo = stats(cliente)["indicadores"]

    esperado = asdict(indicadores(valores, UMBRAL_HIPO_DEFECTO, UMBRAL_HIPER_DEFECTO))
    assert set(cuerpo) == set(esperado)
    for campo, valor in esperado.items():
        assert cuerpo[campo] == valor, campo


# 44 --------------------------------------------------------------------------


def test_44_los_dias_se_cuentan_por_dia_local_y_no_por_utc(cliente):
    """Las 10:00, 19:00 y 20:00 de Monterrey del 10 de septiembre son un solo día local.

    En UTC son las 16:00 del 10 y la 01:00 y las 02:00 del 11: dos días. Si alguien agrupa por
    UTC, esta prueba da 2.
    """
    dia = datetime(2026, 9, 10, tzinfo=MONTERREY)
    subir(cliente, [lectura(dia.replace(hour=h)) for h in (10, 19, 20)])

    assert stats(cliente)["dias_con_lecturas"] == 1


def test_cada_lectura_cuenta_con_su_propia_zona(cliente):
    """La misma hora UTC puede ser dos días locales si las zonas son distintas."""
    instante = datetime(2026, 9, 11, 2, 0, tzinfo=UTC)  # 10 sep en Monterrey, 11 en Madrid
    subir(
        cliente, [lectura(instante), lectura(instante + timedelta(seconds=1), zona="Europe/Madrid")]
    )

    assert stats(cliente)["dias_con_lecturas"] == 2


# 45 --------------------------------------------------------------------------


def test_45_sin_perfil_umbrales_de_omision_y_con_perfil_cambia_el_tbr(cliente):
    subir(cliente, en_dias(3, [75, 120, 140]))

    sin_perfil = stats(cliente)
    assert sin_perfil["umbrales_del_perfil"] is False
    assert (sin_perfil["umbral_hipo"], sin_perfil["umbral_hiper"]) == (70, 180)
    assert sin_perfil["indicadores"]["tbr"] == 0

    perfil = {
        "tipo_usuario": "tipo1",
        "anio_nacimiento": 2001,
        "umbral_hipo": 80,
        "umbral_hiper": 180,
        "duracion_accion_insulina": 5,
    }
    assert cliente.post("/perfil", json=perfil, headers=cabeceras()).status_code == 200

    con_perfil = stats(cliente)
    assert con_perfil["umbrales_del_perfil"] is True
    assert con_perfil["umbral_hipo"] == 80
    assert con_perfil["indicadores"]["tbr"] == 100 / 3  # el 75 ya está por debajo de 80
    assert con_perfil["indicadores"]["tir"] == sin_perfil["indicadores"]["tir"]  # fijo


# 46 --------------------------------------------------------------------------


def test_46_sin_lecturas_es_200_con_cero_dias_y_sin_indicadores(cliente, sesion):
    respuesta = cliente.get("/stats", params=PERIODO, headers=cabeceras(uuid4()))

    assert respuesta.status_code == 200
    assert respuesta.json()["dias_con_lecturas"] == 0
    assert respuesta.json()["indicadores"] is None
    # Un GET no escribe nada: ni crea el usuario (decisión 2.9).
    for tabla in Base.metadata.sorted_tables:
        assert contar(sesion, tabla) == 0, tabla.name


def test_fuera_del_periodo_no_cuenta(cliente):
    subir(cliente, en_dias(3, [100, 120, 140]))
    subir(cliente, [lectura(datetime(2026, 8, 31, 23, 59, tzinfo=UTC), mg_dl=400)])

    assert stats(cliente)["indicadores"]["n"] == 3
