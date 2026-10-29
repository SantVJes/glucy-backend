-- Panel 7a: sentencias xAPI por día y por verbo.
SELECT
  date_trunc('day', ts_utc) AS time,
  verbo                     AS metric,
  COUNT(*)                  AS value
FROM xapi_events
WHERE $__timeFilter(ts_utc)
GROUP BY 1, 2
ORDER BY 1, 2
