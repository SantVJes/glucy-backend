"""`GET /predict`: el artefacto, el modo, la alerta derivada y los 200 ms (pruebas 100 a 116).

El modelo de estas pruebas es un **XGBoost de verdad**, entrenado aquí mismo sobre datos
sintéticos y guardado con su manifiesto, no un objeto de mentiras con un `predict` falso. Así
se prueba de verdad la carga del artefacto, el orden de las características, las contribuciones
TreeSHAP y la latencia; un modelo simulado no probaría ninguna de las cuatro.

El artefacto de la fase 3 entra exactamente igual: su manifiesto en la misma carpeta.
"""

import json
import logging
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


# ---------------------------------------------------------------------------
# El contrato con glucy-ml: cargar el manifiesto que ese repositorio produce **de verdad**.
#
# La primera versión de este cargador no cargaba ninguno. Buscaba `*.manifiesto.json`, exigía
# un campo `archivo`, esperaba la versión completa en un solo campo y convertía toda métrica
# con `float()`; `glucy-ml` escribe `m1-v0.1.0.json` junto a `m1-v0.1.0.ubj`, con `modelo` y
# `version` aparte y con un diccionario y un nulo entre las métricas. El resultado era que
# `/predict` iba a contestar 503 para siempre **sin un solo renglón de registro que lo
# explicara**, porque un glob que no encuentra nada no es un error.
#
# Estas pruebas copian la forma real del manifiesto, no la que se suponía.
# ---------------------------------------------------------------------------


def _artefacto_como_lo_deja_glucy_ml(carpeta: Path, modelo: str, version: str, horizonte: int):
    """Un artefacto con la forma exacta que produce `src/train/artefacto.py` de glucy-ml."""
    generador = np.random.default_rng(3)
    filas = generador.uniform(60, 250, size=(300, len(CARACTERISTICAS_DENSAS)))
    booster = xgboost.train(
        {"max_depth": 3, "seed": 1, "base_score": 0.5},
        xgboost.DMatrix(
            filas, label=filas[:, 0] * 0.95, feature_names=list(CARACTERISTICAS_DENSAS)
        ),
        num_boost_round=8,
    )
    base = carpeta / f"{modelo}-{version}"
    # `.ubj`, el formato binario de XGBoost, que es el que guarda glucy-ml. Y **sin** campo
    # `archivo` en el manifiesto: el nombre se deduce del suyo.
    booster.save_model(f"{base}.ubj")
    manifiesto = Path(f"{base}.json")
    manifiesto.write_text(
        json.dumps(
            {
                "modelo": modelo,
                "version": version,
                "algoritmo": "xgboost",
                "horizonte_min": horizonte,
                "juego": "denso",
                "caracteristicas": list(CARACTERISTICAS_DENSAS),
                "semilla": 42,
                "hiperparametros": {"max_depth": 3},
                "origen_datos": "ohiot1dm",
                "n_entrenamiento": 300,
                "n_prueba": 100,
                "sujetos_entrenamiento": ["559", "563"],
                "sujetos_prueba": [],
                "metricas": {
                    "n": 100,
                    "horizonte_min": horizonte,
                    "rmse": 18.2,
                    "mae": 13.1,
                    "mard": 9.4,
                    "clarke_ab": 96.1,
                    # Un diccionario, que con `float()` reventaba.
                    "clarke_reparto": {"A": 82.0, "B": 14.1},
                    # Y un nulo, que **tiene que poder serlo**: glucy-ml lo deja nulo cuando el
                    # conjunto no traía hipoglucemias reales, en lugar de reportar un 100 %.
                    "sensibilidad_hipo": None,
                    "falsas_alarmas": 11.0,
                },
                "protocolo": "LOSO sobre doce sujetos",
                "version_del_manifiesto": 1,
            }
        )
    )
    return manifiesto


def test_105_se_carga_el_manifiesto_que_glucy_ml_produce_de_verdad(tmp_path: Path):
    manifiesto = _artefacto_como_lo_deja_glucy_ml(tmp_path, "m1", "v0.1.0", 30)

    artefacto = cargar_uno(manifiesto)

    # La versión se compone de `modelo` y `version`, que es lo que se registra en
    # `predictions.modelo_version` (RF-25).
    assert artefacto.version == "m1-v0.1.0"
    assert artefacto.horizonte_min == 30
    assert artefacto.caracteristicas == CARACTERISTICAS_DENSAS
    # Las métricas numéricas sí; el diccionario y el nulo, fuera, sin reventar.
    assert artefacto.metricas["rmse"] == pytest.approx(18.2)
    assert artefacto.metricas["clarke_ab"] == pytest.approx(96.1)
    assert "clarke_reparto" not in artefacto.metricas
    assert "sensibilidad_hipo" not in artefacto.metricas


