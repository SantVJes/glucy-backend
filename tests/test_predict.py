"""`GET /predict`: el artefacto, el modo, la alerta derivada y los 200 ms (pruebas 100 a 116).

El modelo de estas pruebas es un **XGBoost de verdad**, entrenado aquí mismo sobre datos
sintéticos y guardado con su manifiesto, no un objeto de mentiras con un `predict` falso. Así
se prueba de verdad la carga del artefacto, el orden de las características, las contribuciones
TreeSHAP y la latencia; un modelo simulado no probaría ninguna de las cuatro.

El artefacto de la fase 3 entra exactamente igual: su manifiesto en la misma carpeta.
"""

import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
import xgboost
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tablas import Prediccion
from app.repositories import predicciones as repo_predicciones
from app.services.pipeline.caracteristicas import CARACTERISTICAS_DENSAS
from app.services.prediccion.artefacto import ArtefactoInvalido, cargar, cargar_uno
from tests.conftest import USUARIO, cabeceras, contar

# Una serie de sensor cada 5 min durante una hora, que es lo que el juego denso necesita.
PASOS = 13


def _entrenar(tmp_path: Path, version: str, horizonte: int, pendiente: float) -> Path:
    """Un modelo de juguete que aprende `mg_dl × pendiente`, con su manifiesto al lado."""
    generador = np.random.default_rng(7)
    filas = generador.uniform(60, 250, size=(400, len(CARACTERISTICAS_DENSAS)))
    objetivo = filas[:, 0] * pendiente
    booster = xgboost.train(
        {"max_depth": 3, "seed": 1, "base_score": 0.5},
        xgboost.DMatrix(filas, label=objetivo, feature_names=list(CARACTERISTICAS_DENSAS)),
        num_boost_round=12,
    )
    archivo = tmp_path / f"{version}.json"
    booster.save_model(str(archivo))
    manifiesto = tmp_path / f"{version}.manifiesto.json"
    manifiesto.write_text(
        json.dumps(
            {
                "version": version,
                "algoritmo": "xgboost",
                "horizonte_min": horizonte,
                "juego": "denso",
                "caracteristicas": list(CARACTERISTICAS_DENSAS),
                "archivo": archivo.name,
                "metricas": {"rmse": 18.2, "clarke_ab": 96.1},
            }
        )
    )
    return manifiesto


@pytest.fixture
def carpeta_artefactos(tmp_path: Path) -> Path:
    carpeta = tmp_path / "artefactos"
    carpeta.mkdir()
    _entrenar(carpeta, "m1-v0.1.0", 30, 0.9)
    _entrenar(carpeta, "m2-v0.1.0", 60, 0.8)
    return carpeta


@pytest.fixture
def con_modelo(cliente: TestClient, carpeta_artefactos: Path) -> Iterator[TestClient]:
    from app.main import app

    app.state.artefactos = cargar(str(carpeta_artefactos))
    assert len(app.state.artefactos) == 2
    yield cliente
    app.state.artefactos = {}


def _subir_serie(cliente: TestClient, ahora: datetime, origen: str = "sensor") -> None:
    """Una serie que sube, con la última lectura fresca."""
    items = [
        {
            "uuid": str(uuid4()),
            "ts_utc": (ahora - timedelta(minutes=5 * (PASOS - 1 - i))).isoformat(),
            "zona_horaria": "America/Monterrey",
            "mg_dl": 100 + 2 * i,
            "origen": origen,
        }
        for i in range(PASOS)
    ]
    respuesta = cliente.post("/readings", json={"items": items}, headers=cabeceras())
    assert respuesta.status_code == 200, respuesta.text


# ---------------------------------------------------------------------------
# El artefacto: la comprobación que evita el error más caro del proyecto.
# ---------------------------------------------------------------------------


def test_100_un_manifiesto_con_otras_caracteristicas_no_se_carga(tmp_path: Path):
    """Si el modelo espera otras columnas, no se carga: alimentarlo con las columnas cambiadas
    de lugar da números plausibles y equivocados, y nada falla."""
    manifiesto = _entrenar(tmp_path, "malo-v1", 30, 0.9)
    datos = json.loads(manifiesto.read_text())
    datos["caracteristicas"] = list(reversed(datos["caracteristicas"]))
    manifiesto.write_text(json.dumps(datos))

    with pytest.raises(ArtefactoInvalido, match="no son las del juego"):
        cargar_uno(manifiesto)


