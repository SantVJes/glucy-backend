-- Panel 4: desempeño del modelo por versión, **contra la línea base de persistencia**.
--
-- El número suelto no dice nada: un RMSE de 18 mg/dL es bueno o malo según con qué se compare.
-- La persistencia —«dentro de 30 minutos será igual que ahora»— es la comparación honesta, y
-- un modelo que no le gana no justifica su existencia. Las dos columnas se calculan sobre
-- **las mismas predicciones**, que es la única forma de que la comparación valga.
--
-- El valor real se busca por tiempo y no por posición, con una tolerancia de 2.5 minutos: la
-- serie trae huecos, y tomar «la fila más cercana que haya» compararía contra un valor de otro
-- momento sin que nada fallara.
WITH comparables AS (
  SELECT
    p.modelo_version,
    p.valor_predicho,
    real.mg_dl   AS valor_real,
    ahora.mg_dl  AS valor_de_ahora
  FROM predictions p
  CROSS JOIN LATERAL (
    SELECT s.mg_dl
    FROM serie_limpia s
    WHERE s.usuario_uuid = p.usuario_uuid
      AND s.ts_utc BETWEEN p.ts_utc + make_interval(mins => p.horizonte_min) - INTERVAL '2.5 minutes'
                       AND p.ts_utc + make_interval(mins => p.horizonte_min) + INTERVAL '2.5 minutes'
    ORDER BY ABS(EXTRACT(EPOCH FROM (s.ts_utc - (p.ts_utc + make_interval(mins => p.horizonte_min)))))
    LIMIT 1
  ) AS real
  CROSS JOIN LATERAL (
    SELECT s.mg_dl
    FROM serie_limpia s
    WHERE s.usuario_uuid = p.usuario_uuid
      AND s.ts_utc BETWEEN p.ts_utc - INTERVAL '2.5 minutes' AND p.ts_utc + INTERVAL '2.5 minutes'
    ORDER BY ABS(EXTRACT(EPOCH FROM (s.ts_utc - p.ts_utc)))
    LIMIT 1
  ) AS ahora
  WHERE $__timeFilter(p.ts_utc)
    AND p.valor_predicho IS NOT NULL
    AND p.modelo_version IS NOT NULL
)
SELECT
  modelo_version                                                        AS "Versión",
  COUNT(*)                                                              AS "Predicciones",
  ROUND(SQRT(AVG(POWER(valor_predicho - valor_real, 2)))::numeric, 1)   AS "RMSE del modelo",
  ROUND(SQRT(AVG(POWER(valor_de_ahora - valor_real, 2)))::numeric, 1)   AS "RMSE de la persistencia",
  ROUND(AVG(ABS(valor_predicho - valor_real))::numeric, 1)              AS "MAE del modelo",
  ROUND(
    100.0 * AVG(ABS(valor_predicho - valor_real) / NULLIF(valor_real, 0))::numeric, 1
  )                                                                     AS "MARD %"
FROM comparables
GROUP BY 1
ORDER BY 1