def test_106_la_carpeta_de_glucy_ml_se_encuentra_entre_otros_json(tmp_path: Path):
    """Junto al manifiesto viven el modelo en texto y el informe de la conversión a Core ML."""
    _artefacto_como_lo_deja_glucy_ml(tmp_path, "m1", "v0.1.0", 30)
    _artefacto_como_lo_deja_glucy_ml(tmp_path, "m2", "v0.1.0", 60)
    # Lo que de verdad comparte esa carpeta y no es un manifiesto.
    (tmp_path / "m1-v0.1.0-coreml.json").write_text(json.dumps({"la_traduccion_es_fiel": True}))
    (tmp_path / "notas.json").write_text(json.dumps([1, 2, 3]))

    cargados = cargar(str(tmp_path))

    assert sorted(cargados) == [("denso", 30), ("denso", 60)]
    assert cargados[("denso", 30)].version == "m1-v0.1.0"
    assert cargados[("denso", 60)].version == "m2-v0.1.0"


def test_107_un_manifiesto_sin_el_modelo_al_lado_lo_dice_claro(tmp_path: Path):
    manifiesto = _artefacto_como_lo_deja_glucy_ml(tmp_path, "m1", "v0.1.0", 30)
    (tmp_path / "m1-v0.1.0.ubj").unlink()

    with pytest.raises(ArtefactoInvalido, match="no está el archivo del modelo"):
        cargar_uno(manifiesto)


def test_108_un_manifiesto_escrito_a_mano_sigue_cargando(tmp_path: Path):
    """La forma vieja no se rompe: `archivo` manda si viene, y la versión puede ir completa."""
    manifiesto = _entrenar(tmp_path, "m1-v0.2.0", 30, 0.9)

    artefacto = cargar_uno(manifiesto)

    assert artefacto.version == "m1-v0.2.0"
    assert artefacto.metricas["rmse"] == pytest.approx(18.2)


def test_109_la_version_no_se_duplica_si_ya_trae_el_modelo_adelante(tmp_path: Path):
    manifiesto = _artefacto_como_lo_deja_glucy_ml(tmp_path, "m1", "m1-v0.3.0", 30)
    assert cargar_uno(manifiesto).version == "m1-v0.3.0"


def test_110_un_json_que_no_es_manifiesto_no_estorba_ni_se_reporta_como_error(
    tmp_path: Path, caplog
):
    (tmp_path / "cualquiera.json").write_text(json.dumps({"hola": "mundo"}))

    with caplog.at_level(logging.ERROR):
        assert cargar(str(tmp_path)) == {}

    assert caplog.records == []


def test_111_un_manifiesto_corrupto_que_se_declara_como_tal_si_se_reporta(tmp_path: Path, caplog):
    """Quien nombró el archivo `.manifiesto.json` dijo lo que era: saltárselo en silencio
    esconde el problema.

    Esta prueba fija además algo que no se ve: `migrations/env.py` tiene que llamar a
    `fileConfig` con `disable_existing_loggers=False`. Sin eso, correr una migración dentro del
    proceso apaga los registradores de `app.*` y este registro de error desaparece.
    """
    (tmp_path / "roto.manifiesto.json").write_text("{ esto no es json")

    with caplog.at_level(logging.ERROR):
        assert cargar(str(tmp_path)) == {}

    assert any("descartado" in r.message for r in caplog.records)


def test_112_un_modelo_entrenado_con_datos_de_juguete_lo_avisa_al_arrancar(tmp_path: Path, caplog):
    """Un artefacto sintético se carga, pero no se calla.

    `glucy-ml` marca el origen (`ohiot1dm`, `simulador`, `sintetico`) porque una métrica que no
    se puede reportar tiene que decirlo en el archivo. El servidor lo repite en el arranque: sin
    este aviso, un modelo entrenado con senos se sirve igual que uno de verdad y lo único que
    cambia es que los números del documento final serían mentira.
    """
    manifiesto = _artefacto_como_lo_deja_glucy_ml(tmp_path, "m1", "v0.0.2-pruebas", 30)
    datos = json.loads(manifiesto.read_text())
    datos["origen_datos"] = "sintetico"
    manifiesto.write_text(json.dumps(datos))

    with caplog.at_level(logging.WARNING):
        cargados = cargar(str(tmp_path))

    assert cargados[("denso", 30)].origen_datos == "sintetico"
    assert any("NO van al documento final" in r.getMessage() for r in caplog.records)


