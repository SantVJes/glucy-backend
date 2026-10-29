-- Panel 6b: salud de la cola hacia el Learning Record Store.
--
-- «Pendiente» es exactamente «sin enviar y sin rechazar» (C-12). Lo que hay que mirar no es el
-- número de pendientes, que sube y baja, sino **la más antigua**: una cola que se vacía con
-- tres días de retraso funciona y a la vez está mal, y es lo único que delata un LRS que lleva
-- apagado desde el martes.
SELECT
  COUNT(*) FILTER (WHERE enviado_ts IS NULL AND motivo_rechazo IS NULL)  AS "Pendientes",
  COUNT(*) FILTER (WHERE enviado_ts IS NOT NULL)                         AS "Enviadas",
  COUNT(*) FILTER (WHERE motivo_rechazo IS NOT NULL)                     AS "Rechazadas",
  MIN(ts_utc) FILTER (WHERE enviado_ts IS NULL AND motivo_rechazo IS NULL)
                                                                         AS "La pendiente más antigua",
  ROUND(AVG(
    EXTRACT(EPOCH FROM (enviado_ts - ts_utc)) / 60
  ) FILTER (WHERE enviado_ts IS NOT NULL)::numeric, 1)                   AS "Minutos medios en salir",
  ROUND(AVG(intentos)::numeric, 2)                                       AS "Intentos medios"
FROM xapi_events
WHERE $__timeFilter(ts_utc)
