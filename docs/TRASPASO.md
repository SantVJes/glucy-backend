# Traspaso: cómo seguir con glucy-backend sin el contexto de quien lo escribió

Este documento es para quien llegue al proyecto sin haber estado en él, sea una persona u otro
asistente de programación. Junto con `CLAUDE.md` debería bastar para continuar. Hay uno igual
en `glucy-ml-` y otro en `glucy-ios`, cada uno con lo de su repositorio.

Escrito el 20 de noviembre de 2026. Si lees esto mucho después, compara contra el historial de
`develop` antes de dar algo por cierto.

## 1. Antes de tocar nada

- **El trabajo vive en `develop`, no en `main`.** `main` se quedó en la fase 0 y nunca se le
  fusionó `develop`. Clona y cambia de rama: `git checkout develop`.
- **No hay etiquetas ni releases** en este repositorio.
- **`main` no está protegida**, aunque `CLAUDE.md` diga que sí. Es un pendiente (issue abierto).
- La carpeta `glucy-base` que cita `CLAUDE.md` está en los archivos privados del proyecto, no
  en GitHub. No hace falta: lo que importa para el código está en `CLAUDE.md`, en `docs/` y en
  `referencia/reglas_clinicas.py`, que es la **fuente de verdad de los números clínicos** (COB,
  IOB, indicadores, Clarke, métricas). El pipeline, la app y glucy-ml tienen que dar lo mismo.

## 2. Dónde está cada cosa

| Qué | Dónde |
| --- | --- |
| Reglas del proyecto, capas, endpoints, seguridad | `CLAUDE.md` |
| Los endpoints con ejemplos, errores y el sobre de cada uno | `docs/api.md` |
| Tablas y migraciones | `docs/database.md`, `migrations/` |
| Pipeline (limpieza, características, COB, IOB) | `docs/pipeline.md`, `docs/paso-4-*.md` |
| Cómo se construyó cada paso, con sus trampas | `docs/paso-1-*.md` a `docs/paso-4-*.md`, `docs/fase4-*.md`, `docs/fase6-*.md` |
| Simulador en Streamlit (fase 4) | `simulador/`, `docs/simulador.md` |
| Panel de Grafana y Learning Locker (fase 6) | `grafana/`, `docs/panel.md`, `docs/lrs.md`, `docker-compose.lrs.yml` |
| Token de prueba para la app | `scripts/token-de-prueba.py` |

## 3. Estado al 20 de noviembre de 2026

- Los siete endpoints de `CLAUDE.md` existen, más `/perfil` y `/xapi`. `GET /predict` responde
  con mediana de unos 9 ms con el artefacto cargado (presupuesto: 200 ms).
- El servicio de explicación habla con Ollama (Qwen3 8B), valida la respuesta y cae a la
  plantilla determinista si no hay respuesta en 10 s.
- 434 pruebas. Las marcadas `postgres` necesitan una base PostgreSQL 16 con TimescaleDB y la
  integración continua se las salta.
- El servicio de predicción carga **el último manifiesto por orden alfabético** de la carpeta
  `GLUCY_RUTA_ARTEFACTO_MODELO`. Con la carpeta `artifacts/` de glucy-ml eso es hoy
  `m1/m2-v0.3.0-ohiot1dm`, mientras la app trae `v0.2.0-simulador`. El arreglo está en
  glucy-ml (issue allá); aquí no hay que cambiar código, pero conviene saberlo si los números
  del servidor y del teléfono no coinciden.

## 4. Lo que falta

Cada punto tiene su issue en este repositorio.

1. **No hay endpoint que emita ni rote tokens.** Hoy los firma `scripts/token-de-prueba.py` y
   la persona los pega en Ajustes de la app. `CLAUDE.md` pide JWT de corta vigencia con
   rotación; falta el alta del dispositivo y la renovación. Ojo: el servidor solo conoce un
   UUID, nunca nombre ni correo.
2. **La imagen `api` del `docker-compose.yml` no se construye detrás de un proxy con
   certificado propio**, porque `pip` dentro del build no confía en ese certificado. En una
   red normal puede que no pase; si pasa, la salida es pasar el certificado al build o correr
   la API desde el anfitrión con `uvicorn` y levantar en contenedor solo la base.
3. **Proteger `main`** y fusionarle `develop` (lo hace el dueño desde la configuración de
   GitHub).
4. Llenar `docs/architecture.md`, `docs/ai.md` y `docs/testing.md`, que siguen diciendo
   «Pendiente de llenar».

## 5. Trampas que ya costaron horas

- **La fila se arma en el instante de la última lectura, no con el reloj.** Con el reloj,
  casi la mitad de las veces los rezagos caen en la lectura equivocada y el RMSE pasa de 12 a
  125 mg/dL sin que falle nada. `test_106b` lo fija.
- **Las características tienen que coincidir columna por columna con glucy-ml y con
  `VectorDeCaracteristicas.swift` de la app**: mismo nombre, misma ventana, misma hora. El
  pipeline de aquí es la autoridad.
- **El manifiesto de un artefacto se llama `m1-vX.json` y el modelo es su hermano `.ubj`.**
  `metricas` no es todo números: `clarke_reparto` es un diccionario y `sensibilidad_hipo` puede
  ser `null`. Un glob que no encuentra nada no es un error: el cargador lo registra a propósito.
- **Grafana solo lee `provisioning/dashboards` y `provisioning/datasources`**, en inglés. Con
  otro nombre arranca sin tableros y sin decir nada.
- **Learning Locker**: dar de alta el cliente pide cuatro cosas en MongoDB y cada error apunta
  a otro sitio. Está en `docs/lrs.md`.
- **Alembic apaga los registros** de la aplicación al configurar los suyos, y entonces una
  prueba de bitácora pasa por vacía. Está corregido con `disable_existing_loggers=False` en
  `migrations/env.py`; no lo quites.
- Para que el iPhone llegue al servidor en la red local: `uvicorn --host 0.0.0.0`,
  `GLUCY_JWT_MINUTOS_VIGENCIA=1440` (por omisión son 15) y `GLUCY_RUTA_ARTEFACTO_MODELO`
  apuntando a los artefactos, o `/predict` contesta 503. La guía está en
  `glucy-ios/docs/servidor-en-la-red-local.md`.

## 6. Cómo se trabaja

- Todo en español: código, comentarios, commits (Conventional Commits), ramas y PR. Los nombres
  de las tablas no se traducen ni se renombran.
- Un PR por cosa, **siempre contra `develop`, nunca apilado sobre otro PR**. Una vez se
  fusionaron dos PR apilados casi a la vez y un endpoint acabó en una rama que ya nadie usaba.
- Antes de fusionar, la integración continua tiene que terminar en verde. «Cancelado» y
  «saltado» no son verde.
- `ruff check . && ruff format .` antes de subir.

## 7. Aviso

Glucy no es un dispositivo médico certificado. Informa; nunca prescribe ni administra, y jamás
calcula ni sugiere una dosis de insulina.
