-- Panel 2: tiempo en rango, bajo y alto de la población, por día.
-- Los tres salen de `agregados_diarios`, que el pipeline agrupa por **día local** de cada
-- lectura con la zona que viaja en su fila (regla 5). Contarlos en UTC haría que una lectura
-- de las 19:00 en Monterrey cayera en otro día que en el teléfono.
SELECT
  periodo                          AS time,
  AVG(tir)                         AS "En rango (70-180)",
  AVG(tbr)                         AS "Bajo (< 70)",
  AVG(tar)                         AS "Alto (> 180)"
FROM agregados_diarios
WHERE $__timeFilter(periodo)
GROUP BY periodo
ORDER BY periodo
