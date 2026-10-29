-- Panel 1: distribución de glucosa por hora del día **local**.
--
-- Lee `serie_limpia` y no `agregados_horarios`, aunque los agregados ya estén calculados y
-- fueran más baratos. El motivo: `agregados_horarios.periodo` guarda el inicio de la hora
-- local **convertido a UTC** y la tabla no tiene columna de zona, así que de ahí no se puede
-- recuperar la hora local. `EXTRACT(HOUR FROM periodo)` devuelve la hora UTC, y para México
-- eso corre la curva seis horas: una bajada de las 03:00 de la madrugada aparecería a las
-- 09:00. En el panel cuya pregunta es «¿a qué hora del día me baja?», eso no es un detalle.
-- Queda anotado como C-14: cerrarlo pide una columna `zona_horaria` en los agregados.
--
-- El promedio, el mínimo y el máximo **no son reglas clínicas** —así lo dice el propio
-- `agregados.py`—, así que calcularlos aquí no es una cuarta implementación de nada. El TIR
-- sí lo es, y por eso el panel 2 lo lee ya calculado en lugar de rehacerlo en SQL.
--
-- Las atípicas quedan fuera, igual que en los agregados: son artefactos del sensor.
SELECT
  EXTRACT(HOUR FROM (ts_utc AT TIME ZONE zona_horaria))::int AS "Hora local",
  ROUND(AVG(mg_dl)::numeric, 1)                              AS "Promedio",
  ROUND(MIN(mg_dl)::numeric, 1)                              AS "Mínimo",
  ROUND(MAX(mg_dl)::numeric, 1)                              AS "Máximo",
  ROUND(
    PERCENTILE_CONT(0.1) WITHIN GROUP (ORDER BY mg_dl)::numeric, 1
  )                                                          AS "Percentil 10",
  ROUND(
    PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY mg_dl)::numeric, 1
  )                                                          AS "Percentil 90",
  COUNT(DISTINCT usuario_uuid)                               AS "Personas"
FROM serie_limpia
WHERE $__timeFilter(ts_utc)
  AND NOT atipica
GROUP BY 1
ORDER BY 1
