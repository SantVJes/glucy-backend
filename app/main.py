"""Punto de entrada de la API de Glucy.

La documentación OpenAPI se publica en `/docs` (RF-21, punto 14 de la rúbrica).
"""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import ajustes
from app.routers import insulin, meals, perfil, readings

VERSION = "0.1.0"

# Se leen los ajustes al importar: sin GLUCY_JWT_SECRET la aplicación no arranca.
ajustes()

app = FastAPI(
    title="Glucy",
    version=VERSION,
    description=(
        "API de Glucy: recibe lotes del teléfono, que es el dueño del dato. "
        "Glucy no es un dispositivo médico certificado: informa, nunca prescribe ni "
        "administra, y jamás calcula ni sugiere una dosis de insulina."
    ),
)


@app.exception_handler(RequestValidationError)
async def sobre_invalido(_: Request, error: RequestValidationError) -> JSONResponse:
    """Un sobre que no se puede usar es 400, no el 422 de FastAPI (RF-21, decisión 2.5).

    La app entiende 400 como «no me entendiste, no reintentes». Los renglones se validan uno
    por uno dentro del servicio, así que lo único que llega aquí es el sobre.
    """
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": jsonable_errores(error)},
    )


def jsonable_errores(error: RequestValidationError) -> list[dict]:
    """Solo la ubicación y el mensaje: no se devuelve el valor recibido."""
    return [{"loc": list(e["loc"]), "msg": e["msg"]} for e in error.errors()]


@app.get("/salud", tags=["salud"])
def salud() -> dict[str, str]:
    """Para el healthcheck del paso 4. No toca la base ni devuelve dato de nadie."""
    return {"estado": "ok", "version": VERSION}


app.include_router(readings.router)
app.include_router(meals.router)
app.include_router(insulin.router)
app.include_router(perfil.router)
