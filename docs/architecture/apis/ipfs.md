# IPFS

## Descripción

`api/ipfs` encapsula la interacción con un nodo IPFS. Permite subir documentos por HTTP o por Kafka y recuperar contenido por CID.

## Endpoints

- `POST /ipfs/upload`: sube un archivo o bytes de formulario a IPFS y devuelve `cid` y `filename`.
- `GET /ipfs/{cid}`: consulta el contenido de un CID mediante la API `cat` de IPFS.

## Daemons

- Consumidor Kafka `consume_and_process`: escucha `REQUEST_TOPIC` con `group_id=ipfs-agent-group`. Procesa mensajes `upload_ipfs`, serializa el documento, lo sube a IPFS y publica `ipfs_uploaded` en `RESPONSE_TOPIC`.
- Productor Kafka local: publica la respuesta con el CID generado.

## Inicialización

Carga `.env`, configura logging, URLs IPFS y tópicos Kafka. En `startup` lanza el consumidor Kafka en segundo plano. El consumidor reintenta la conexión a Kafka hasta `MAX_RETRIES` con espera `RETRY_DELAY`.

## Variables de entorno

- `LOG_LEVEL`: nivel de logging.
- El formato de salida es JSON de una sola línea y es común al resto de servicios Python.
- `KAFKA_BOOTSTRAP`: bootstrap Kafka.
- `KAFKA_REQUEST_TOPIC`: tópico de solicitudes de subida IPFS.
- `KAFKA_RESPONSE_TOPIC`: tópico de respuestas.
- `IPFS_API_ADD`: URL del endpoint IPFS `/api/v0/add`.
- `IPFS_API_CAT`: URL del endpoint IPFS `/api/v0/cat`.

Constantes internas:

- `MAX_RETRIES`: número de reintentos de conexión Kafka.
- `RETRY_DELAY`: espera entre reintentos.
