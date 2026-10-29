"""Pruebas del Learning Record Store: `POST /xapi`, la sentencia y la ventana de envío.

El LRS de las pruebas es un **servidor HTTP de verdad** en un puerto libre, no un parche sobre
`httpx.post`. Con un parche, el tope de tiempo nunca se agota y la cabecera que Learning Locker
exige nunca se comprueba, que son justo las dos cosas que más fallan al integrar xAPI.
"""

import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tablas import EventoXapi
from app.schemas.xapi import (
    ACTIVIDADES,
    BASE_IRI,
    COMBINACIONES,
    VERBOS,
    VERSION_XAPI,
    Actividad,
    Verbo,
)
from app.services.xapi.envio import enviar_pendientes
from app.services.xapi.lrs import CABECERA_VERSION, ConfiguracionLrs
from app.services.xapi.sentencia import duracion_iso
from tests.conftest import USUARIO, cabeceras, contar

# Las marcas de los eventos son del 28 y `AHORA` del 29: un evento tiene que haber
# ocurrido ya, y una fecha fija no se vuelve futura con el paso de los días.
AHORA = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
OTRO_USUARIO = UUID("22222222-2222-2222-2222-222222222222")


def evento(**sobre: Any) -> dict[str, Any]:
    base = {
        "uuid": str(uuid4()),
        "ts_utc": "2026-10-28T11:00:00Z",
        "verbo": "experienced",
        "actividad": "registro-de-glucosa",
    }
    return {**base, **sobre}


def subir(cliente: TestClient, *eventos: dict[str, Any], sub: UUID = USUARIO):
    return cliente.post("/xapi", json={"items": list(eventos)}, headers=cabeceras(sub))


# --- El endpoint y las tres listas -----------------------------------------------------------


def test_un_lote_bueno_sale_todo_en_aceptados(cliente: TestClient):
    respuesta = subir(
        cliente, evento(), evento(verbo="received", actividad="alerta-de-hipoglucemia")
    )
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert len(cuerpo["aceptados"]) == 2
    assert cuerpo["duplicados"] == []
    assert cuerpo["cuarentena"] == []


def test_el_mismo_lote_dos_veces_no_crea_filas(cliente: TestClient, sesion: Session):
    uno = evento()
    assert subir(cliente, uno).json()["aceptados"] == [uno["uuid"]]
    segunda = subir(cliente, uno).json()
    assert segunda["aceptados"] == []
    assert segunda["duplicados"] == [uno["uuid"]]
    assert contar(sesion, EventoXapi) == 1


def test_un_uuid_repetido_dentro_del_mismo_lote_entra_una_vez(cliente: TestClient):
    uno = evento()
    cuerpo = subir(cliente, uno, dict(uno)).json()
    assert cuerpo["aceptados"] == [uno["uuid"]]
    assert cuerpo["duplicados"] == [uno["uuid"]]


def test_sin_token_es_401(cliente: TestClient):
    assert cliente.post("/xapi", json={"items": [evento()]}).status_code == 401


def test_un_sobre_vacio_es_400(cliente: TestClient):
    assert cliente.post("/xapi", json={"items": []}, headers=cabeceras()).status_code == 400


def test_cada_quien_ve_solo_lo_suyo(cliente: TestClient, sesion: Session):
    mio, suyo = evento(), evento()
    subir(cliente, mio)
    subir(cliente, suyo, sub=OTRO_USUARIO)
    duenos = {
        str(f.usuario_uuid)
        for f in sesion.scalars(select(EventoXapi).where(EventoXapi.uuid == UUID(mio["uuid"])))
    }
    assert duenos == {str(USUARIO)}


# --- Lo que va a cuarentena ------------------------------------------------------------------


def test_una_marca_de_tiempo_futura_va_a_cuarentena(cliente: TestClient):
    futuro = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    cuerpo = subir(cliente, evento(ts_utc=futuro)).json()
    assert "futura" in cuerpo["cuarentena"][0]["motivo"]


def test_un_verbo_que_no_va_con_la_actividad_va_a_cuarentena(cliente: TestClient):
    """«Contestó una medición de glucosa» no es un dato raro: es el teléfono mandando otra cosa."""
    cuerpo = subir(cliente, evento(verbo="answered", actividad="registro-de-glucosa")).json()
    motivo = cuerpo["cuarentena"][0]["motivo"]
    assert "no va con la actividad" in motivo
    assert "evaluacion" in motivo  # dice con cuál sí va


