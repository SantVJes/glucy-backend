"""`POST /explain`: el prompt, la validación, la plantilla y la caché (pruebas 81 a 96).

El Ollama de mentiras es un **servidor HTTP de verdad** en un puerto libre, no un parche sobre
la función: así se prueba el cliente completo —el tope de tiempo, las opciones que viajan y qué
pasa con un 500— y no solo la lógica que lo rodea. Un tope de tiempo parcheado nunca falla, y
el tope es justo el requisito (P-13).
"""

import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from app.config import Ajustes
from app.routers.explain import configuracion
from app.schemas.explicacion import ContribucionShap, ExplicacionEntrada
from app.services.explicacion.prompt import SISTEMA, mensaje_de_usuario
from app.services.explicacion.servicio import explicar, vaciar_cache
from app.services.explicacion.validacion import numeros, revisar
from referencia.reglas_clinicas import plantilla_explicacion
from tests.conftest import cabeceras

PETICION = {
    "valor_actual": 112,
    "valor_predicho": 74,
    "horizonte_min": 30,
    "modo": "sensor",
    "umbral_hipo": 70,
    "umbral_hiper": 180,
    "cob_g": 12,
    "iob_ui": 2.5,
    "hora_local": 3,
    "shap": [
        {"variable": "insulina que sigue activa", "mg_dl": -20},
        {"variable": "tendencia de la última media hora", "mg_dl": -10},
        {"variable": "carbohidratos que siguen activos", "mg_dl": -8},
    ],
}

BUENA = (
    "Vas a bajar en la próxima media hora, sobre todo porque la insulina que te aplicaste "
    "sigue activa. Es una estimación: conviene confirmarla con una medición."
)


class _Falso(BaseHTTPRequestHandler):
    """Contesta lo que la prueba le haya puesto en los atributos de clase."""

    texto = BUENA
    estado = 200
    demora_s = 0.0
    peticiones: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802 — lo exige BaseHTTPRequestHandler
        largo = int(self.headers.get("Content-Length", 0))
        type(self).peticiones.append(json.loads(self.rfile.read(largo)))
        time.sleep(type(self).demora_s)
        cuerpo = json.dumps({"message": {"content": type(self).texto}}).encode()
        self.send_response(type(self).estado)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *_: object) -> None:
        """Sin ruido en la salida de pytest."""


@pytest.fixture
def ollama_falso() -> Iterator[type[_Falso]]:
    _Falso.texto, _Falso.estado, _Falso.demora_s = BUENA, 200, 0.0
    _Falso.peticiones = []
    servidor = HTTPServer(("127.0.0.1", 0), _Falso)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    _Falso.url = f"http://127.0.0.1:{servidor.server_port}"  # type: ignore[attr-defined]
    vaciar_cache()
    yield _Falso
    servidor.shutdown()
    servidor.server_close()
    vaciar_cache()


def _con_ollama(cliente: TestClient, url: str | None, timeout_s: float = 5.0) -> None:
    """Apunta la app al Ollama de mentiras, o a ninguno."""
    from app.main import app

    app.dependency_overrides[configuracion] = lambda: Ajustes(
        jwt_secret="x", ollama_url=url or "", explicacion_timeout_s=timeout_s
    )


@pytest.fixture(autouse=True)
def _limpiar() -> Iterator[None]:
    vaciar_cache()
    yield
    from app.main import app

    app.dependency_overrides.pop(configuracion, None)
    vaciar_cache()


# ---------------------------------------------------------------------------
# La plantilla es el piso: estas tres pasan con la computadora de Ollama apagada.
# ---------------------------------------------------------------------------


def test_81_sin_ollama_configurado_sale_la_plantilla(cliente: TestClient):
    _con_ollama(cliente, None)
    respuesta = cliente.post("/explain", json=PETICION, headers=cabeceras())
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["origen"] == "plantilla"
    assert cuerpo["motivo"] == "sin_asistente"
    assert "estimación" in cuerpo["explicacion"]


def test_82_con_el_asistente_apagado_no_se_llama_a_nadie(
    cliente: TestClient, ollama_falso: type[_Falso]
):
    _con_ollama(cliente, ollama_falso.url)  # type: ignore[attr-defined]
    cuerpo = cliente.post(
        "/explain", json={**PETICION, "asistente_activo": False}, headers=cabeceras()
    ).json()
    assert cuerpo["origen"] == "plantilla"
    assert cuerpo["motivo"] == "sin_asistente"
    assert ollama_falso.peticiones == []


