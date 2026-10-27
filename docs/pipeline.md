# Pipeline

La limpieza de la señal del sensor (RF-23), los dos juegos de características (RF-24) y los
agregados. Sale del paso 4 de la fase 2 (`docs/paso-4-postgres-timescale-y-pipeline.md`).

## Cómo se corre

Es una orden, **no un endpoint** (decisión 2.11): el teléfono sube un lote de 500 lecturas en
una ventana de wifi y no tiene por qué esperar a que se recalculen semanas de serie.

```bash
python -m app.pipeline --usuario <uuid> --desde 2026-10-01 --hasta 2026-10-26
python -m app.pipeline --todos --ultimos-dias 7

# En el contenedor:
docker compose exec api python -m app.pipeline --todos --ultimos-dias 7
```

- La base sale de `GLUCY_DATABASE_URL`, igual que en las migraciones. El pipeline no necesita
  el secreto del token.
- Una fecha sin hora (`2026-10-01`) es la medianoche **UTC** de ese día, y `--hasta` no entra
  en el periodo. Para otra frontera, ISO 8601 con offset: `2026-10-01T06:00:00+00:00`.
- Hace falta exactamente uno de `--desde` y `--ultimos-dias`. Sale con `0` si todo fue bien y
  con `2` si la orden está mal escrita.
- **Es idempotente**: correrla dos veces sobre el mismo periodo deja la misma `serie_limpia` y
  los mismos agregados. Un usuario sin lecturas en el periodo no escribe nada y sale con `0`.
- Programarla es de la fase 6. Por ahora se corre a mano.

Cada corrida, por usuario: lee sus lecturas del periodo, las limpia, reemplaza su
`serie_limpia` en el periodo y recalcula sus dos agregados, en una sola transacción.

## 1. Limpieza (RF-23)

`app/services/pipeline/limpieza.py`. Tres operaciones, en este orden, y **solo sobre las
lecturas de origen `sensor`** (decisión 2.8): una lectura manual o de foto es un punto aislado,
y entre dos pinchazos separados por horas cualquier tasa de cambio es posible.

| Caso | Qué pasa |
| --- | --- |
| Tasa de cambio > 4 mg/dL/min contra la última lectura válida | `atipica = true`. **Se marca, no se borra**, y no entra al suavizado, a los agregados ni a las características |
| Hueco de hasta 15 min entre dos lecturas válidas | se rellena cada 5 min por interpolación lineal: `interpolada = true`, `origen = sensor`, la zona de la lectura anterior |
| Hueco de más de 15 min | **no se rellena**. Queda el hueco, y el suavizado se corta ahí en dos tramos |
| Lectura manual o de foto | entra tal cual, con su origen, sin tocar |

Las reglas de tasa y de hueco son las de la referencia: `es_atipica_por_tasa` y
`se_puede_interpolar`, que ya reciben el origen.

Dos detalles:

- En el instante de una atípica **no se interpola**: la atípica no se borra y dos filas no caben
  en el mismo instante. Ese lugar queda sin valor válido y las características lo ven como `NaN`.
- Si dos filas caen en el mismo instante, gana la lectura real sobre la interpolada, y la del
  sensor sobre la manual.

### El filtro: Savitzky-Golay

`app/services/pipeline/filtro.py`, con **ventana 7 y grado 2**: 35 minutos y una parábola. Con
5 minutos de muestreo, una ventana más corta no quita el ruido del sensor y una más larga empieza
a aplanar los picos postprandiales, que son justo lo que el modelo tiene que predecir.

Se escribió con numpy en lugar de meter scipy en la imagen para una función (decisión 2.7). Los
pesos salen de la fila central de la pseudoinversa de Vandermonde, y con ventana 7 y grado 2
son `(−2, 3, 6, 7, 6, 3, −2) / 21`, **los publicados**. En los extremos se ajusta la parábola a
la primera y a la última ventana, como el modo `interp` de scipy.

`scipy.signal.savgol_filter` está en `requirements-dev.txt` como **árbitro**: la prueba 62
compara las dos salidas con 7, 12, 50 y 289 muestras, y coinciden a ~2·10⁻¹³ en el centro y en
los dos extremos.

## 2. Características (RF-24)

`app/services/pipeline/caracteristicas.py`. **Ese módulo es la autoridad sobre los nombres y el
orden**, y `glucy-ml` copia las tuplas (decisión 2.9): si el modelo recibe las columnas en otro
orden, salen números plausibles y equivocados y nada falla.

### Juego denso, para modo sensor