def test_101_un_manifiesto_incompleto_no_se_carga(tmp_path: Path):
    manifiesto = _entrenar(tmp_path, "sin-version", 30, 0.9)
    datos = json.loads(manifiesto.read_text())
    del datos["version"]
    manifiesto.write_text(json.dumps(datos))
    with pytest.raises(ArtefactoInvalido, match="falta"):
        cargar_uno(manifiesto)


def test_102_un_artefacto_malo_no_tira_los_demas(tmp_path: Path, carpeta_artefactos: Path):
    (carpeta_artefactos / "roto.manifiesto.json").write_text("{ esto no es json")
    assert len(cargar(str(carpeta_artefactos))) == 2


def test_103_sin_carpeta_no_hay_artefactos_y_no_truena(tmp_path: Path):
    assert cargar(None) == {}
    assert cargar("") == {}
    assert cargar(str(tmp_path / "no-existe")) == {}


def test_104_las_contribuciones_son_cinco_y_sin_el_termino_base(carpeta_artefactos: Path):
    artefacto = cargar(str(carpeta_artefactos))[("denso", 30)]
    fila = [120.0] + [110.0] * (len(CARACTERISTICAS_DENSAS) - 1)
    valor, contribuciones = artefacto.predecir(fila)
    assert valor > 0
    assert len(contribuciones) == 5
    assert all(nombre in CARACTERISTICAS_DENSAS for nombre, _ in contribuciones)
    # Ordenadas de mayor a menor en valor absoluto.
    aportes = [abs(aporte) for _, aporte in contribuciones]
    assert aportes == sorted(aportes, reverse=True)


# ---------------------------------------------------------------------------
# El endpoint.
# ---------------------------------------------------------------------------


def test_105_sin_modelo_cargado_es_503_y_no_un_numero_inventado(cliente: TestClient):
    from app.main import app

    app.state.artefactos = {}
    _subir_serie(cliente, datetime.now(UTC))
    respuesta = cliente.get("/predict", headers=cabeceras())
    assert respuesta.status_code == 503
    assert "modelo" in respuesta.json()["detail"]


def test_106_con_sensor_fresco_responde_los_dos_horizontes(con_modelo: TestClient):
    _subir_serie(con_modelo, datetime.now(UTC))
    cuerpo = con_modelo.get("/predict", headers=cabeceras()).json()

    assert cuerpo["modo"] == "sensor"
    assert cuerpo["puede_alertar_hipoglucemia"] is True
    assert [p["horizonte_min"] for p in cuerpo["predicciones"]] == [30, 60]
    assert cuerpo["predicciones"][0]["modelo_version"] == "m1-v0.1.0"
    assert cuerpo["predicciones"][1]["modelo_version"] == "m2-v0.1.0"
    assert len(cuerpo["predicciones"][0]["shap"]) == 5
    assert cuerpo["valor_actual"] == pytest.approx(100 + 2 * (PASOS - 1))


def test_107_p03_una_lectura_vieja_degrada_a_sin_sensor_y_lo_dice(con_modelo: TestClient):
    """Pasados los 15 minutos de frescura no se proyecta con datos viejos."""
    _subir_serie(con_modelo, datetime.now(UTC) - timedelta(minutes=40))
    cuerpo = con_modelo.get("/predict", headers=cabeceras()).json()

    assert cuerpo["modo"] == "sin_sensor"
    assert cuerpo["predicciones"] == []
    assert cuerpo["puede_alertar_hipoglucemia"] is False
    assert "no se puede anticipar" in cuerpo["aviso"]


def test_108_rf10b_lecturas_manuales_nunca_dan_modo_sensor(con_modelo: TestClient):
    """Una serie de pinchazos no es una serie continua, por fresca que sea."""
    _subir_serie(con_modelo, datetime.now(UTC), origen="manual")
    cuerpo = con_modelo.get("/predict", headers=cabeceras()).json()
    assert cuerpo["modo"] == "sin_sensor"
    assert cuerpo["puede_alertar_hipoglucemia"] is False
    assert cuerpo["aviso"]


def test_109_sin_ninguna_lectura_responde_sin_sensor(con_modelo: TestClient):
    cuerpo = con_modelo.get("/predict", headers=cabeceras()).json()
    assert cuerpo["modo"] == "sin_sensor"
    assert cuerpo["valor_actual"] is None
    assert cuerpo["antiguedad_min"] is None
    assert cuerpo["predicciones"] == []


