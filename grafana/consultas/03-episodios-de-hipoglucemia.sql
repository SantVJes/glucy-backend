-- Panel 3: episodios de hipoglucemia por día, con los nocturnos aparte.
--
-- Un episodio es una **racha** de lecturas por debajo del umbral, y dos rachas separadas por
-- menos de 15 minutos son el mismo episodio: sin eso, una glucosa que oscila alrededor de 70
-- se contaría como seis episodios y el panel diría que la noche fue seis veces peor de lo que
-- fue. Los 15 minutos son la misma constante que usa el pipeline para interpolar huecos.
--
-- Se excluyen las filas interpoladas y las atípicas: una hipoglucemia inventada por una
-- interpolación es la peor clase de dato en este panel, porque es la que más alarma.
--
-- Nocturno es la hora **local** de cada fila, con su propia zona, no la UTC: una hipoglucemia
-- de madrugada es el evento central del proyecto y no puede depender de en qué zona se midió.
WITH bajas AS (
  SELECT
    usuario_uuid,
    ts_utc,
    (ts_utc AT TIME ZONE zona_horaria) AS ts_local,
    ts_utc - LAG(ts_utc) OVER (PARTITION BY usuario_uuid ORDER BY ts_utc) AS hueco
  FROM serie_limpia
  WHERE $__timeFilter(ts_utc)
    AND mg_dl < 70
    AND NOT interpolada
    AND NOT atipica
),
numeradas AS (
  SELECT
    usuario_uuid,
    ts_local,
    SUM(CASE WHEN hueco IS NULL OR hueco > INTERVAL '15 minutes' THEN 1 ELSE 0 END)
      OVER (PARTITION BY usuario_uuid ORDER BY ts_utc) AS episodio
  FROM bajas
),
por_episodio AS (
  SELECT usuario_uuid, episodio, MIN(ts_local) AS inicio
  FROM numeradas
  GROUP BY usuario_uuid, episodio
)
SELECT
  date_trunc('day', inicio) AS time,
  CASE WHEN EXTRACT(HOUR FROM inicio) < 6
       THEN 'Nocturnos (00:00-06:00 local)'
       ELSE 'Diurnos' END   AS metric,
  COUNT(*)                  AS value
FROM por_episodio
GROUP BY 1, 2
ORDER BY 1, 2
