# El simulador (fase 4)

Un escenario a mano —glucosa, tendencia, hora, una comida, una dosis— y **lo que el sistema
contestaría con él**. Sirve para enseñar el producto sin un sensor pegado al brazo, para probar
un caso raro sin esperar a que ocurra, y para el video de la defensa.

```bash
pip install -r simulador/requirements.txt
GLUCY_JWT_SECRET=cualquiera streamlit run simulador/pantalla.py
```

La variable hace falta solo porque `app.config` se niega a arrancar sin ella. El simulador **no
abre la base de datos ni sale a la red**: todo sale de los controles de la pantalla.

Para que prediga de verdad, se escribe en la barra lateral la misma carpeta de
`GLUCY_RUTA_ARTEFACTO_MODELO`. Sin ella, enseña la línea base de persistencia y lo dice.

## Las dos piezas, y por qué están separadas

| Archivo | Qué hace |
| --- | --- |
| `simulador/escenario.py` | el escenario y su cálculo. **No importa Streamlit.** |
| `simulador/pantalla.py` | controles y gráficas. **No importa ninguna regla.** |

Es la misma regla que en la app: la vista dibuja y recoge gestos, no calcula. Así el simulador
se prueba sin navegador (`tests/test_simulador.py`, 33 pruebas) y la integración continua no
tiene que instalar Streamlit. Hay dos pruebas que vigilan justamente eso: una revisa los
imports de la pantalla y la otra que nadie hable de dosificar.

## Lo que el simulador no inventa

Nada. Ese es el punto. La serie se arma con la pendiente que se pidió y se pasa por el mismo
`limpiar()` del pipeline, el vector lo construye `vector_denso`, el modo lo decide
`modo_actual` de la referencia, la predicción la hace el mismo artefacto que carga la API y la
explicación sale del mismo servicio, con la misma validación. Un simulador que calculara por su
cuenta sería una demostración de sí mismo: enseñaría una curva que el sistema de verdad no
produce.

Hay una prueba que lo fija: arma el vector con el simulador, alimenta el artefacto a mano y
compara. Si algún día el simulador empieza a hacer su propia cuenta, el número deja de
coincidir.

## Las reglas que se ven en la pantalla

- **Sin sensor no hay predicción y se declara** arriba, antes de cualquier cifra (RF-10b, P-04).
  Y una lectura de más de 15 minutos degrada el modo sola (P-03).
- **Lo medido es línea continua y lo estimado punteada**, con color distinto además del trazo.
  No es decoración: es la regla de interfaz que permite distinguirlos a las tres de la mañana.
- **La línea base se llama línea base.** Sin modelo cargado, el simulador enseña la persistencia
  —«dentro de media hora será igual que ahora»— diciendo que no es una predicción. Y no alerta,
  porque repetir el valor de ahora no anticipa nada: comparar contra el umbral diría
  «hipoglucemia» cuando la persona **ya** está baja.
- **Si el modelo se entrenó con datos que no son de OhioT1DM, la pantalla lo marca** y dice que
  esas cifras no van al documento final.
- **Nunca una dosis.** Se registra lo que la persona dice haberse aplicado; no se sugiere nada
  (regla 7).
- Una comida de cero gramos no existe: es que no hubo (D-9, RF-37).

## Dos cosas que solo se vieron corriéndolo

1. **La pantalla no puede llamarse `app.py`.** Streamlit mete la carpeta del script al frente de
   `sys.path`, así que `simulador/app.py` se vuelve el módulo `app` y tapa al paquete `app/` del
   backend. El error que sale, `No module named 'app.services'; 'app' is not a package`, no
   apunta a la causa.
2. **Altair repartía los trazos por orden alfabético.** «Estimado» y «Línea base» van antes que
   «Medido», así que lo medido salía punteado y la estimación continua: exactamente al revés de
   la regla. Ahora el dominio y el rango van escritos a mano.

Las dos tienen su prueba.