def test_113_un_artefacto_de_ohiot1dm_no_avisa_nada(tmp_path: Path, caplog):
    _artefacto_como_lo_deja_glucy_ml(tmp_path, "m1", "v0.1.0", 30)

    with caplog.at_level(logging.WARNING):
        assert cargar(str(tmp_path))[("denso", 30)].origen_datos == "ohiot1dm"

    assert caplog.records == []


# ---------------------------------------------------------------------------
# Los factores, que son lo que dibuja la pantalla de la app.
# ---------------------------------------------------------------------------


def test_120_la_respuesta_trae_los_factores_con_nombre_en_palabras(con_modelo: TestClient):
    """La regla del proyecto es que en la superficie no hay tecnicismos.

    `shap` sigue crudo porque es el contrato con el pipeline y con glucy-ml, y `/explain` lo
    necesita así. Lo que la pantalla dibuja es `factores`, y ahí `rezago_30` no puede aparecer.
    """
    from app.services.pipeline.caracteristicas import CARACTERISTICAS_DENSAS

    _subir_serie(con_modelo, datetime.now(UTC))
    prediccion = con_modelo.get("/predict", headers=cabeceras()).json()["predicciones"][0]

    assert prediccion["factores"], "la respuesta llegó sin factores"
    # El modelo de juguete del fixture pone `mg_dl` arriba de todo, así que la frase se puede
    # fijar: si cambiara el diccionario de nombres, esta prueba lo dice.
    assert prediccion["factores"][0]["nombre"] == "tu glucosa de ahora"
    for factor in prediccion["factores"]:
        assert factor["nombre"] not in CARACTERISTICAS_DENSAS, factor
        assert "_" not in factor["nombre"], factor
        assert isinstance(factor["mg_dl"], float | int)


def test_121_son_cinco_como_mucho_y_van_de_mayor_a_menor(con_modelo: TestClient):
    """Cinco es lo que el reporte promete y lo que cabe en una pantalla. El orden importa: la
    app enseña las primeras, así que si no fueran las que más pesan enseñaría otra cosa."""
    _subir_serie(con_modelo, datetime.now(UTC))
    factores = con_modelo.get("/predict", headers=cabeceras()).json()["predicciones"][0]["factores"]

    assert 0 < len(factores) <= 5
    pesos = [abs(f["mg_dl"]) for f in factores]
    assert pesos == sorted(pesos, reverse=True)


def test_122_la_hora_del_dia_no_sale_dos_veces(con_modelo: TestClient):
    """`hora_sin` y `hora_cos` son una sola idea para quien lee y dos columnas para el modelo.
    SHAP es aditivo, así que se suman. Sin esto «la hora del día» aparecía dos veces con dos
    cifras distintas, que es lo que hace que una explicación deje de creerse."""
    _subir_serie(con_modelo, datetime.now(UTC))
    factores = con_modelo.get("/predict", headers=cabeceras()).json()["predicciones"][0]["factores"]

    prediccion = con_modelo.get("/predict", headers=cabeceras()).json()["predicciones"][0]
    crudas = {c["variable"] for c in prediccion["shap"]}
    nombres = [f["nombre"] for f in factores]

    assert len(nombres) == len(set(nombres)), nombres
    assert {"hora_sin", "hora_cos"} <= crudas, "el fixture dejó de ejercitar la suma"
    assert len(factores) < len(prediccion["shap"]), "las dos mitades de la hora no se sumaron"
    assert "la hora del día" in nombres


def test_123_sin_sensor_no_hay_factores_porque_no_hay_prediccion(con_modelo: TestClient):
    """RF-10b: no se rellena con algo que parezca una explicación de algo que no se predijo."""
    _subir_serie(con_modelo, datetime.now(UTC) - timedelta(minutes=40))
    cuerpo = con_modelo.get("/predict", headers=cabeceras()).json()

    assert cuerpo["predicciones"] == []