def test_110_la_alerta_sale_del_umbral_del_perfil(con_modelo: TestClient):
    """El modelo predice un número; la alerta se deriva comparándolo con el umbral."""
    _subir_serie(con_modelo, datetime.now(UTC))
    sin_perfil = con_modelo.get("/predict", headers=cabeceras()).json()
    assert sin_perfil["umbral_hipo"] == 70

    # Con el umbral de hipoglucemia en 90, la misma predicción ya es una alerta.
    predicho = sin_perfil["predicciones"][0]["valor_predicho"]
    con_modelo.post(
        "/perfil",
        json={
            "tipo_usuario": "tipo1",
            "anio_nacimiento": 2000,
            "umbral_hipo": 90,
            "umbral_hiper": 180,
            "tipo_insulina_rapida": "lispro",
            "duracion_accion_insulina": 5,
        },
        headers=cabeceras(),
    )
    con_perfil = con_modelo.get("/predict", headers=cabeceras()).json()
    assert con_perfil["umbral_hipo"] == 90
    esperada = "hipoglucemia" if predicho < 90 else None
    assert con_perfil["predicciones"][0]["alerta"] == esperada


def test_111_rf25_cada_prediccion_queda_registrada_con_su_version(
    con_modelo: TestClient, sesion: Session
):
    _subir_serie(con_modelo, datetime.now(UTC))
    con_modelo.get("/predict", headers=cabeceras())

    sesion.expire_all()
    filas = sesion.scalars(select(Prediccion)).all()
    assert {f.horizonte_min for f in filas} == {30, 60}
    assert {f.modelo_version for f in filas} == {"m1-v0.1.0", "m2-v0.1.0"}
    assert all(f.modo == "sensor" for f in filas)
    assert all(f.usuario_uuid == USUARIO for f in filas)


def test_112_el_mismo_instante_dos_veces_no_acumula_filas(con_modelo: TestClient, sesion: Session):
    """La llave natural es (usuario, instante, horizonte, versión): una app que reintenta no
    pesa el cálculo del error hacia los instantes que se consultaron más veces.

    El endpoint usa el reloj del servidor, así que el instante repetido se prueba donde de
    verdad vive la regla: en el repositorio, que es quien lleva el `upsert`.
    """
    instante = datetime.now(UTC).replace(microsecond=0)
    _subir_serie(con_modelo, datetime.now(UTC))
    con_modelo.get("/predict", headers=cabeceras())
    assert contar(sesion, Prediccion) == 2

    filas = [
        {"horizonte_min": 30, "valor_predicho": 150.0, "modo": "sensor", "modelo_version": "m1"},
        {"horizonte_min": 60, "valor_predicho": 160.0, "modo": "sensor", "modelo_version": "m2"},
    ]
    repo_predicciones.registrar(sesion, USUARIO, instante, filas)
    assert contar(sesion, Prediccion) == 4
    repo_predicciones.registrar(sesion, USUARIO, instante, filas)
    assert contar(sesion, Prediccion) == 4, "el mismo instante creó filas nuevas"


def test_113_el_modo_sin_sensor_no_registra_ninguna_prediccion(
    con_modelo: TestClient, sesion: Session
):
    _subir_serie(con_modelo, datetime.now(UTC) - timedelta(hours=2))
    con_modelo.get("/predict", headers=cabeceras())
    assert contar(sesion, Prediccion) == 0


def test_114_cada_usuario_predice_con_sus_propias_lecturas(con_modelo: TestClient):
    otro = "22222222-2222-2222-2222-222222222222"
    _subir_serie(con_modelo, datetime.now(UTC))
    cuerpo = con_modelo.get("/predict", headers=cabeceras(otro)).json()
    assert cuerpo["modo"] == "sin_sensor"
    assert cuerpo["valor_actual"] is None


def test_115_sin_token_es_401(con_modelo: TestClient):
    assert con_modelo.get("/predict").status_code == 401


def test_116_rf21_responde_en_menos_de_200_ms(con_modelo: TestClient):
    """Con el artefacto ya en memoria. Se mide la mediana de cinco, no una sola llamada."""
    _subir_serie(con_modelo, datetime.now(UTC))
    con_modelo.get("/predict", headers=cabeceras())  # la primera calienta la base

    tiempos = []
    for _ in range(5):
        inicio = time.perf_counter()
        respuesta = con_modelo.get("/predict", headers=cabeceras())
        tiempos.append((time.perf_counter() - inicio) * 1000)
        assert respuesta.status_code == 200
    mediana = sorted(tiempos)[len(tiempos) // 2]
    assert mediana < 200, f"mediana {mediana:.0f} ms, tiempos {[round(t) for t in tiempos]}"
