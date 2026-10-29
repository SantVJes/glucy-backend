"""El presente, en un solo lugar.

`datetime.now(UTC)` escrito dentro del servicio haría que una prueba de la ventana de envío no
pudiera fijar la hora, y la hora es justo lo que se marca al enviar. La orden lo pasa como
parámetro, y esta función existe para que la orden tenga de dónde sacarlo.
"""

from datetime import UTC, datetime


def ahora_utc() -> datetime:
    return datetime.now(UTC)
