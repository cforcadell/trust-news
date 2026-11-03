# News Handler

## Description

`api/news-handler` is the main conductor of the Assermetry flow. It creates orders, persists its status in MongoDB, publishes requests to Kafka to generate assertions, upload documents to IPFS, register news on blockchain and request validations. It also consolidates the responses of those services and exposes queries of commands, events, validators and consistency.

## Endpoints

- `POST /publishNew`: creates a new command for a text, checks `news_generation` quota, saves the command and publishes `generate_assertions` in Kafka.
- `POST /publishWithAssertions`: creates an order with customer-provided assertions and publishes a synthetic `assertions_generated` response to continue the flow.
- `GET /orders/{order_id}`: returns the command, its enriched data, validation snapshots and results added by assertion.
- `GET /news/{order_id}/events`: returns the events registered for a command.
- `GET /news`: lists commands/news, filtering by `client_id` except in admin mode.
- `GET /validators/cache`: Check the validator cache, optionally refreshed from blockchain/IPFS.
- `GET /validators/cache/{validator_hash}`: returns the configuration detail of a cached validator.
- `GET /validators/cache/{validator_hash}/validations`: returns validations associated with a validator, with proveedor/modelo filters and detail options.
- `POST /find-order-by-text`: calculates the text hash and searches for commands with the same `hash_text`.
- `POST /extract_text_from_url`: download a secure public URL, extract the main text of the article with Readability/BeautifulSoup and return title, final URL and text.
- `GET /checkOrderConsistency/{order_id}`: performs consistency checks between Order, IPFS document and contract details.

## Daemons

- Consumer Kafka `consume_responses_loop`: listen `TOPIC_RESPONSES` and `TOPIC_LIGHT_VALIDATION_RESPONSES` with `group_id=fake-news-orchestrator-group`. Processes actions such as generated assertions, upload to IPFS, blockchain log, solicitudes/completados validation and validation configuration events. Updates command status, events, validations and cache of validators.
- Global Kafka Producer: publishes applications to generation topics, IPFS, blockchain, validation and light validation as the flow progresses.

## Initialisation

In `startup` connects to MongoDB, initializes collections of commands, events and validations, creates pay indexes, loads the cache of validators from blockchain/IPFS, starts the producer Kafka and launches the consumer responses. In `shutdown` stops producer, consumer and MongoDB connection.

## Environment variables

- `KAFKA_BROKER`, `KAFKA_USERNAME`, `KAFKA_PASSWORD`, `KAFKA_SECURITY_PROTOCOL`, `KAFKA_MECHANISM`: Kafka connection and security.
- `TOPIC_REQUESTS_GENERATE`: Topic to request generation of assertions.
- `TOPIC_REQUESTS_IPFS`: Topic to request IPFS upload.
- `TOPIC_REQUESTS_BLOCKCHAIN`: Topical for blockchain registration.
- `TOPIC_REQUESTS_VALIDATE`: legacy/validacion topic.
- `TOPIC_RESPONSES`: main topic of answers.
- `TOPIC_LIGHT_VALIDATION_REQUESTS`, `TOPIC_LIGHT_VALIDATION_RESPONSES`: topics of light validation mode.
- `MONGO_URI` or `MONGO_APP_*` variables: MongoDB connection.
- `MONGO_DBNAME`: database.
- `MONGO_COLLECTION`: command collection.
- `MONGO_EVENTS_COLLECTION`: Event collection.
- `MONGO_VALIDATIONS_COLLECTION`: validation collection.
- `MAX_WORKERS`: configurable orchestrator attendance.
- `ADMIN_URL`: URL of the admin service for installments.
- `IPFS_FASTAPI_URL`: IPFS service URL.
- `NEWS_CHAIN_URL`: URL of the blockchain service.
- `GENERATE_ASSERTIONS_URL`: URL of the assertion generator.
- `IMPORT_URL_TIMEOUT_SECONDS`, `IMPORT_URL_MAX_REDIRECTS`, `IMPORT_URL_MAX_BYTES`, `IMPORT_URL_USER_AGENT`: URL import boundaries and headers.