def test_un_verbo_desconocido_va_a_cuarentena(cliente: TestClient):
    cuerpo = subir(cliente, evento(verbo="bailo")).json()
    assert cuerpo["cuarentena"][0]["motivo"].startswith("verbo:")


def test_un_actor_mandado_por_el_telefono_va_a_cuarentena(cliente: TestClient):
    """El actor lo arma el servidor. Aceptarlo sería dejar que el teléfono escriba en el LRS."""
    cuerpo = subir(cliente, evento(actor={"mbox": "mailto:alguien@ejemplo.com"})).json()
    assert "los arma el servidor" in cuerpo["cuarentena"][0]["motivo"]
    assert "regla 3" in cuerpo["cuarentena"][0]["motivo"]


def test_una_nota_va_a_cuarentena(cliente: TestClient):
    """Es el caso que la regla 3 prohíbe: texto libre que se va del teléfono."""
    cuerpo = subir(cliente, evento(nota="me sentí mareado")).json()
    assert "texto libre" in cuerpo["cuarentena"][0]["motivo"]


def test_la_cuarentena_no_guarda_nada_del_texto_que_llego(cliente: TestClient, sesion: Session):
    """De un renglón rechazado se guardan uuid y hora, y de lo demás solo el nombre de la clave.

    Es más estricto que en los lotes clínicos a propósito: ahí la carga son números y enums, y
    aquí cualquier campo podría traer texto. Se pierde detalle para diagnosticar y se gana que
    la tabla de diagnóstico no sea la puerta de atrás por la que entra una nota.
    """
    subir(cliente, evento(nota="texto que no debe quedar en ninguna parte"))
    filas = list(sesion.execute(select(*_columnas_de_cuarentena(sesion))))
    carga = json.dumps([dict(zip(("carga", "claves"), f, strict=True)) for f in filas])
    assert "texto que no debe quedar" not in carga
    assert "nota" in carga  # el nombre de la clave sí, para poder arreglarlo


def _columnas_de_cuarentena(sesion: Session):
    from app.models.tablas import Cuarentena

    return (Cuarentena.carga_original, Cuarentena.claves_descartadas)


def test_un_usuario_uuid_distinto_del_token_va_a_cuarentena(cliente: TestClient):
    cuerpo = subir(cliente, evento(usuario_uuid=str(OTRO_USUARIO))).json()
    assert "distinto del token" in cuerpo["cuarentena"][0]["motivo"]


def test_un_puntaje_en_un_verbo_que_no_puntua_va_a_cuarentena(cliente: TestClient):
    cuerpo = subir(cliente, evento(puntaje=0.8)).json()
    assert "no puntúa nada" in cuerpo["cuarentena"][0]["motivo"]


def test_un_puntaje_fuera_de_cero_a_uno_va_a_cuarentena(cliente: TestClient):
    """`score.scaled` de xAPI es de 0 a 1. Un 85 ahí lo rechazaría el LRS, no nosotros."""
    cuerpo = subir(cliente, evento(verbo="answered", actividad="evaluacion", puntaje=85)).json()
    assert cuerpo["cuarentena"][0]["motivo"].startswith("puntaje:")


def test_una_duracion_negativa_va_a_cuarentena(cliente: TestClient):
    cuerpo = subir(
        cliente, evento(verbo="launched", actividad="modulo-educativo", duracion_s=-5)
    ).json()
    assert cuerpo["cuarentena"][0]["motivo"].startswith("duracion_s:")


# --- La fila que se guarda es la sentencia que se va a mandar --------------------------------


def _fila(sesion: Session, uuid: str) -> EventoXapi:
    sesion.expire_all()
    return sesion.scalars(select(EventoXapi).where(EventoXapi.uuid == UUID(uuid))).one()


def test_el_actor_es_una_cuenta_con_el_uuid_y_nada_mas(cliente: TestClient, sesion: Session):
    """Sin `mbox`: un correo en el actor sería la fuga completa, y el servidor no lo sabe."""
    uno = evento()
    subir(cliente, uno)
    actor = _fila(sesion, uno["uuid"]).actor
    assert actor == {
        "objectType": "Agent",
        "account": {"homePage": f"{BASE_IRI}/usuarios", "name": str(USUARIO)},
    }
    assert "mbox" not in json.dumps(actor)


