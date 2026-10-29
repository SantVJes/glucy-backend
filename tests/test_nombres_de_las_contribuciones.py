"""Que ningún nombre de característica llegue crudo a una pantalla (C-15).

`rezago_30` y `derivada_2` son el contrato con el pipeline y con glucy-ml, y ahí se quedan. Lo
que se prueba aquí es que no salgan de ahí: ni a la plantilla determinista, ni al prompt del
modelo de lenguaje, que es donde más daño hacían.
"""

import pytest

from app.schemas.explicacion import ContribucionShap, ExplicacionEntrada
from app.services.explicacion.prompt import mensaje_de_usuario
from app.services.explicacion.validacion import numeros, revisar
from app.services.nombres import NOMBRES, legible, legibles
from app.services.pipeline.caracteristicas import (
    CARACTERISTICAS_DENSAS,
    CARACTERISTICAS_DISPERSAS,
)
from referencia.reglas_clinicas import Modo, plantilla_explicacion

TODAS = set(CARACTERISTICAS_DENSAS) | set(CARACTERISTICAS_DISPERSAS)


def test_01_todas_las_caracteristicas_tienen_nombre_en_palabras():
    """La prueba que importa de este módulo.

    Una característica nueva sin su nombre llegaría cruda a la pantalla y nadie lo notaría
    hasta leerla. Aquí se cae la integración continua en su lugar.
    """
    assert TODAS - set(NOMBRES) == set()


def test_02_no_sobra_ningun_nombre():
    """Un nombre de más es una característica que se quitó del pipeline y nadie limpió aquí."""
    assert set(NOMBRES) - TODAS == set()


def test_03_ningun_nombre_tiene_pinta_de_tecnicismo():
    for variable, nombre in NOMBRES.items():
        assert "_" not in nombre, variable
        assert nombre == nombre.lower() or nombre[0].isupper(), variable
        assert variable not in nombre, variable


def test_04_una_caracteristica_desconocida_no_revienta():
    """Mejor un nombre feo que ninguna explicación; la cobertura la cuida la prueba 01."""
    assert legible("caracteristica_que_no_existe") == "caracteristica_que_no_existe"


def test_10_las_dos_mitades_de_la_hora_se_suman_en_una_sola_idea():
    """SHAP es aditivo, así que sumar dos columnas de una misma idea es correcto.

    Sin esto «la hora del día» aparecía dos veces con dos cifras distintas, que es justo lo que
    hace que una explicación deje de creerse.
    """
    resultado = legibles([("hora_sin", 4.0), ("hora_cos", -1.5), ("cob", 7.0)])

    assert resultado == [
        ("los carbohidratos que siguen activos", 7.0),
        ("la hora del día", 2.5),
    ]


def test_11_se_ordenan_por_magnitud_y_el_signo_no_se_pierde():
    resultado = legibles([("cob", 2.0), ("iob", -9.0)])
    assert [nombre for nombre, _ in resultado] == [
        "la insulina que sigue activa",
        "los carbohidratos que siguen activos",
    ]
    assert resultado[0][1] == -9.0


def _entrada(**cambios) -> ExplicacionEntrada:
    datos = {
        "valor_actual": 112.0,
        "valor_predicho": 74.0,
        "horizonte_min": 30,
        "modo": Modo.SENSOR,
        "umbral_hipo": 70.0,
        "umbral_hiper": 180.0,
        "cob_g": 12.0,
        "iob_ui": 2.5,
        "hora_local": 15,
        "shap": [
            ContribucionShap(variable="iob", mg_dl=-20.0),
            ContribucionShap(variable="rezago_30", mg_dl=-10.0),
            ContribucionShap(variable="derivada_1", mg_dl=-8.0),
        ],
    }
    return ExplicacionEntrada(**{**datos, **cambios})


def test_20_el_prompt_no_lleva_un_solo_nombre_crudo():
    """El sistema le prohíbe al modelo usar tecnicismos y antes le entregaba los datos en
    tecnicismos: para obedecer tenía que adivinar qué era `rezago_30`."""
    mensaje = mensaje_de_usuario(_entrada())

    for variable in TODAS:
        assert variable not in mensaje, variable
    assert "la insulina que sigue activa: -20 mg/dL" in mensaje
    assert "tu glucosa de hace media hora: -10 mg/dL" in mensaje


def test_21_el_prompt_sigue_sin_llevar_nada_de_quien_es_la_persona():
    mensaje = mensaje_de_usuario(_entrada())
    for prohibido in ("uuid", "nombre", "peso", "notas", "correo"):
        assert prohibido not in mensaje.lower()


# ---------------------------------------------------------------------------
# C-15: la plantilla ya no se contradice.
# ---------------------------------------------------------------------------


def test_30_la_direccion_y_las_contribuciones_van_por_separado():
    """Antes decía «Sube sobre todo POR tu glucosa de ahora (-29 mg/dL)».

    La dirección compara el valor predicho con el actual; una contribución SHAP se mide contra
    el valor base del modelo. Son dos referencias distintas, y la palabra «por» las unía.
    """
    texto = plantilla_explicacion(85, 120, [("tu glucosa de ahora", -29.0)])

    assert texto.startswith("Vas a subir.")
    assert "sobre todo por" not in texto
    assert "-29 mg/dL" in texto


@pytest.mark.parametrize(
    "actual, predicho, principio",
    [(120, 85, "Vas a bajar."), (85, 120, "Vas a subir."), (110, 110, "Te mantienes igual.")],
)
def test_31_las_tres_direcciones(actual, predicho, principio):
    assert plantilla_explicacion(actual, predicho, []).startswith(principio)


def test_32_sin_contribuciones_la_plantilla_sigue_siendo_una_frase_honesta():
    texto = plantilla_explicacion(120, 85, [])
    assert "los datos de las últimas horas" in texto
    assert "confirmar con una medición" in texto


def test_33_la_plantilla_entera_pasa_su_propio_validador():
    """Es el piso de la función: si no pasara, el validador estaría bloqueando lenguaje
    legítimo y la app se quedaría sin explicación ninguna."""
    entrada = _entrada()
    texto = plantilla_explicacion(
        entrada.valor_actual,
        entrada.valor_predicho,
        legibles([(c.variable, c.mg_dl) for c in entrada.shap]),
    )
    permitidos = numeros(mensaje_de_usuario(entrada)) + numeros(texto)

    assert revisar(texto, permitidos) is None, texto
    # Y nada de la superficie prohibida: la app habla de «insulina que sigue activa», no de UI.
    assert " ui" not in texto.lower()