def test_83_la_plantilla_es_determinista(cliente: TestClient):
    _con_ollama(cliente, None)
    primera = cliente.post("/explain", json=PETICION, headers=cabeceras()).json()
    segunda = cliente.post("/explain", json=PETICION, headers=cabeceras()).json()
    assert primera == segunda


# ---------------------------------------------------------------------------
# Con el modelo de lenguaje contestando.
# ---------------------------------------------------------------------------


def test_84_una_respuesta_buena_se_devuelve_tal_cual(
    cliente: TestClient, ollama_falso: type[_Falso]
):
    _con_ollama(cliente, ollama_falso.url)  # type: ignore[attr-defined]
    cuerpo = cliente.post("/explain", json=PETICION, headers=cabeceras()).json()
    assert cuerpo["origen"] == "modelo"
    assert cuerpo["explicacion"] == BUENA
    assert cuerpo["motivo"] is None


def test_85_viajan_la_temperatura_cero_la_semilla_y_el_tope(
    cliente: TestClient, ollama_falso: type[_Falso]
):
    """La misma predicción tiene que dar siempre la misma explicación."""
    _con_ollama(cliente, ollama_falso.url)  # type: ignore[attr-defined]
    cliente.post("/explain", json=PETICION, headers=cabeceras())
    enviado = ollama_falso.peticiones[0]
    assert enviado["options"]["temperature"] == 0.0
    assert enviado["options"]["seed"] == 7
    assert enviado["options"]["num_predict"] == 160
    assert enviado["stream"] is False
    assert enviado["messages"][0] == {"role": "system", "content": SISTEMA}


def test_86_el_prompt_no_lleva_nada_de_quien_pregunta(
    cliente: TestClient, ollama_falso: type[_Falso]
):
    """Lo que identifica a la persona no sube, y menos a un modelo de lenguaje (regla 3)."""
    _con_ollama(cliente, ollama_falso.url)  # type: ignore[attr-defined]
    cliente.post("/explain", json=PETICION, headers=cabeceras())
    prompt = "\n".join(m["content"] for m in ollama_falso.peticiones[0]["messages"])
    from tests.conftest import USUARIO

    for prohibido in (str(USUARIO), "uuid", "nombre", "apellido", "peso", "nacimiento", "nota"):
        assert prohibido not in prompt.lower(), prohibido


def test_87_la_segunda_peticion_igual_sale_de_la_cache(
    cliente: TestClient, ollama_falso: type[_Falso]
):
    _con_ollama(cliente, ollama_falso.url)  # type: ignore[attr-defined]
    primera = cliente.post("/explain", json=PETICION, headers=cabeceras()).json()
    segunda = cliente.post("/explain", json=PETICION, headers=cabeceras()).json()
    assert primera == segunda
    assert len(ollama_falso.peticiones) == 1


# ---------------------------------------------------------------------------
# P-13 y la validación: lo que no sirve se descarta, no se corrige.
# ---------------------------------------------------------------------------


def test_88_p13_si_no_contesta_a_tiempo_sale_la_plantilla(
    cliente: TestClient, ollama_falso: type[_Falso]
):
    ollama_falso.demora_s = 1.5
    _con_ollama(cliente, ollama_falso.url, timeout_s=0.3)  # type: ignore[attr-defined]
    cuerpo = cliente.post("/explain", json=PETICION, headers=cabeceras()).json()
    assert cuerpo["origen"] == "plantilla"
    assert cuerpo["motivo"] == "sin_respuesta"


def test_89_si_contesta_un_error_sale_la_plantilla(
    cliente: TestClient, ollama_falso: type[_Falso]
):
    ollama_falso.estado = 500
    _con_ollama(cliente, ollama_falso.url)  # type: ignore[attr-defined]
    cuerpo = cliente.post("/explain", json=PETICION, headers=cabeceras()).json()
    assert cuerpo["motivo"] == "sin_respuesta"


def test_90_una_cifra_inventada_se_descarta(cliente: TestClient, ollama_falso: type[_Falso]):
    ollama_falso.texto = "Vas a bajar a 68 mg/dL. Es una estimación: conviene confirmarla."
    _con_ollama(cliente, ollama_falso.url)  # type: ignore[attr-defined]
    cuerpo = cliente.post("/explain", json=PETICION, headers=cabeceras()).json()
    assert cuerpo["origen"] == "plantilla"
    assert cuerpo["motivo"] == "no_paso_validacion"
    assert "68" not in cuerpo["explicacion"]


