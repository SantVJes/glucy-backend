"""El tablero de Grafana: que el JSON esté al día y que sus consultas sean SQL válido.

Un panel roto no avisa. Enseña un rectángulo vacío o un error diminuto en una esquina, y la
primera vez que alguien lo mira en serio es cuando lo necesita. Lo que de verdad lo rompe es
renombrar una columna en una migración: el motor valida los nombres al planear la consulta
**aunque la tabla esté vacía**, así que correr las doce consultas contra el esquema migrado
atrapa justo esa clase de error, y es lo que hace la prueba marcada `postgres`.
"""

import json
import os
import re
import subprocess
import sys

import pytest
from sqlalchemy import text

from tests.conftest import RAIZ

GRAFANA = RAIZ / "grafana"
CONSULTAS = sorted((GRAFANA / "consultas").glob("*.sql"))
TABLERO = json.loads((GRAFANA / "tableros" / "glucy.json").read_text())

# Lo que una consulta de panel no puede contener. El usuario del origen de datos es de solo
# lectura (`grafana/lector.sql`), así que el motor también lo impediría; esto lo atrapa antes,
# en la revisión, donde cuesta un minuto en lugar de un incidente.
ESCRITURAS = re.compile(
    r"\b(insert|update|delete|drop|truncate|alter|create|grant|revoke|copy)\b", re.IGNORECASE
)


def test_el_json_del_tablero_esta_al_dia():
    """Si cambia un `.sql` y no se regenera el JSON, el panel enseña la consulta vieja."""
    hecho = subprocess.run(
        [sys.executable, str(GRAFANA / "armar_tablero.py"), "--ver"],
        capture_output=True,
        text=True,
    )
    assert hecho.returncode == 0, hecho.stdout + hecho.stderr


def test_estan_los_ocho_paneles_del_documento_2():
    """Ocho paneles pedidos, repartidos en doce consultas, más el aviso de cómo leerlos."""
    titulos = [p["title"] for p in TABLERO["panels"]]
    assert len(titulos) == 13
    for esperado in (
        "Glucosa por hora del día",
        "Tiempo en rango, bajo y alto",
        "Episodios de hipoglucemia, los nocturnos aparte",
        "Desempeño del modelo contra la persistencia",
        "Alertas y falsas alarmas por versión",
        "Qué hay en la cuarentena",
        "Salud de la cola hacia el Learning Record Store",
        "Sentencias xAPI por verbo",
        "Indicadores de aprendizaje",
        "Explicaciones: del modelo o de la plantilla",
        "Por qué salió la plantilla, y cuánto tarda cada camino",
    ):
        assert esperado in titulos


def test_el_aviso_de_no_concluyente_esta_en_el_tablero():
    """La regla del Documento 2 para este tablero, visible y no en un comentario del código."""
    aviso = next(p for p in TABLERO["panels"] if p["type"] == "text")
    assert "no concluyente" in aviso["options"]["content"]
    assert "no es un dispositivo médico certificado" in aviso["options"]["content"]
    # Y arriba de todo: si estuviera al final nadie lo leería.
    assert aviso["gridPos"]["y"] == 0


def test_ningun_panel_tapa_a_otro():
    """Grafana reacomoda los solapes por su cuenta y el tablero deja de parecerse al código."""
    ocupado: dict[tuple[int, int], str] = {}
    for panel in TABLERO["panels"]:
        g = panel["gridPos"]
        for x in range(g["x"], g["x"] + g["w"]):
            for y in range(g["y"], g["y"] + g["h"]):
                anterior = ocupado.get((x, y))
                assert anterior is None, f"«{panel['title']}» se encima con «{anterior}»"
                ocupado[(x, y)] = panel["title"]
        assert g["x"] + g["w"] <= 24, f"«{panel['title']}» se sale de la rejilla"


def test_cada_consulta_respeta_el_rango_de_tiempo_elegido():
    """Sin `$__timeFilter` el panel ignora el selector y lee la tabla completa."""
    for archivo in CONSULTAS:
        assert "$__timeFilter" in archivo.read_text(), archivo.name


def test_ninguna_consulta_escribe():
    for archivo in CONSULTAS:
        sin_comentarios = "\n".join(
            renglon
            for renglon in archivo.read_text().splitlines()
            if not renglon.lstrip().startswith("--")
        )
        encontrado = ESCRITURAS.search(sin_comentarios)
        assert encontrado is None, f"{archivo.name}: «{encontrado.group(0) if encontrado else ''}»"


