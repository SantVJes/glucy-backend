-- Panel 5: alertas y falsas alarmas por versión del modelo.
--
-- La tasa de falsas alarmas es **criterio de aceptación** del proyecto (≤ 15 %): un modelo que
-- avisa de más se apaga solo, y entonces no avisa el día que importa. Se calcula solo sobre las
-- alertas cuyo desenlace se conoce (`resulto_real IS NOT NULL`): contar las de desenlace
-- desconocido como acertadas bajaría la tasa sin que nada hubiera mejorado.
SELECT
  p.modelo_version                                               AS "Versión",
  COUNT(*)                                                       AS "Alertas",
  COUNT(*) FILTER (WHERE a.resulto_real IS NOT NULL)             AS "Con desenlace conocido",
  COUNT(*) FILTER (WHERE a.resulto_real IS FALSE)                AS "Falsas alarmas",
  ROUND(
    100.0 * COUNT(*) FILTER (WHERE a.resulto_real IS FALSE)
    / NULLIF(COUNT(*) FILTER (WHERE a.resulto_real IS NOT NULL), 0), 1
  )                                                              AS "% falsas (meta <= 15)",
  COUNT(*) FILTER (WHERE a.ts_respuesta IS NOT NULL)             AS "Respondidas",
  ROUND(AVG(
    EXTRACT(EPOCH FROM (a.ts_respuesta - a.ts_emision)) / 60
  ) FILTER (WHERE a.ts_respuesta IS NOT NULL)::numeric, 1)       AS "Minutos medios en responder"
FROM alerts a
JOIN predictions p ON p.uuid = a.prediccion_uuid
WHERE $__timeFilter(a.ts_emision)
GROUP BY 1
ORDER BY 1