@pytest.mark.parametrize(
    "texto",
    [
        "Ponte 2 unidades de insulina antes de dormir.",
        "Te conviene tomar algo con azúcar ahora.",
        "Aplícate una corrección de insulina rápida.",
        "Debes comer 15 gramos de carbohidratos.",
        "Sube la dosis de insulina basal de la noche.",
        "Recomiendo un bolo pequeño.",
    ],
)
def test_91_cualquier_insinuacion_de_tratamiento_se_bloquea(
    cliente: TestClient, ollama_falso: type[_Falso], texto: str
):
    """La regla 7, comprobada sobre la salida y no solo pedida en el prompt."""
    ollama_falso.texto = texto
    _con_ollama(cliente, ollama_falso.url)  # type: ignore[attr-defined]
    cuerpo = cliente.post("/explain", json=PETICION, headers=cabeceras()).json()
    assert cuerpo["origen"] == "plantilla"
    assert cuerpo["motivo"] == "no_paso_validacion"


def test_92_una_respuesta_vacia_se_descarta(cliente: TestClient, ollama_falso: type[_Falso]):
    ollama_falso.texto = "   "
    _con_ollama(cliente, ollama_falso.url)  # type: ignore[attr-defined]
    cuerpo = cliente.post("/explain", json=PETICION, headers=cabeceras()).json()
    assert cuerpo["origen"] == "plantilla"


# ---------------------------------------------------------------------------
# El sobre.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cambio",
    [
        {"nombre": "Jesús"},
        {"usuario_uuid": "11111111-1111-1111-1111-111111111111"},
        {"nota": "me sentí mal"},
        {"peso_kg": 80},
    ],
)
def test_93_un_campo_que_identifica_es_400(cliente: TestClient, cambio: dict):
    _con_ollama(cliente, None)
    respuesta = cliente.post("/explain", json={**PETICION, **cambio}, headers=cabeceras())
    assert respuesta.status_code == 400


def test_94_mas_de_cinco_contribuciones_es_400(cliente: TestClient):
    _con_ollama(cliente, None)
    seis = [{"variable": f"v{i}", "mg_dl": -i} for i in range(6)]
    respuesta = cliente.post("/explain", json={**PETICION, "shap": seis}, headers=cabeceras())
    assert respuesta.status_code == 400


def test_95_sin_token_es_401(cliente: TestClient):
    _con_ollama(cliente, None)
    assert cliente.post("/explain", json=PETICION).status_code == 401


# ---------------------------------------------------------------------------
# El validador, directo.
# ---------------------------------------------------------------------------


def _entrada() -> ExplicacionEntrada:
    return ExplicacionEntrada(
        **{**PETICION, "shap": [ContribucionShap(**c) for c in PETICION["shap"]]}  # type: ignore[arg-type]
    )


def test_96_la_plantilla_pasa_su_propia_validacion():
    """La plantilla no se revisa —la arma el programa— pero si no pasara sería una pista de que
    el validador bloquea lenguaje legítimo. «Sube» y «baja» hablan de la glucosa, no de una
    dosis, y tienen que pasar."""
    entrada = _entrada()
    permitidos = numeros(mensaje_de_usuario(entrada))
    for actual, predicho in ((112, 74), (74, 112)):
        texto = plantilla_explicacion(
            actual, predicho, [(c.variable, c.mg_dl) for c in entrada.shap]
        )
        assert revisar(texto, permitidos + numeros(texto)) is None, texto


def test_97_la_magnitud_de_una_contribucion_se_puede_redactar_sin_signo():
    """Una contribución de −20 mg/dL redactada como «quita 20 mg/dL» es el mismo dato: lo que
    no puede cambiar es la magnitud."""
    permitidos = numeros(mensaje_de_usuario(_entrada()))
    assert revisar("La insulina que sigue activa quita unos 20 mg/dL.", permitidos) is None
    assert revisar("Ahora estás en 110 mg/dL.", permitidos) is not None


def test_98_sube_y_baja_de_la_glucosa_no_se_bloquean():
    assert revisar("Tu glucosa sube y luego baja un poco.", []) is None
    assert revisar("Sube la dosis de insulina.", []) is not None


def test_99_el_servicio_no_llama_a_nadie_sin_url():
    """El piso, probado sin cliente HTTP ni app: `explicar` con `None` arma la plantilla."""
    respuesta = explicar(_entrada(), None, "qwen3:8b", 10.0)
    assert respuesta.origen == "plantilla"
    assert respuesta.motivo == "sin_asistente"
