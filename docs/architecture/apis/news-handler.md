# News Handler

## Descripción

`api/news-handler` es el orquestador principal del flujo TrustNews. Crea órdenes, persiste su estado en MongoDB, publica solicitudes a Kafka para generar aserciones, subir documentos a IPFS, registrar noticias en blockchain y solicitar validaciones. También consolida las respuestas de esos servicios y expone consultas de órdenes, eventos, validadores y consistencia.

## Endpoints

- `POST /publishNew`: crea una orden nueva para un texto, comprueba cuota `news_generation`, guarda la orden y publica `generate_assertions` en Kafka.
- `POST /publishWithAssertions`: crea una orden con aserciones proporcionadas por el cliente y publica una respuesta sintética `assertions_generated` para continuar el flujo.
- `GET /orders/{order_id}`: devuelve la orden, sus datos enriquecidos, snapshots de validadores y resultados agregados por aserción.
- `GET /news/{order_id}/events`: devuelve los eventos registrados para una orden.
- `GET /news`: lista órdenes/noticias, filtrando por `client_id` salvo en modo admin.
- `GET /validators/cache`: lista el cache de validadores, opcionalmente refrescado desde blockchain/IPFS.
- `GET /validators/cache/{validator_hash}`: devuelve el detalle de configuración de un validador cacheado.
- `GET /validators/cache/{validator_hash}/validations`: devuelve validaciones asociadas a un validador, con filtros por proveedor/modelo y opciones de detalle.
- `POST /find-order-by-text`: calcula el hash del texto y busca órdenes con el mismo `hash_text`.
- `POST /extract_text_from_url`: descarga una URL pública segura, extrae el texto principal del artículo con Readability/BeautifulSoup y devuelve título, URL final y texto.
- `GET /checkOrderConsistency/{order_id}`: ejecuta comprobaciones de consistencia entre Order, documento IPFS y datos del contrato.

## Daemons

- Consumidor Kafka `consume_responses_loop`: escucha `TOPIC_RESPONSES` y `TOPIC_LIGHT_VALIDATION_RESPONSES` con `group_id=fake-news-orchestrator-group`. Procesa acciones como aserciones generadas, subida a IPFS, registro blockchain, solicitudes/completados de validación y eventos de configuración de validadores. Actualiza estado de órdenes, eventos, validaciones y cache de validadores.
- Productor Kafka global: publica solicitudes a tópicos de generación, IPFS, blockchain, validación y validación light según avanza el flujo.

## Inicialización

En `startup` conecta con MongoDB, inicializa colecciones de órdenes, eventos y validaciones, crea índices útiles, carga el cache de validadores desde blockchain/IPFS, arranca el productor Kafka y lanza el consumidor de respuestas. En `shutdown` detiene productor, consumidor y conexión MongoDB.

## Variables de entorno

- `KAFKA_BROKER`, `KAFKA_USERNAME`, `KAFKA_PASSWORD`, `KAFKA_SECURITY_PROTOCOL`, `KAFKA_MECHANISM`: conexión y seguridad Kafka.
- `TOPIC_REQUESTS_GENERATE`: tópico para solicitar generación de aserciones.
- `TOPIC_REQUESTS_IPFS`: tópico para solicitar subida a IPFS.
- `TOPIC_REQUESTS_BLOCKCHAIN`: tópico para solicitar registro en blockchain.
- `TOPIC_REQUESTS_VALIDATE`: tópico legacy/validación.
- `TOPIC_RESPONSES`: tópico principal de respuestas.
- `TOPIC_LIGHT_VALIDATION_REQUESTS`, `TOPIC_LIGHT_VALIDATION_RESPONSES`: tópicos del modo de validación light.
- `MONGO_URI` o variables `MONGO_APP_*`: conexión MongoDB.
- `MONGO_DBNAME`: base de datos.
- `MONGO_COLLECTION`: colección de órdenes.
- `MONGO_EVENTS_COLLECTION`: colección de eventos.
- `MONGO_VALIDATIONS_COLLECTION`: colección de validaciones.
- `MAX_WORKERS`: concurrencia configurable del orquestador.
- `ADMIN_URL`: URL del servicio admin para cuotas.
- `IPFS_FASTAPI_URL`: URL del servicio IPFS.
- `NEWS_CHAIN_URL`: URL del servicio blockchain.
- `GENERATE_ASSERTIONS_URL`: URL del generador de aserciones.
- `IMPORT_URL_TIMEOUT_SECONDS`, `IMPORT_URL_MAX_REDIRECTS`, `IMPORT_URL_MAX_BYTES`, `IMPORT_URL_USER_AGENT`: límites y cabeceras de importación de URLs.
