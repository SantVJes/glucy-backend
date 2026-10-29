-- Panel 8b: por qué salió la plantilla, y cuánto tarda cada camino.
--
-- Los motivos no son equivalentes y por eso se desglosan: `sin_asistente` es la persona que lo
-- apagó y está bien; `sin_respuesta` es la computadora de Ollama apagada o pasada de los diez
-- segundos; `cifra_inventada` y `patron_de_dosificacion` son el modelo portándose mal, y son
-- los dos que hay que mirar, porque es la validación de la regla 7 haciendo su trabajo.
SELECT
  origen                              AS "Origen",
  COALESCE(motivo, '—')               AS "Motivo",
  COUNT(*)                            AS "Veces",
  ROUND(AVG(duracion_ms)::numeric, 0) AS "ms medios",
  MAX(duracion_ms)                    AS "ms peor caso"
FROM explicaciones
WHERE $__timeFilter(ts_utc)
GROUP BY 1, 2
ORDER BY 3 DESC
