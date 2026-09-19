# API

Los siete endpoints con ejemplos de petición y respuesta, errores y límites.
Sale del punto 14 del reporte y de la OpenAPI que genera FastAPI en `/docs`.

| Endpoint | Método | Para qué |
| --- | --- | --- |
| `/readings` | POST | lote de lecturas de glucosa |
| `/meals` | POST | lote de comidas |
| `/insulin` | POST | lote de dosis |
| `/predict` | GET | predicción a 30 y 60 min y con qué modo respondió |
| `/explain` | POST | explicación en lenguaje natural |
| `/stats` | GET | TIR, promedio, GMI, coeficiente de variación |
| `/history` | GET | histórico para el panel y la exportación |

_Pendiente de llenar en la fase 2._
