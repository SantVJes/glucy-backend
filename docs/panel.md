# Panel de seguimiento

Los ocho paneles del §10 del Documento 2, en Grafana, leyendo la misma base que la API.
Sale del punto 15 del reporte.

## Cómo se levanta

```bash
cp .env.example .env            # y llenar; .env está en .gitignore
docker compose up -d            # base, api y panel

# Una vez, cuando la base ya esté migrada: el usuario de SOLO LECTURA del panel.
docker compose exec -T base psql -U "$POSTGRES_USER" -d glucy \
  -v usuario="$GLUCY_GRAFANA_DB_USUARIO" -v secreto="$GLUCY_GRAFANA_DB_SECRETO" \
  -f - < grafana/lector.sql

docker compose restart panel    # para que el origen de datos tome al usuario nuevo
```

El panel queda en **`http://127.0.0.1:3000`**, solo desde el propio servidor. Para verlo desde
otra máquina, un túnel:

```bash
ssh -L 3000:127.0.0.1:3000 <servidor>   # y abrir http://localhost:3000 en la máquina de uno
```

No se publica en internet abierto, y eso no es prudencia de más: aunque los datos estén
seudonimizados siguen siendo datos de salud.

## Qué hay dentro

| # | Panel | De dónde lee |
| --- | --- | --- |
| 1 | Glucosa por hora del día (hora **local**) | `serie_limpia` |
| 2 | Tiempo en rango, bajo y alto | `agregados_diarios` |
| 3 | Episodios de hipoglucemia, los nocturnos aparte | `serie_limpia` |
| 4 | Desempeño del modelo contra la persistencia | `predictions` + `serie_limpia` |
| 5 | Alertas y falsas alarmas por versión | `alerts` + `predictions` |
| 6 | Salud de la sincronización: cuarentena y cola del LRS | `cuarentena`, `xapi_events` |
| 7 | Indicadores de aprendizaje | `xapi_events` |
| 8 | Uso del modelo de lenguaje | `explicaciones` |

Los paneles 6, 7 y 8 se parten en dos consultas cada uno, así que son doce archivos en
`grafana/consultas/` más la cabecera que cuenta a las personas.

## El tablero es código, no se edita a mano

El JSON de `grafana/tableros/glucy.json` **se genera** desde los `.sql`:

```bash
python grafana/armar_tablero.py          # reescribe el JSON
python grafana/armar_tablero.py --ver    # solo dice si está al día (lo corre la CI)
```

Por qué así: el JSON de Grafana es largo y lleno de campos que no significan nada, y la
consulta es lo único que importa de cada panel. En un archivo `.sql` se lee, se corre contra la
base y se revisa en un pull request; pegada dentro del JSON con los saltos de línea escapados,
no se puede hacer ninguna de las tres cosas. Y `allowUiUpdates: false` en el aprovisionamiento,
porque un tablero editado en la interfaz se pierde con el contenedor y nadie se acuerda de qué
decía el panel.

## Cómo se lee, y esto va en el reporte

Mientras haya pocas personas detrás, **todo lo que enseña el tablero es no concluyente**:
describe a quien está usando Glucy, no a quien tiene diabetes (riesgo R-2). El aviso está en el
tablero mismo, arriba y en grande, no en un comentario del código, y hay una prueba que lo fija.

Dos salvedades que conviene saber antes de citar un número de aquí:

- **El panel 1 lee la hora local de cada fila** con su propia zona, no la de los agregados.
  `agregados_horarios.periodo` guarda el inicio de la hora local **convertido a UTC** y la tabla
  no tiene columna de zona, así que de ahí saldría la hora UTC: en México, la curva corrida seis
  horas, con la bajada de las 03:00 apareciendo a las 09:00. Es **C-14**.
- **El panel 2 agrupa por el instante del día local.** Con todas las personas en la misma zona
  es un punto por día, que es el caso real. Con zonas distintas, un mismo día de calendario
  aparece como puntos separados; cerrarlo pide la misma columna `zona_horaria` en los agregados.