def test_el_panel_no_queda_en_internet_abierto():
    """Las tres decisiones del servicio `panel`, cada una por un motivo distinto."""
    compose = (RAIZ / "docker-compose.yml").read_text()
    # `3000:3000` abriría el puerto en todas las interfaces y atravesaría el cortafuegos.
    assert '"127.0.0.1:3000:3000"' in compose
    assert '3000:3000"' not in compose.replace('"127.0.0.1:3000:3000"', "")
    assert 'GF_AUTH_ANONYMOUS_ENABLED: "false"' in compose
    # Una instantánea de Grafana se publica por omisión FUERA de este servidor.
    assert 'GF_SNAPSHOTS_EXTERNAL_ENABLED: "false"' in compose


def test_el_aprovisionamiento_no_lleva_ninguna_credencial():
    """Los valores salen del entorno; en el repositorio solo viven los nombres."""
    for archivo in (GRAFANA / "provisioning").rglob("*.yml"):
        texto = archivo.read_text()
        for renglon in texto.splitlines():
            limpio = renglon.strip()
            if limpio.startswith("#") or ":" not in limpio:
                continue
            clave, _, valor = limpio.partition(":")
            if any(p in clave.lower() for p in ("password", "secreto", "user", "usuario")):
                valor = valor.strip()
                assert valor.startswith("${"), f"{archivo.name}: «{limpio}»"


def test_el_origen_de_datos_es_el_que_usa_el_tablero():
    """Un uid distinto deja todos los paneles con «datasource not found»."""
    origen = next(a for a in (GRAFANA / "provisioning" / "datasources").glob("*.yml")).read_text()
    assert "uid: glucy-postgres" in origen
    for panel in TABLERO["panels"]:
        assert panel["datasource"]["uid"] == "glucy-postgres"


URL = os.environ.get("GLUCY_DATABASE_URL_POSTGRES")


@pytest.mark.postgres
@pytest.mark.skipif(not URL, reason="sin GLUCY_DATABASE_URL_POSTGRES")
def test_las_doce_consultas_corren_contra_postgresql():
    """El esquema migrado y vacío basta: el motor valida los nombres al planear.

    Es la prueba que atrapa la columna renombrada. Que los números sean los correctos se
    comprobó aparte, contra una base sembrada; está en `docs/fase6-paso-2-panel-de-grafana.md`.
    """
    from app.db.sesion import crear_motor  # noqa: PLC0415
    from tests.test_postgres import migrar, vaciar_el_esquema  # noqa: PLC0415

    vaciar_el_esquema()
    migrar(URL)
    motor = crear_motor(URL)
    try:
        for archivo in CONSULTAS:
            sql = re.sub(
                r"\$__timeFilter\(([^)]+)\)",
                r"\1 BETWEEN '2026-01-01 00:00:00+00' AND '2027-01-01 00:00:00+00'",
                archivo.read_text(),
            )
            with motor.connect() as conexion:
                conexion.execute(text(sql)).all()
    finally:
        motor.dispose()


def test_no_quedo_ninguna_consulta_sin_panel():
    """Un `.sql` que nadie dibuja es trabajo perdido; un panel sin `.sql` es un hueco."""
    en_el_tablero = {
        objetivo["rawSql"] for panel in TABLERO["panels"] for objetivo in panel.get("targets", [])
    }
    en_disco = {archivo.read_text().rstrip() + "\n" for archivo in CONSULTAS}
    assert en_el_tablero == en_disco
    assert len(CONSULTAS) == 12


def test_los_archivos_de_grafana_no_mencionan_nombres_de_personas():
    """Regla 3: lo que identifica a la persona no sube, y el servidor no lo tiene.

    La prueba es sobre las columnas, que es donde se colaría: `nombre`, `apellidos`, `peso` y
    `notas` no existen en este servidor, así que una consulta que las pidiera ni correría. Esto
    lo atrapa en la revisión y deja dicho por qué no están.
    """
    prohibidas = ("nombre", "apellido", "peso", "notas", "foto", "correo", "mbox")
    for archivo in CONSULTAS:
        cuerpo = "\n".join(
            renglon
            for renglon in archivo.read_text().splitlines()
            if not renglon.lstrip().startswith("--")
        ).lower()
        for palabra in prohibidas:
            assert palabra not in cuerpo, f"{archivo.name}: «{palabra}»"
