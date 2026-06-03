# Validate Asertions

## Descripción

`api/validate-asertions` implementa un validador automático de aserciones. Puede validar por memoria LLM, búsqueda online o RAG con evidencias, registrar/desregistrar el validador en blockchain, publicar su configuración en IPFS y responder a solicitudes de validación tanto desde eventos blockchain como desde Kafka en modo light.

## Endpoints

- `POST /verificar`: valida directamente una aserción con contexto y devuelve el resultado.
- `GET /tx/status/{tx_hash}`: consulta el estado de una transacción en blockchain.
- `POST /registrar_validador`: sube la configuración del validador a IPFS, registra el validador en el contrato y publica evento de configuración.
- `POST /desregistrar_validador`: marca configuración como baja, actualiza blockchain, desregistra el validador y publica evento.
- `GET /admin/config`: devuelve proveedor, modelo y categorías actuales del validador.
- `PUT /admin/config`: actualiza proveedor/modelo/categorías, refresca configuración IPFS y actualiza blockchain si cambia el hash.

## Daemons

- `BlockchainEventAgent`: escucha eventos `ValidationRequested` del contrato para la cuenta del validador. Recupera el documento desde IPFS, construye el payload de validación, valida la aserción y registra el resultado en blockchain.
- Consumidor Kafka `consume_light_validation_requests`: escucha `TOPIC_LIGHT_VALIDATION_REQUESTS` para validar aserciones en modo light y publicar `LightValidationResponse` en `TOPIC_RESPONSES`.
- Productor Kafka light/configuración: publica respuestas de validación light y eventos de configuración del validador.

## Inicialización

Durante la carga del módulo configura Web3, contrato, proveedor LLM, prompts, categorías y conexión Kafka. En `startup`, si el tipo de validador es automático, arranca el listener de eventos blockchain y el consumidor Kafka light. Después comprueba si la cuenta ya está registrada como validador; si lo está, sincroniza el hash de configuración IPFS si ha cambiado y publica evento de cache. Si no está registrada, intenta registrarla automáticamente con `VALIDATOR_NAME` y `VALIDATOR_CATEGORIES`.

## Variables de entorno

- `LOG_LEVEL`: nivel de logging.
- `RPC_URL`: endpoint RPC Ethereum.
- `PRIVATE_KEY`: clave privada de la cuenta validadora.
- `ACCOUNT_ADDRESS`: dirección del validador.
- `CONTRACT_ADDRESS`: dirección del contrato TrustNews.
- `CONTRACT_ABI_PATH`: ruta al ABI.
- `API_URL`, `API_KEY`, `MODEL`: configuración genérica del proveedor LLM.
- `AI_PROVIDER`: proveedor LLM (`mistral`, `gemini`, `openrouter`, `grok`).
- `LLM_MEMORY_VALIDATION_PROMPT`, `LLM_SEARCH_VALIDATION_PROMPT`, `RAG_EVIDENCE_VALIDATION_PROMPT`: prompts específicos por estrategia.
- `VALIDATOR_NAME`: nombre publicado del validador.
- `VALIDATOR_TYPE`: tipo de validador.
- `VALIDATOR_CATEGORIES`: lista JSON de categorías soportadas.
- `VALIDATOR_ACTIVE_DATE`, `VALIDATOR_UPDATED_DATE`: metadatos temporales de configuración.
- `USE_EVIDENCE_SEARCH`: activa integración RAG/evidence-search.
- `ONLINE_SEARCH_ENABLED`: activa comportamiento de búsqueda online en el prompt/proveedor.
- `EVIDENCE_SEARCH_URL`: URL del servicio evidence-search.
- `EVIDENCE_SEARCH_MAX_RESULTS_PER_DOMAIN`, `EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS`, `EVIDENCE_SEARCH_MAX_DOMAINS`, `EVIDENCE_SEARCH_MAX_SOURCES`, `EVIDENCE_SEARCH_MAX_QUERIES_PER_DOMAIN`: política de búsqueda de evidencias.
- `TEMPERATURE`: temperatura del modelo.
- `KAFKA_BROKER` o `KAFKA_BOOTSTRAP`: bootstrap Kafka.
- `KAFKA_USERNAME`, `KAFKA_PASSWORD`, `KAFKA_SECURITY_PROTOCOL`, `KAFKA_MECHANISM`: seguridad Kafka.
- `TOPIC_LIGHT_VALIDATION_REQUESTS`: tópico de solicitudes light.
- `TOPIC_RESPONSES` o `KAFKA_RESPONSE_TOPIC`: tópico de respuestas.
- `IPFS_API_URL`: URL del servicio IPFS usada para leer/subir configuraciones.
