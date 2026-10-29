-- Panel 7b: los dos indicadores que de verdad dicen algo de autocuidado.
--
-- Contar sentencias por verbo es un número de actividad; lo que importa es la **proporción**:
-- de los avisos que recibió, a cuántos respondió, y de los módulos que abrió, cuántos terminó.
-- Esas dos son las que van al reporte.
SELECT
  COUNT(*) FILTER (WHERE verbo = 'received')   AS "Avisos recibidos",
  COUNT(*) FILTER (WHERE verbo = 'responded')  AS "Avisos respondidos",
  ROUND(
    100.0 * COUNT(*) FILTER (WHERE verbo = 'responded')
    / NULLIF(COUNT(*) FILTER (WHERE verbo = 'received'), 0), 1
  )                                            AS "% de respuesta",
  COUNT(*) FILTER (WHERE verbo = 'launched')   AS "Módulos abiertos",
  COUNT(*) FILTER (WHERE verbo = 'completed')  AS "Módulos terminados",
  ROUND(
    100.0 * COUNT(*) FILTER (WHERE verbo = 'completed')
    / NULLIF(COUNT(*) FILTER (WHERE verbo = 'launched'), 0), 1
  )                                            AS "% terminados",
  COUNT(*) FILTER (WHERE verbo = 'answered')   AS "Evaluaciones contestadas"
FROM xapi_events
WHERE $__timeFilter(ts_utc)
