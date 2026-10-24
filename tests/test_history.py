"""Pruebas 47 a 53: `GET /history`, la forma de sus renglones y el cursor (decisiones 2.5 a 2.8)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.schemas.comidas import ComidaEntrada
from app.schemas.dosis import DosisEntrada
from app.schemas.lecturas import LecturaEntrada
from tests.conftest import cabeceras

INICIO = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
DESDE, HASTA = "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"
PERIODO = {"desde": DESDE, "hasta": HASTA}


def lectura(ts: datetime, zona: str = "America/Monterrey") -> dict:
    return {
        "uuid": str(uuid4()),
        "ts_utc": ts.isoformat(),
        "zona_horaria": zona,
        "mg_dl": 112,
        "origen": "sensor",
        "contexto_comida": "antes_de_comer",
    }


def subir(cliente, ruta: str, items: list[dict]) -> None:
    cuerpo = cliente.post(ruta, json={"items": items}, headers=cabeceras()).json()
    assert len(cuerpo["aceptados"]) == len(items), cuerpo


def historial(cliente, **params):
    return cliente.get("/history", params={**PERIODO, **params}, headers=cabeceras())


def cinco_lecturas(cliente) -> list[str]:
    items = [lectura(INICIO + timedelta(hours=h)) for h in range(5)]
    subir(cliente, "/readings", items)
    return [i["uuid"] for i in items]


def paginar(cliente, **params) -> list[list[str]]:
    """Sigue `siguiente` hasta el final y devuelve los uuid de cada página."""
    paginas, cursor = [], None
    while True:
        extra = {"cursor": cursor} if cursor else {}
        cuerpo = historial(cliente, **params, **extra).json()
        paginas.append([r["uuid"] for r in cuerpo["lecturas"]])
        cursor = cuerpo["siguiente"]
        if cursor is None:
            return paginas


# 47 --------------------------------------------------------------------------


def test_47_las_tres_series_con_exactamente_las_columnas_de_su_tabla(cliente):
    subir(cliente, "/readings", [lectura(INICIO + timedelta(hours=h)) for h in range(3)])
    comidas = [
        {
            "uuid": str(uuid4()),
            "ts_utc": (INICIO + timedelta(hours=h)).isoformat(),
            "zona_horaria": "America/Monterrey",
            "carbs_g": 60,
            "origen": "barcode",
            "codigo_barras": "7501055300014",
        }
        for h in range(2)
    ]
    subir(cliente, "/meals", comidas)
    dosis = {
        "uuid": str(uuid4()),
        "ts_utc": INICIO.isoformat(),
        "zona_horaria": "America/Monterrey",
        "unidades": 6.5,
        "tipo": "bolo",
        "motivo": "comida",
    }
    subir(cliente, "/insulin", [dosis])

    cuerpo = historial(cliente).json()

    assert (len(cuerpo["lecturas"]), len(cuerpo["comidas"]), len(cuerpo["dosis"])) == (3, 2, 1)
    for serie, esquema in (
        ("lecturas", LecturaEntrada),
        ("comidas", ComidaEntrada),
        ("dosis", DosisEntrada),
    ):
        for renglon in cuerpo[serie]:
            assert set(renglon) == set(esquema.model_fields), serie
            assert "nota" not in renglon and "usuario_uuid" not in renglon
    assert cuerpo["comidas"][0]["tiempo_absorcion_min"] == 180
    assert cuerpo["dosis"][0]["unidades"] == 6.5
    assert cuerpo["siguiente"] is None


# 48 --------------------------------------------------------------------------


def test_48_que_lecturas_no_consulta_las_otras_tablas(cliente, motor):
    cinco_lecturas(cliente)
    sentencias: list[str] = []

    def anotar(_conexion, _cursor, sql, *_):
        sentencias.append(sql)

    event.listen(motor, "before_cursor_execute", anotar)
    try:
        cuerpo = historial(cliente, que="lecturas").json()
    finally:
        event.remove(motor, "before_cursor_execute", anotar)

    assert len(cuerpo["lecturas"]) == 5
    assert cuerpo["comidas"] == [] and cuerpo["dosis"] == []
    assert any("glucose_readings" in s for s in sentencias)
    assert not any("meals" in s or "insulin_doses" in s for s in sentencias)


# 49 --------------------------------------------------------------------------


def test_49_lo_que_cae_fuera_del_periodo_no_entra(cliente):
    antes = lectura(datetime(2026, 8, 31, 23, 59, tzinfo=UTC))
    justo = lectura(datetime(2026, 9, 1, 0, 0, tzinfo=UTC))
    en_hasta = lectura(datetime(2026, 10, 1, 0, 0, tzinfo=UTC))
    subir(cliente, "/readings", [antes, justo, en_hasta])

    uuids = [r["uuid"] for r in historial(cliente).json()["lecturas"]]

    # El periodo es semiabierto: `desde` entra, `hasta` no.
    assert uuids == [justo["uuid"]]


# 50 --------------------------------------------------------------------------


def test_50_el_cursor_da_cada_renglon_una_sola_vez_y_en_orden(cliente):
    originales = cinco_lecturas(cliente)

    paginas = paginar(cliente, limite=2)

    assert paginas == [originales[0:2], originales[2:4], originales[4:5]]


def test_un_limite_exacto_termina_con_siguiente_null(cliente):
    """La señal de fin es `siguiente: null`, no «vino menos de `limite`»."""
    originales = cinco_lecturas(cliente)

    assert paginar(cliente, limite=5) == [originales]


def test_dos_lecturas_con_la_misma_hora_se_desempatan_por_uuid(cliente):
    gemelas = [lectura(INICIO) for _ in range(4)]
    subir(cliente, "/readings", gemelas)

    vistas = [u for pagina in paginar(cliente, limite=1) for u in pagina]

    assert vistas == sorted((g["uuid"] for g in gemelas), key=lambda u: u.replace("-", ""))


def test_el_cursor_recorre_las_tres_series_mezcladas_en_orden(cliente):
    subir(cliente, "/readings", [lectura(INICIO), lectura(INICIO + timedelta(hours=2))])
    dosis = {
        "uuid": str(uuid4()),
        "ts_utc": (INICIO + timedelta(hours=1)).isoformat(),
        "zona_horaria": "America/Monterrey",
        "unidades": 2,
        "tipo": "bolo",
    }
    subir(cliente, "/insulin", [dosis])

    primera = historial(cliente, limite=2).json()
    segunda = historial(cliente, limite=2, cursor=primera["siguiente"]).json()

    assert (len(primera["lecturas"]), len(primera["dosis"])) == (1, 1)
    assert (len(segunda["lecturas"]), len(segunda["dosis"]), segunda["siguiente"]) == (1, 0, None)


# 51 --------------------------------------------------------------------------


def test_51_un_lote_nuevo_a_la_mitad_no_hace_saltar_nada(cliente):
    originales = cinco_lecturas(cliente)
    primera = historial(cliente, limite=2).json()

    # Llega a la mitad una lectura anterior al cursor. Con offset, la segunda página
    # repetiría la segunda lectura original; con cursor no se mueve nada.
    subir(cliente, "/readings", [lectura(INICIO - timedelta(minutes=30))])
    vistas = [r["uuid"] for r in primera["lecturas"]]
    cursor = primera["siguiente"]
    while cursor:
        cuerpo = historial(cliente, limite=2, cursor=cursor).json()
        vistas += [r["uuid"] for r in cuerpo["lecturas"]]
        cursor = cuerpo["siguiente"]

    assert vistas == originales


# 52 --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        pytest.param({"hasta": HASTA}, id="sin-desde"),
        pytest.param({"desde": DESDE}, id="sin-hasta"),
        pytest.param({"desde": HASTA, "hasta": DESDE}, id="desde-despues-de-hasta"),
        pytest.param({"desde": DESDE, "hasta": DESDE}, id="desde-igual-a-hasta"),
        pytest.param({"desde": DESDE, "hasta": "2026-12-01T00:00:00Z"}, id="91-dias"),
        pytest.param({**PERIODO, "limite": 1001}, id="limite-1001"),
        pytest.param({**PERIODO, "limite": 0}, id="limite-0"),
        pytest.param({"desde": "2026-09-01T00:00:00", "hasta": HASTA}, id="sin-offset"),
        pytest.param({**PERIODO, "que": "lecturas,fotos"}, id="serie-desconocida"),
        pytest.param({**PERIODO, "cursor": "no-es-un-cursor"}, id="cursor-ilegible"),
        pytest.param({**PERIODO, "offset": 10}, id="offset"),
    ],
)
def test_52_parametros_que_no_sirven_son_400(cliente, params):
    respuesta = cliente.get("/history", params=params, headers=cabeceras())

    assert respuesta.status_code == 400, respuesta.text


def test_90_dias_exactos_y_un_hasta_futuro_se_aceptan(cliente):
    noventa = {"desde": "2026-09-01T00:00:00Z", "hasta": "2026-11-30T00:00:00Z"}
    assert cliente.get("/history", params=noventa, headers=cabeceras()).status_code == 200
    assert cliente.get("/stats", params=noventa, headers=cabeceras()).status_code == 200


def test_sin_token_es_401(cliente):
    assert cliente.get("/history", params=PERIODO).status_code == 401
    assert cliente.get("/stats", params=PERIODO).status_code == 401


# 53 --------------------------------------------------------------------------


def test_53_las_fechas_salen_con_z_y_cada_renglon_con_su_zona(cliente):
    madrid = lectura(datetime(2026, 9, 2, 8, 0, tzinfo=UTC), zona="Europe/Madrid")
    monterrey = lectura(datetime(2026, 9, 2, 9, 0, tzinfo=UTC))
    subir(cliente, "/readings", [madrid, monterrey])

    [primera, segunda] = historial(cliente).json()["lecturas"]

    assert primera["ts_utc"] == "2026-09-02T08:00:00Z"
    leida = datetime.fromisoformat(primera["ts_utc"])
    assert leida.tzinfo is not None and leida == datetime(2026, 9, 2, 8, 0, tzinfo=UTC)
    assert (primera["zona_horaria"], segunda["zona_horaria"]) == (
        "Europe/Madrid",
        "America/Monterrey",
    )


def test_un_usuario_sin_datos_recibe_series_vacias_y_no_404(cliente):
    respuesta = cliente.get("/history", params=PERIODO, headers=cabeceras(uuid4()))

    assert respuesta.status_code == 200
    assert respuesta.json() == {"lecturas": [], "comidas": [], "dosis": [], "siguiente": None}
