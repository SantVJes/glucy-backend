-- Cabecera del tablero, no uno de los ocho paneles: cuántas personas hay detrás de todo lo
-- que se ve abajo.
--
-- Es la regla que el Documento 2 pide para este tablero: **todo panel con pocos usuarios
-- detrás se marca no concluyente**. Escrito una vez arriba y en grande, para que nadie lea una
-- curva de doce personas como si fuera una población.
SELECT COUNT(DISTINCT usuario_uuid) AS personas
FROM agregados_diarios
WHERE $__timeFilter(periodo)