def test_el_objeto_lleva_el_iri_de_la_actividad_y_su_nombre_en_espanol(
    cliente: TestClient, sesion: Session
):
    uno = evento(verbo="launched", actividad="modulo-educativo")
    subir(cliente, uno)
    objeto = _fila(sesion, uno["uuid"]).objeto
    assert objeto is not None
    assert objeto["id"] == f"{BASE_IRI}/actividades/modulo-educativo"
    assert objeto["definition"]["name"]["es-MX"] == "un módulo educativo"


def test_sin_los_tres_numeros_la_sentencia_no_lleva_resultado(cliente: TestClient, sesion: Session):
    """Un `result` vacío es válido en xAPI y no significa nada; en el panel parecería un dato."""
    uno = evento()
    subir(cliente, uno)
    assert _fila(sesion, uno["uuid"]).resultado is None


def test_el_resultado_lleva_exito_puntaje_y_duracion_en_el_formato_de_xapi(
    cliente: TestClient, sesion: Session
):
    uno = evento(
        verbo="answered", actividad="evaluacion", exito=True, puntaje=0.75, duracion_s=42.5
    )
    subir(cliente, uno)
    assert _fila(sesion, uno["uuid"]).resultado == {
        "success": True,
        "score": {"scaled": 0.75},
        "duration": "PT42.50S",
    }


@pytest.mark.parametrize(("segundos", "esperado"), [(30, "PT30S"), (42.5, "PT42.50S"), (0, "PT0S")])
def test_la_duracion_sale_en_iso_8601(segundos: float, esperado: str):
    """Un número suelto hace que el LRS rechace el lote completo con un 400 ilegible."""
    assert duracion_iso(segundos) == esperado


def test_la_fila_no_lleva_ninguna_cifra_clinica(cliente: TestClient, sesion: Session):
    """La regla del paso: el LRS es un registro de aprendizaje, no una copia de datos de salud.

    Dice que la persona registró una medición, nunca cuánto marcó, así que el LRS —que es un
    servidor de terceros con su propia base— no tiene razón para contener datos de salud.
    """
    uno = evento()
    subir(cliente, uno)
    fila = _fila(sesion, uno["uuid"])
    texto = json.dumps([fila.actor, fila.objeto, fila.resultado])
    for palabra in ("mg_dl", "mg/dL", "glucosa_valor", "carbs", "unidades"):
        assert palabra not in texto


# --- El vocabulario, con el cotejo del 29/10/2026 fijado -------------------------------------


def test_los_seis_verbos_tienen_iri_y_display():
    assert set(VERBOS) == set(Verbo)
    for datos in VERBOS.values():
        assert datos.iri.startswith("http")
        assert datos.display


def test_cuales_verbos_estan_en_el_perfil_de_adl():
    """Cotejado contra `adl/adl.jsonld` de adlnet/xapi-authored-profiles el 29/10/2026.

    Se fija con una prueba porque es lo que el reporte tiene que decir: tres de los seis verbos
    **no** están en el perfil que publica ADL, y escribir «xAPI 1.0.3» sin más lo esconde.
    Cambiar uno de estos valores sin volver a cotejar hace fallar esta prueba.
    """
    en_el_perfil = {v for v, datos in VERBOS.items() if datos.en_el_perfil_de_adl}
    assert en_el_perfil == {Verbo.EXPERIENCED, Verbo.LAUNCHED, Verbo.ANSWERED}


def test_received_usa_el_vocabulario_de_activity_streams():
    """No existe en el de ADL, así que se toma el que usa todo el mundo para «recibió»."""
    assert VERBOS[Verbo.RECEIVED].iri == "http://activitystrea.ms/schema/1.0/receive"


def test_cada_verbo_tiene_al_menos_una_actividad_y_cada_actividad_un_verbo():
    assert set(COMBINACIONES) == set(Verbo)
    assert set(ACTIVIDADES) == set(Actividad)
    alcanzables = {a for actividades in COMBINACIONES.values() for a in actividades}
    assert alcanzables == set(Actividad)


# --- La ventana de envío, contra un Learning Locker de mentiras ------------------------------


class _LrsFalso(BaseHTTPRequestHandler):
    estado = 204
    peticiones: list[dict[str, Any]] = []
    url = ""

    def do_POST(self) -> None:  # noqa: N802  (lo exige BaseHTTPRequestHandler)
        cuerpo = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        _LrsFalso.peticiones.append(
            {
                "ruta": self.path,
                "version": self.headers.get(CABECERA_VERSION),
                "auth": self.headers.get("Authorization"),
                "sentencias": json.loads(cuerpo or b"[]"),
            }
        )
        self.send_response(_LrsFalso.estado)
        self.end_headers()
        if _LrsFalso.estado >= 400:
            self.wfile.write(b"el LRS dijo que no")

    def log_message(self, *_: Any) -> None:
        pass


