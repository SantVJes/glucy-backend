"""`/stats`: los indicadores del periodo y cuándo se enseñan (RF-16, paso 3).

No calcula ningún indicador por su cuenta: los pide a la referencia. Lo único que hace aquí
es contar días locales, que es lo que decide si las cifras se enseñan.
"""

from datetime import UTC, date, tzinfo
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.models.tablas import LecturaGlucosa
from app.repositories import consultas as repo_consultas
from app.schemas.consultas import Indicadores, Periodo, RespuestaStats
from referencia.reglas_clinicas import (
    UMBRAL_HIPER_DEFECTO,
    UMBRAL_HIPO_DEFECTO,
    gmi_es_fiable,
    hay_suficientes_dias,
    indicadores,
)


def calcular(sesion: Session, usuario_uuid: UUID, periodo: Periodo) -> RespuestaStats:
    """Arma /stats. No calcula ningún indicador por su cuenta: los pide a la referencia.

    Si el servidor y el teléfono pudieran dar números distintos para los mismos datos, algún
    día los darían. Un usuario sin lecturas, o que no existe, devuelve `indicadores: None` y
    no un 404 (decisión 2.9).
    """
    # 1. Las lecturas del periodo, sin límite: hay que contar días.
    lecturas = repo_consultas.lecturas_del_periodo(
        sesion, usuario_uuid, periodo.desde, periodo.hasta
    )

    # 2. Días locales, con la zona de cada renglón (decisión 2.3).
    dias = len({dia_local(lectura) for lectura in lecturas})

    # Los umbrales van en la respuesta en los dos casos, así que se leen antes de la puerta.
    # Sin perfil, los de omisión, y se dice (decisión 2.4): el historial no se cae el primer día.
    umbrales = repo_consultas.umbrales_del_perfil(sesion, usuario_uuid)
    umbral_hipo, umbral_hiper = umbrales or (UMBRAL_HIPO_DEFECTO, UMBRAL_HIPER_DEFECTO)
    respuesta = {
        "desde": periodo.desde,
        "hasta": periodo.hasta,
        "dias_con_lecturas": dias,
        "umbrales_del_perfil": umbrales is not None,
        "umbral_hipo": umbral_hipo,
        "umbral_hiper": umbral_hiper,
    }

    # 3. Con menos de tres días no se enseña nada: faltan datos, no un cero.
    if not hay_suficientes_dias(dias):
        return RespuestaStats(**respuesta, indicadores=None)

    # 4 y 5. Los indicadores, de la referencia, con los umbrales del perfil.
    calculados = indicadores([lectura.mg_dl for lectura in lecturas], umbral_hipo, umbral_hiper)

    # 6. Con menos de catorce días se enseña todo menos el GMI, sin tocar el resto.
    return RespuestaStats(
        **respuesta,
        indicadores=Indicadores(
            n=calculados.n,
            promedio=calculados.promedio,
            desviacion=calculados.desviacion,
            coeficiente_variacion=calculados.coeficiente_variacion,
            tir=calculados.tir,
            tbr=calculados.tbr,
            tar=calculados.tar,
            gmi=calculados.gmi if gmi_es_fiable(dias) else None,
        ),
    )


def dia_local(lectura: LecturaGlucosa) -> date:
    """El día de la lectura en la zona guardada con ella, igual que `DiaTipico.diaLocal`.

    Contar en UTC haría que una lectura de las 19:00 en Monterrey —01:00 UTC del día
    siguiente— cayera en otro día que en el teléfono, y los días deciden si las cifras se
    enseñan. Una zona ilegible no tumba la consulta: esa lectura se agrupa por UTC, que es lo
    único que se sabe de ella con certeza, como hace el Swift.
    """
    return lectura.ts_utc.astimezone(_zona(lectura.zona_horaria)).date()


def _zona(nombre: str) -> tzinfo:
    try:
        return ZoneInfo(nombre)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return UTC
