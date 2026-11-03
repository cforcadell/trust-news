# Admin

## Description

`api/admin` manages OpenRouter customers, quotas and model recommendations. It also consumes Kafka events of responses to charge consumption to customers according to the invoiced services executed.

## Endpoints

- `GET /ai/openrouter/recommendations`: consult the OpenRouter catalog and return both the general ranking and three alternatives by componente/validator LLM deployed: premium improvement, coste/capacidad comparable option and savings option. For each one calculates its difference against the effective model on an explicit token sample. The optional `max_news_cost_usd` parameter limits the combined LLM cost of each scenario for an estimated five-assertion news; combinations that cannot be met are omitted, including the premium.
- `POST /clients`: creates a quota client.
- `GET /clients`: client list, with optional filters by `status` and partial search by `name`.
- `GET /clients/{client_id}`: recovers quotas, consumption and customer status.
- `PATCH /clients/{client_id}`: Updates data, limits, status or consumption of a client.
- `DELETE /clients/{client_id}`: removes a customer from the quota collection.

## Daemons

- Consumer Kafka `consume_responses_for_quotas`: listen to `TOPIC_RESPONSES` with `group_id=gateway-quota-billing-group`. Processes response events, resolves the `client_id` associated with an order or post, and updates consumption counters in MongoDB for billable services.

## Initialisation

In `startup` opens connection to MongoDB, initializes collections of commands and quotas, creates indexes on `client_id`, `order_id` and `postId`, and launches Kafka consumer quotas in the background. In `shutdown` stops the consumer and closes MongoDB.

## Environment variables

- `MONGO_URI`: MongoDB complete URI. If it does not exist, it is built with `MONGO_APP_*` variables.
- `MONGO_DBNAME`: MongoDB database.
- `ORDERS_COLLECTION`: command collection used to solve customers.
- `QUOTAS_COLLECTION_NAME`: cuotas/clientes. collection
- `KAFKA_BROKER`: Kafka bootstrap server.
- `TOPIC_RESPONSES`: Topic with flow response events.
- `OPENROUTER_MODELS_URL`: OpenRouter model endpoint.
- `OPENROUTER_CHAT_COMPLETIONS_URL`: recommended plugin URL for setting up validators.
- `OPENROUTER_SITE_URL`: referer opcional enviado a OpenRouter.
- `OPENROUTER_APP_TITLE`: Optional title sent to OpenRouter.