| # | Nombre | Qué es |
| --- | --- | --- |
| 0 | `mg_dl` | la glucosa limpia en el instante |
| 1–5 | `rezago_5` … `rezago_60` | la glucosa 5, 10, 15, 30 y 60 min antes |
| 6 | `derivada_1` | mg/dL por minuto en los últimos 5 min |
| 7 | `derivada_2` | el cambio de la derivada |
| 8–9 | `media_30`, `media_60` | promedio de la última media hora y de la última hora |
| 10 | `cob` | carbohidratos activos, `cob_total` de la referencia |
| 11 | `iob` | insulina activa, `iob` de la referencia, **solo bolo** |
| 12–13 | `hora_sin`, `hora_cos` | la hora local en un círculo: `2π × minutos / 1440` |
| 14 | `dia_semana` | 0 a 6, el lunes es 0, en la zona de la fila |

### Juego disperso, para modo sin sensor

| # | Nombre | Qué es |
| --- | --- | --- |
| 0 | `mg_dl` | la última lectura |
| 1 | `antiguedad_min` | cuántos minutos tiene esa lectura |
| 2 | `carbs_g` | los gramos de la última comida que sigue absorbiéndose |
| 3 | `dosis_ui` | las unidades del último bolo que sigue activo |
| 4–5 | `cob`, `iob` | como en el denso |
| 6–7 | `hora_sin`, `hora_cos` | en la zona de la última lectura |
| 8 | `contexto_comida` | código fijo por valor; «sin contexto» es un código propio |
| 9 | `promedio_7d` | promedio de los últimos siete días |

### Las reglas que van con la lista

- **Lo que falta es `NaN`, nunca cero.** Un rezago que no existe porque la serie empieza ahí no
  es glucosa cero: el modelo trata el `NaN` como información y el cero como un valor.
- **La hora es cíclica** porque a las 23:50 y a las 00:10 la hora cruda está a 23 horas de
  distancia y en realidad son veinte minutos.
- **COB e IOB salen de la referencia.** El COB usa el tiempo de absorción de cada comida (D-8,
  RF-24b); el IOB, la duración de acción del perfil, o 5 h si no hay perfil.
- **No se infiere ninguna comida** (D-9, RF-37). Sin comida registrada, `carbs_g` es `NaN` y el
  COB es 0, porque no hay nada que absorber: no es lo mismo.
- **`contexto_comida`** se codifica así, y cambiar un número obliga a reentrenar:
  `en_ayunas` 0, `antes_de_comer` 1, `dos_horas_despues` 2, `antes_de_dormir` 3, `otro` 4,
  sin contexto 5.

Las características **no se guardan**: se construyen cuando se necesitan, en el entrenamiento y
en `/predict` (paso 5).

### Sin actividad ni sueño (C-10, C-11)

RF-24 pide actividad y sueño en el juego denso, y **no hay de dónde sacarlas**:

1. **Ningún endpoint sube contexto** (C-10).
2. **La app tampoco lo captura**: `EventoContexto.swift` existe en el modelo, pero ninguna
   pantalla ni caso de uso crea uno.
3. **Las escalas no coinciden** (C-11): `EventoContexto.swift` dice 1 a 5; `glucy-ml` usa las de
   OhioT1DM, 1 a 10 para ejercicio y 1 a 3 para sueño, que no se cambian; y en el backend
   `context_events.intensidad` y `.calidad` son texto.

Entrenar con una variable que en producción siempre falta es un desajuste entre entrenamiento y
servicio, peor que no tenerla. OhioT1DM sí trae ejercicio y sueño, así que `glucy-ml` entrena
**con y sin** ellas y reporta la diferencia: eso mide lo que cuesta no capturarlas.

## 3. Agregados

`app/services/pipeline/agregados.py` llena `agregados_horarios` y `agregados_diarios` desde
`serie_limpia`, **con `indicadores()` de la referencia** (decisión 2.6).

- **No son *continuous aggregates***: no existen en la edición Apache 2 de TimescaleDB, y
  calcularían el TIR y el GMI en SQL, una cuarta implementación de las reglas clínicas sin nada
  que la compare con la referencia.
- **`periodo`** es el inicio de la hora o del día **local**, con la zona de cada fila,
  guardado en UTC. Igual que los días de `/stats`.
- Se lee un día de margen a cada lado del periodo y solo se escriben los grupos que **empiezan**
  dentro de él, para que ningún día quede a medias en la frontera.
- Las filas **atípicas no entran**. Las interpoladas sí: son parte de la serie continua.
- El TBR y el TAR usan los umbrales del perfil, o 70 y 180 si no ha llegado.
- **`gmi` queda nulo** en las dos tablas: resume semanas, y una hora o un día no las tienen
  (`gmi_es_fiable`).
- `minimo` y `maximo` son el rango del grupo, no una regla clínica.

### Lo que ahorran, medido

`/stats` sobre el periodo máximo con densidad de sensor —90 días cada 5 minutos, 25 920
lecturas— tarda **600 ms**. Con `agregados_diarios` el mismo periodo son 90 filas. **El paso 4
no cambia `/stats`** (decisión 2.6 bis): los agregados se calculan sobre la serie limpia, y
`/stats` responde hoy sobre las lecturas crudas de todos los orígenes, que no es lo mismo.
Cambiarlo es un paso aparte.