@pytest.fixture
def lrs() -> Iterator[type[_LrsFalso]]:
    _LrsFalso.estado, _LrsFalso.peticiones = 204, []
    servidor = HTTPServer(("127.0.0.1", 0), _LrsFalso)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    _LrsFalso.url = f"http://127.0.0.1:{servidor.server_port}"
    yield _LrsFalso
    servidor.shutdown()
    servidor.server_close()


def configuracion(url: str) -> ConfiguracionLrs:
    return ConfiguracionLrs(url=url, usuario="clave", secreto="secreto", timeout_s=3.0)


def test_la_ventana_manda_lo_pendiente_y_lo_marca(
    cliente: TestClient, sesion: Session, lrs: type[_LrsFalso]
):
    uno = evento()
    subir(cliente, uno)
    resumen = enviar_pendientes(sesion, configuracion(lrs.url), AHORA)
    assert (resumen.enviadas, resumen.rechazadas, resumen.pendientes) == (1, 0, 0)
    assert resumen.el_lrs_contesto
    fila = _fila(sesion, uno["uuid"])
    assert fila.enviado_ts == AHORA
    assert fila.intentos == 1
    assert fila.motivo_rechazo is None


def test_la_peticion_lleva_la_ruta_la_cabecera_y_el_basic(
    cliente: TestClient, sesion: Session, lrs: type[_LrsFalso]
):
    """Sin `X-Experience-API-Version` Learning Locker contesta 400 a todo, y no dice por qué."""
    subir(cliente, evento())
    enviar_pendientes(sesion, configuracion(lrs.url), AHORA)
    peticion = lrs.peticiones[0]
    assert peticion["ruta"] == "/data/xAPI/statements"
    assert peticion["version"] == VERSION_XAPI
    assert peticion["auth"].startswith("Basic ")


def test_el_id_de_la_sentencia_es_el_uuid_del_telefono(
    cliente: TestClient, sesion: Session, lrs: type[_LrsFalso]
):
    """Así reenviar la cola después de un corte no duplica nada en el LRS (RF-36c)."""
    uno = evento()
    subir(cliente, uno)
    enviar_pendientes(sesion, configuracion(lrs.url), AHORA)
    [sentencia] = lrs.peticiones[0]["sentencias"]
    assert sentencia["id"] == uno["uuid"]
    assert sentencia["verb"]["id"] == VERBOS[Verbo.EXPERIENCED].iri
    assert sentencia["timestamp"].startswith("2026-10-28T11:00:00")


def test_las_sentencias_salen_de_la_mas_antigua_a_la_mas_reciente(
    cliente: TestClient, sesion: Session, lrs: type[_LrsFalso]
):
    """Un LRS que las recibe desordenadas calcula mal cualquier indicador de secuencia."""
    vieja = evento(ts_utc="2026-10-28T08:00:00Z")
    nueva = evento(ts_utc="2026-10-28T10:00:00Z")
    subir(cliente, nueva, vieja)
    enviar_pendientes(sesion, configuracion(lrs.url), AHORA)
    salieron = [s["id"] for s in lrs.peticiones[0]["sentencias"]]
    assert salieron == [vieja["uuid"], nueva["uuid"]]


def test_la_segunda_ventana_no_remanda_lo_que_ya_salio(
    cliente: TestClient, sesion: Session, lrs: type[_LrsFalso]
):
    subir(cliente, evento())
    enviar_pendientes(sesion, configuracion(lrs.url), AHORA)
    resumen = enviar_pendientes(sesion, configuracion(lrs.url), AHORA)
    assert (resumen.enviadas, resumen.pendientes) == (0, 0)
    assert len(lrs.peticiones) == 1


def test_sin_url_del_lrs_no_se_toca_nada_y_no_se_llama_a_nadie(
    cliente: TestClient, sesion: Session
):
    """Es el piso de la función: el LRS es para analítica y nada depende de que exista."""
    uno = evento()
    subir(cliente, uno)
    resumen = enviar_pendientes(sesion, ConfiguracionLrs(), AHORA)
    assert resumen.pendientes == 1
    assert resumen.detenida_por is not None
    assert "GLUCY_LRS_URL" in resumen.detenida_por
    assert _fila(sesion, uno["uuid"]).enviado_ts is None


