# Instalar y comprobar el Learning Record Store

Learning Locker es **software de terceros**. Esta guía es lo que hay que hacer en el servidor
para que las sentencias xAPI de la cola lleguen a algún sitio, y lo que hay que comprobar para
saber que llegaron.

Hasta el **30 de octubre de 2026** este paso estaba sin hacer y el reporte decía, con razón,
que el código hablaba con un LRS que nadie había levantado. Ya se levantó, y lo que sigue es
lo que costó: cuatro cosas en MongoDB, ninguna evidente, cada una con su propio error.

Nada de esto es crítico. Sin LRS, `python -m app.lrs` deja las sentencias en `xapi_events` con
su motivo y las reintenta en la siguiente ventana. Es el comportamiento diseñado, no una
avería.

## 1. Levantarlo

```bash
docker compose -f docker-compose.lrs.yml up -d
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8081/data/xAPI/about   # 200
```

`/data/xAPI/` es el prefijo de Learning Locker y es el que arma `app/services/xapi/lrs.py`:
`GLUCY_LRS_URL` lleva **solo el origen**, sin ruta. Con el compose de este repositorio:

```
GLUCY_LRS_URL=http://127.0.0.1:8081
```

Levantar solo el servicio que recibe sentencias es suficiente. La interfaz web de Learning
Locker es otra pieza; sirve para mirar los datos, no para que entren.

## 2. Dar de alta el cliente, que es la parte que no se adivina

El servicio no tiene pantalla de alta: lee el cliente de la colección `client` de MongoDB. Hay
que insertarlo a mano una vez. **Las cuatro cosas, y el error que da cada una si falta:**

| Qué | Si falta |
| --- | --- |
| `api.basic_key` y `api.basic_secret` | **401**. Son el usuario y la contraseña de `GLUCY_LRS_USUARIO` y `GLUCY_LRS_SECRETO`. |
| `isTrusted: true` | **403** «el LRS no aceptó las credenciales». Con `false` rechaza el cliente aunque la clave esté bien, y el mensaje habla de credenciales: se pierde media hora buscando la contraseña. |
| `authority` **como cadena JSON**, no como objeto | **400** «Expected valid JSON in client.authority». El servicio le aplica `JSON.parse` al campo, así que un objeto de Mongo no sirve. |
| `organisation` con `expiration: null` y una fila en `lrs` | **403** por cliente vencido, o **404** de modelo. El cliente apunta a una organización y a un LRS; si alguno no existe, no hay cliente. |

```bash
docker compose -f docker-compose.lrs.yml exec -T lrs-mongo mongo --quiet learninglocker_v2 --eval '
var org = ObjectId(), lrs = ObjectId();
db.organisations.insertOne({_id: org, name: "Glucy", expiration: null});
db.lrs.insertOne({_id: lrs, title: "Glucy", organisation: org});
db.client.insertOne({
  title: "Glucy backend", lrs_id: lrs, organisation: org,
  scopes: ["all"], isTrusted: true,
  api: {basic_key: "PON_LA_CLAVE", basic_secret: "PON_EL_SECRETO"},
  authority: JSON.stringify({objectType: "Agent", name: "Glucy", mbox: "mailto:CORREO"})
});
'
```

La clave y el secreto se generan aparte y van al `.env`, **nunca a este archivo**:

```bash
python3 -c "import secrets; print(secrets.token_hex(12)); print(secrets.token_hex(16))"
```

## 3. Comprobar que entraron de verdad

Vaciar la cola y contar en MongoDB. Que `python -m app.lrs` no se queje no alcanza: un LRS
puede aceptar un lote y no guardarlo donde se espera.

```bash
python -m app.lrs

docker compose -f docker-compose.lrs.yml exec -T lrs-mongo mongo --quiet learninglocker_v2 \
  --eval 'print(db.statements.countDocuments({}) + " guardadas, " +
                db.statements.distinct("statement.id").length + " ids distintos")'
```

**Los dos números tienen que ser iguales.** Que lo sean es lo que demuestra la idempotencia por
UUID (RF-36c): el `id` de la sentencia es el uuid que generó el teléfono, así que reenviar la
cola tras un corte no duplica nada.

## Lo que quedó comprobado el 30/10/2026

Con Learning Locker levantado en esta misma configuración, usando el armador de sentencias del
repositorio (`app/services/xapi/sentencia.armar`) y su cliente (`lrs.enviar`), sin tocar ni una
línea de los dos:

- **Las ocho sentencias del lote fueron aceptadas**: los **seis verbos** y las **seis
  actividades** del Documento 2, incluidos los tres verbos que no están en el perfil de ADL
  (`completed`, `responded`, `received`) y los `result` con éxito, puntaje y duración ISO 8601.
  Era el riesgo real de este paso: que las sentencias se armaran bien contra un servidor HTTP
  falso y un LRS de verdad las rechazara.
- **El reenvío del mismo lote no creó duplicados**: 8 guardadas, 8 ids distintos. La
  idempotencia por UUID funciona contra una implementación real y no solo por diseño.
- El `authority` que guarda el LRS es el del cliente, no uno que mande Glucy.

Lo que **no** se comprobó, y así va al reporte: la interfaz web de Learning Locker, los
indicadores de autocuidado dibujados sobre datos reales (los paneles 7a y 7b del tablero leen
`xapi_events`, no el LRS), y el respaldo de MongoDB.
