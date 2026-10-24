"""Pruebas 37 a 39: nadie ve la serie de otra persona (decisión 2.1 del paso 3).

Son las que de verdad importan en este paso. Desde el primer `GET`, el peor error posible es
devolver los datos de alguien más, y son datos de salud. Estas pruebas son las únicas que
fallan si alguien «simplifica» el repositorio y quita el filtro por dueño.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from tests.conftest import USUARIO, cabeceras

OTRO = UUID("22222222-2222-2222-2222-222222222222")
INICIO = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
PERIODO = {"desde": "2026-09-01T00:00:00Z", "hasta": "2026-10-01T00:00:00Z"}


def subir_lecturas(cliente, sub: UUID, cuantas: int, *, mg_dl: float = 110) -> list[str]:
    """`cuantas` lecturas, una por día desde INICIO, con el token de `sub`."""
    items = [
        {
            "uuid": str(uuid4()),
            "ts_utc": (INICIO + timedelta(days=dia)).isoformat(),
            "zona_horaria": "America/Monterrey",
            "mg_dl": mg_dl,
            "origen": "manual",
        }
        for dia in range(cuantas)
    ]
    cuerpo = cliente.post("/readings", json={"items": items}, headers=cabeceras(sub)).json()
    assert len(cuerpo["aceptados"]) == cuantas
    return [i["uuid"] for i in items]


def subir_comida_y_dosis(cliente, sub: UUID) -> tuple[str, str]:
    comida = {
        "uuid": str(uuid4()),
        "ts_utc": INICIO.isoformat(),
        "zona_horaria": "America/Monterrey",
        "carbs_g": 45,
        "origen": "manual",
    }
    dosis = {
        "uuid": str(uuid4()),
        "ts_utc": INICIO.isoformat(),
        "zona_horaria": "America/Monterrey",
        "unidades": 4,
        "tipo": "bolo",
    }
    assert cliente.post("/meals", json={"items": [comida]}, headers=cabeceras(sub)).json()[
        "aceptados"
    ]
    assert cliente.post("/insulin", json={"items": [dosis]}, headers=cabeceras(sub)).json()[
        "aceptados"
    ]
    return comida["uuid"], dosis["uuid"]


# 37 --------------------------------------------------------------------------


def test_37_cada_usuario_ve_solo_su_historial(cliente):
    propias_a = subir_lecturas(cliente, USUARIO, 4)
    propias_b = subir_lecturas(cliente, OTRO, 3, mg_dl=150)
    comida_a, dosis_a = subir_comida_y_dosis(cliente, USUARIO)

    de_a = cliente.get("/history", params=PERIODO, headers=cabeceras(USUARIO)).json()
    de_b = cliente.get("/history", params=PERIODO, headers=cabeceras(OTRO)).json()

    assert [r["uuid"] for r in de_a["lecturas"]] == propias_a
    assert [r["uuid"] for r in de_b["lecturas"]] == propias_b
    assert [r["uuid"] for r in de_a["comidas"]] == [comida_a]
    assert [r["uuid"] for r in de_a["dosis"]] == [dosis_a]
    assert de_b["comidas"] == [] and de_b["dosis"] == []


# 38 --------------------------------------------------------------------------


def test_38_la_n_de_cada_usuario_es_la_suya_y_no_la_suma(cliente):
    subir_lecturas(cliente, USUARIO, 5, mg_dl=100)
    subir_lecturas(cliente, OTRO, 3, mg_dl=200)

    de_a = cliente.get("/stats", params=PERIODO, headers=cabeceras(USUARIO)).json()
    de_b = cliente.get("/stats", params=PERIODO, headers=cabeceras(OTRO)).json()

    assert (de_a["dias_con_lecturas"], de_a["indicadores"]["n"]) == (5, 5)
    assert (de_b["dias_con_lecturas"], de_b["indicadores"]["n"]) == (3, 3)
    assert de_a["indicadores"]["promedio"] == 100
    assert de_b["indicadores"]["promedio"] == 200


# 39 --------------------------------------------------------------------------


@pytest.mark.parametrize("ruta", ["/history", "/stats"])
@pytest.mark.parametrize("nombre", ["usuario_uuid", "usuario", "uuid", "sub"])
def test_39_un_usuario_en_la_consulta_es_400_y_nunca_la_serie_ajena(cliente, ruta, nombre):
    """El filtro sale del token y de ningún otro sitio: ni «solo para el panel»."""
    subir_lecturas(cliente, USUARIO, 4)

    respuesta = cliente.get(ruta, params={**PERIODO, nombre: str(USUARIO)}, headers=cabeceras(OTRO))

    assert respuesta.status_code == 400
    assert str(USUARIO) not in respuesta.text
    assert "lecturas" not in respuesta.json() and "indicadores" not in respuesta.json()
