-- Panel 6a: qué hay en la cuarentena, por tabla y por motivo.
-- RF-22 obliga a conservar lo rechazado con su motivo, y este panel es para qué sirve: un
-- motivo que se repite mil veces es un error de la app, no mil datos malos.
SELECT
  tabla_destino     AS "Tabla",
  motivo_rechazo    AS "Motivo",
  COUNT(*)          AS "Renglones",
  MAX(ts_recepcion) AS "El más reciente"
FROM cuarentena
WHERE $__timeFilter(ts_recepcion)
GROUP BY 1, 2
ORDER BY 3 DESC