def test_el_lrs_caido_deja_todo_pendiente_y_no_gasta_nada(cliente: TestClient, sesion: Session):
    """La propiedad que pide el requisito: una caída de una semana no tira ninguna sentencia.

    Se apunta a un puerto donde no hay nadie, que es lo que pasa con el contenedor apagado.
    """
    uno = evento()
    subir(cliente, uno)
    resumen = enviar_pendientes(sesion, configuracion("http://127.0.0.1:9"), AHORA)
    assert (resumen.enviadas, resumen.pendientes) == (0, 1)
    assert not resumen.el_lrs_contesto
    fila = _fila(sesion, uno["uuid"])
    assert fila.enviado_ts is None
    assert fila.motivo_rechazo is None
    assert fila.intentos == 0  # una caída no es un intento gastado


@pytest.mark.parametrize("estado", [401, 403, 500, 503])
def test_credenciales_malas_y_errores_del_servidor_dejan_la_cola_quieta(
    cliente: TestClient, sesion: Session, lrs: type[_LrsFalso], estado: int
):
    """Ninguno de los cuatro es culpa de las sentencias, así que ninguna se marca."""
    uno = evento()
    subir(cliente, uno)
    lrs.estado = estado
    resumen = enviar_pendientes(sesion, configuracion(lrs.url), AHORA)
    assert (resumen.enviadas, resumen.rechazadas, resumen.pendientes) == (0, 0, 1)
    assert resumen.detenida_por is not None
    assert _fila(sesion, uno["uuid"]).motivo_rechazo is None


def test_un_lote_rechazado_se_reintenta_de_una_en_una(
    cliente: TestClient, sesion: Session, lrs: type[_LrsFalso]
):
    """xAPI valida el lote completo: una sentencia mala hace que el LRS conteste 400 por todas.

    Sin el reintento individual, un solo error de programación nuestro sacaría de la cola a las
    noventa y nueve sentencias buenas que iban en el mismo lote.
    """
    uno, dos = evento(), evento()
    subir(cliente, uno, dos)
    lrs.estado = 400
    resumen = enviar_pendientes(sesion, configuracion(lrs.url), AHORA)
    # 1 del lote + 2 individuales
    assert len(lrs.peticiones) == 3
    assert [len(p["sentencias"]) for p in lrs.peticiones] == [2, 1, 1]
    assert (resumen.enviadas, resumen.rechazadas, resumen.pendientes) == (0, 2, 0)
    assert "400" in (_fila(sesion, uno["uuid"]).motivo_rechazo or "")


def test_una_rechazada_sale_de_la_cola_con_su_motivo_y_no_se_borra(
    cliente: TestClient, sesion: Session, lrs: type[_LrsFalso]
):
    """Una sentencia rechazada sin rastro es una falla invisible (RF-22)."""
    uno = evento()
    subir(cliente, uno)
    lrs.estado = 400
    enviar_pendientes(sesion, configuracion(lrs.url), AHORA)
    assert contar(sesion, EventoXapi) == 1
    segunda = enviar_pendientes(sesion, configuracion(lrs.url), AHORA)
    assert segunda.pendientes == 0  # ya no se reintenta: reintentar lo mismo da lo mismo


def test_una_fila_con_un_verbo_desconocido_no_tapa_la_cola(
    cliente: TestClient, sesion: Session, lrs: type[_LrsFalso]
):
    """Una fila de otra versión no puede quedarse al frente impidiendo que salga lo de hoy."""
    bueno = evento()
    subir(cliente, bueno)
    sesion.execute(
        EventoXapi.__table__.insert().values(
            uuid=uuid4(),
            usuario_uuid=USUARIO,
            ts_utc=datetime(2026, 10, 28, 7, 0, tzinfo=UTC),
            actor={"objectType": "Agent"},
            verbo="de-otra-version",
            objeto={"id": "x"},
            intentos=0,
        )
    )
    sesion.commit()
    resumen = enviar_pendientes(sesion, configuracion(lrs.url), AHORA)
    assert (resumen.enviadas, resumen.rechazadas, resumen.pendientes) == (1, 1, 0)
    assert [s["id"] for s in lrs.peticiones[0]["sentencias"]] == [bueno["uuid"]]


def test_la_cola_vacia_no_llama_al_lrs(sesion: Session, lrs: type[_LrsFalso]):
    resumen = enviar_pendientes(sesion, configuracion(lrs.url), AHORA)
    assert (resumen.enviadas, resumen.pendientes) == (0, 0)
    assert lrs.peticiones == []
