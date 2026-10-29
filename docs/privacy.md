# Privacidad

Qué dato vive dónde, qué no sale del teléfono y cómo se borra todo.
Sale del punto 19 del reporte.

**El servidor no sabe quién eres.** Lo único que identifica a alguien en el backend, en el
panel y en el Learning Record Store es un UUID que generó el teléfono.

Nunca salen del teléfono: nombre y apellidos, peso, notas de texto libre, fotografías del
glucómetro y de etiquetas, y la caché de productos.

Normatividad aplicable: LFPDPPP y NOM-024-SSA3-2012.

## El panel de seguimiento (fase 6)

Tres decisiones, cada una por un motivo distinto, y las tres con prueba en
`tests/test_tablero.py`:

1. **Detrás de autenticación y nunca en internet abierto.** El puerto se publica en
   `127.0.0.1:3000` y no en `3000:3000`: con lo segundo Docker lo abre en todas las interfaces y
   además atraviesa el cortafuegos del anfitrión sin avisar. Para verlo de fuera, un túnel por
   SSH. Las instantáneas externas de Grafana quedan apagadas, porque por omisión se publican en
   un servidor de Grafana Labs, fuera de este servidor y sin autenticación.
2. **El panel lee con un usuario de solo lectura** (`grafana/lector.sql`), no con el de la
   aplicación. Grafana acepta consultas escritas a mano en su interfaz, y con un usuario que
   puede escribir, un `DELETE` queda a una pulsación. El teléfono es el dueño del dato, pero una
   copia que se borra es una copia perdida.
3. **Ningún panel lleva nombres, y no es por disciplina: el servidor no los tiene.** Una consulta
   que pidiera `nombre`, `peso` o `notas` ni correría, porque esas columnas no existen aquí.

Y la regla de lectura, escrita en el propio tablero y no en un comentario del código: mientras
haya pocas personas detrás, **todo lo que enseña es no concluyente**. Describe a quien está, no a
quien tiene diabetes (riesgo R-2).

## Lo que se guarda de cada explicación

Si contestó el modelo de lenguaje o la plantilla, por qué, cuánto tardó, el horizonte y el modo.
**No el texto de la explicación ni un solo valor de glucosa** (tabla `explicaciones`, C-13).
