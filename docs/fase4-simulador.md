# Fase 4 — el simulador en Streamlit

Qué se construyó, qué se decidió y qué quedó pendiente. El cómo correrlo está en
[`simulador.md`](simulador.md).

## Por qué se pudo construir ahora

El plan dice que la fase 4 depende de la fase 3, y la fase 3 depende de los datos de OhioT1DM,
que todavía no llegan. Pero la dependencia real es más corta de lo que dice la tabla: el
simulador necesita el **pipeline**, el **cargador de artefactos** y el **servicio de
explicación**, y los tres son de la fase 2 y están desde hace semanas. Lo único que la fase 3
aporta es el archivo del modelo, y el simulador funciona sin él: enseña la línea base y lo dice.

Es la misma lectura que permitió cerrar la fase 6 antes que la 3. La tabla de dependencias del
reporte dice de qué fase sale cada pieza, no en qué orden hay que escribirlas.

## Lo que se construyó

```
simulador/
  escenario.py        el escenario y su cálculo. No importa Streamlit.
  pantalla.py         controles y gráficas. No importa ninguna regla.
  requirements.txt    Streamlit, Altair y pandas, aparte de los de la API.
tests/test_simulador.py   33 pruebas, sin navegador
```

El reparto es la decisión principal y es la misma de la app: **la vista no calcula**. Lo que
decide algo vive en `escenario.py`, se prueba sin interfaz y no depende de que Streamlit esté
instalado. Por eso `simulador/requirements.txt` va aparte de `requirements.txt`: ni la imagen de
la API ni la integración continua tienen por qué cargar con Streamlit.

Hay dos pruebas que sostienen el reparto, y no son ceremonia: una revisa que `pantalla.py` no
importe `referencia` ni el pipeline ni el explicador, y otra recorre los dos archivos con el
**mismo validador** que filtra lo que contesta el modelo de lenguaje, buscando un patrón de
dosificación. Si alguna vez aparece uno, se detiene antes de llegar a una pantalla.

## Decisiones

### 1. El simulador no calcula nada por su cuenta

Es lo que lo separa de una maqueta. La serie se arma con la pendiente que se pidió y se pasa por
`limpiar()`; el vector lo construye `vector_denso`; el modo lo decide `modo_actual`; la
predicción la hace el artefacto que carga la API con `cargar()`; la explicación sale de
`explicar()` con su validación puesta. Lo único propio de este módulo es traducir unos controles
a esas entradas.

Un simulador que calculara aparte sería una demostración de sí mismo: enseñaría una curva bonita
que el sistema de verdad no produce, y el día que no coincidieran nadie se enteraría.
`test_33_el_simulador_contesta_lo_mismo_que_el_endpoint` arma el vector con el simulador,
alimenta el artefacto a mano y compara.

### 2. Sin modelo se enseña la línea base, y se llama línea base

Mientras no haya artefacto —que es hoy— el simulador enseña la persistencia: «dentro de media
hora será igual que ahora». Con tres cuidados:

- se dice en pantalla que **no es una predicción**, y de qué horizonte se habla (tener el modelo
  de 30 y no el de 60 es el caso normal mientras se entrena);
- **no alerta**. Comparar el valor de ahora contra el umbral diría «hipoglucemia» cuando la
  persona ya está baja, y eso sería pasar por alerta predictiva lo que es una medición;
- `se_puede_reportar` es falso, así que esa cifra no puede acabar en el documento final.

Esto no contradice la decisión de `GET /predict`, que **no** devuelve una línea base de
respaldo: ahí la cifra iría a la app, donde alguien actuaría sobre ella. Aquí el simulador es una
herramienta de evaluación y la persona que lo mueve sabe lo que está viendo, porque se lo dice la
pantalla.

### 3. El origen de los datos del modelo se enseña

Si el manifiesto dice `sintetico` o `simulador`, la pantalla lo marca con la frase completa:
«estas cifras no van al documento final». Es la continuación de lo que ya avisa el arranque de
la API desde el pull request #11.

### 4. La hora del escenario es hora local, no UTC

`hora_sin` y `hora_cos` entran al modelo. Una bajada de las 03:00 metida como las 09:00 es otra
cosa, y en México son seis horas de diferencia. El control se traduce a un instante real en
`America/Mexico_City` y de ahí a UTC (regla 5).

## Dos fallas que solo aparecieron corriéndolo

Las dos se encontraron abriendo la pantalla en un navegador, no leyendo el código, y las dos
tienen prueba.

1. **`simulador/app.py` no arrancaba.** Streamlit mete la carpeta del script al frente de
   `sys.path`, así que ese archivo se convertía en el módulo `app` y tapaba al paquete `app/`
   del backend. El error, `No module named 'app.services'; 'app' is not a package`, no apunta a
   la causa. Se renombró a `pantalla.py` y se pone la raíz del repositorio en `sys.path` a mano,
   que es lo que obliga al `per-file-ignores` de E402 en `pyproject.toml`.
2. **La gráfica tenía los trazos al revés.** Altair reparte los patrones de línea por orden
   alfabético de la serie, y «Estimado» y «Línea base» van antes que «Medido»: lo medido salía
   punteado y la estimación continua. Es justo la regla de interfaz que el proyecto no puede
   perder —una persona medio dormida tiene que distinguirlas sin leer la leyenda—, y habría
   pasado desapercibida en una revisión de código.

## Contradicción nueva

**C-15 — la plantilla determinista puede contradecirse sola.**
`plantilla_explicacion` de `referencia/reglas_clinicas.py` escribe la dirección comparando el
valor predicho con el actual, y luego enumera las contribuciones SHAP más grandes, que son
relativas a la base del modelo y no al valor actual. Sale, por ejemplo:

> «**Sube** sobre todo por mg_dl (**−29** mg/dL) y por rezago_5 (−4 mg/dL).»

Para quien lo lee, «sube por algo que resta» no se entiende. La plantilla es el **piso** de la
función de explicación —lo que se promete en el reporte que funciona aunque todo lo demás esté
apagado—, así que no puede producir una frase que se contradice.

No se corrige en este pull request a propósito: `reglas_clinicas.py` es la referencia compartida
por los tres repositorios, tiene sus propias pruebas y su copia en la base de documentación.
Cambiar cómo se redacta una explicación que ve el usuario es una decisión aparte, y va en su
propio pull request.

## Lo que queda pendiente

- Correrlo con un modelo entrenado con datos de verdad. Hoy se comprobó con artefactos de
  juguete y con el de contrato de glucy-ml, que está marcado como `sintetico`.
- El escenario es de una comida y una dosis. Varias comidas encadenadas darían un COB más
  parecido a un día real, y el pipeline ya las soporta: es solo interfaz.
- No se ha probado contra Ollama encendido. El camino está (basta escribir la URL en la barra
  lateral) y es el mismo del endpoint, pero aquí no hay un Qwen3 corriendo.
