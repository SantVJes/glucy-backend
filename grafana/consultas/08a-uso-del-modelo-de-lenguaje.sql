-- Panel 8a: cuántas explicaciones salieron del modelo y cuántas de la plantilla, por día.
--
-- Es la cifra que hace creíble al componente de IA generativa. La plantilla determinista no es
-- un plan de emergencia: es el piso de la función, y este panel dice cada cuánto se pisa.
SELECT
  date_trunc('day', ts_utc)                        AS time,
  COUNT(*) FILTER (WHERE origen = 'modelo')        AS "Del modelo de lenguaje",
  COUNT(*) FILTER (WHERE origen = 'plantilla')     AS "De la plantilla determinista"
FROM explicaciones
WHERE $__timeFilter(ts_utc)
GROUP BY 1
ORDER BY 1
