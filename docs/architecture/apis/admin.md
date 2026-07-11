# Admin

## Descripción

`api/admin` gestiona clientes, cuotas y recomendaciones de modelos de OpenRouter. Además consume eventos Kafka de respuestas para imputar consumo a clientes según los servicios facturables ejecutados.

## Endpoints

- `GET /ai/openrouter/recommendations`: consulta modelos de OpenRouter y devuelve una recomendación ordenada por heurística de calidad/precio.
- `POST /clients`: crea un cliente de cuotas.
- `GET /clients`: lista clientes, con filtros opcionales por `status` y búsqueda parcial por `name`.
- `GET /clients/{client_id}`: recupera cuotas, consumo y estado de un cliente.
- `PATCH /clients/{client_id}`: actualiza datos, límites, estado o consumo de un cliente.
- `DELETE /clients/{client_id}`: elimina un cliente de la colección de cuotas.

## Daemons

- Consumidor Kafka `consume_responses_for_quotas`: escucha `TOPIC_RESPONSES` con `group_id=gateway-quota-billing-group`. Procesa eventos de respuesta, resuelve el `client_id` asociado a una orden o post, y actualiza contadores de consumo en MongoDB para los servicios facturables.

## Inicialización

En `startup` abre conexión a MongoDB, inicializa las colecciones de órdenes y cuotas, crea índices sobre `client_id`, `order_id` y `postId`, y lanza el consumidor Kafka de cuotas en segundo plano. En `shutdown` detiene el consumidor y cierra MongoDB.

## Variables de entorno

- `MONGO_URI`: URI completa de MongoDB. Si no existe, se construye con variables `MONGO_APP_*`.
- `MONGO_DBNAME`: base de datos MongoDB.
- `ORDERS_COLLECTION`: colección de órdenes usada para resolver clientes.
- `QUOTAS_COLLECTION_NAME`: colección de cuotas/clientes.
- `KAFKA_BROKER`: bootstrap server de Kafka.
- `TOPIC_RESPONSES`: tópico con eventos de respuesta del flujo.
- `OPENROUTER_MODELS_URL`: endpoint de modelos de OpenRouter.
- `OPENROUTER_CHAT_COMPLETIONS_URL`: URL de completions recomendada para configurar validadores.
- `OPENROUTER_SITE_URL`: referer opcional enviado a OpenRouter.
- `OPENROUTER_APP_TITLE`: título opcional enviado a OpenRouter.
