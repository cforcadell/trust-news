# Validate Asertions

## Descripción

`api/validate-asertions` implementa un validador automático de aserciones para Assermetry. Puede validar por memoria LLM, búsqueda online o RAG con evidencias, registrar/desregistrar el validador en blockchain, publicar su configuración en IPFS y responder a solicitudes de validación tanto desde eventos blockchain como desde Kafka en modo light.

## Endpoints

- `POST /verificar`: valida directamente una aserción con contexto y devuelve el resultado.
- `GET /tx/status/{tx_hash}`: consulta el estado de una transacción en blockchain.
- `POST /registrar_validador`: sube la configuración del validador a IPFS, registra el validador en el contrato y publica evento de configuración.
- `POST /desregistrar_validador`: marca configuración como baja, actualiza blockchain, desregistra el validador y publica evento.
- `GET /admin/config`: devuelve proveedor, modelo, categorías y configuración runtime del validador. `private_key` y `api_key` se devuelven ofuscados como `********`.
- `PUT /admin/config`: actualiza proveedor/modelo/categorías y permite cambiar `api_url`, `validator_type`, `evidence_search_url`, `evidence_search_use_preferred_domains`, `evidence_search_preferred_profile_id`, `private_key`, `account_address` y `api_key`. Si se envía `private_key` o `api_key` como solo asteriscos, se conserva el valor actual. Refresca configuración IPFS y actualiza blockchain cuando cambia el hash público de configuración.

## Evidencia de decisión

Los validadores que usan búsqueda online o RAG deben devolver evidencia auditable cuando se decantan por `TRUE` o `FALSE`.

- `VALIDATOR_TYPE=2` (`LLM_SEARCH_VALIDATION`) rellena `sources` con enlaces concretos. Cada entrada debe incluir `url`, `title` si está disponible, `evidence_text`, `supports` y `reason`.
- `VALIDATOR_TYPE=3` (`RAG_EVIDENCE_VALIDATION`) rellena `evidence_used` usando exclusivamente las evidencias proporcionadas por `evidence-search`. Cada entrada debe incluir `source_id`, `url`, `evidence_text`, `supports`, `reason` y, cuando exista, `context_id` o `chunk_id`.
- `evidence_text` debe ser el fragmento breve o dato concreto que justifica el veredicto. En RAG debe estar presente literalmente en los contextos aportados al prompt.
- `supports` indica si la evidencia apoya la aserción: `true` si la confirma, `false` si la contradice. No significa “apoya el veredicto”.
- `descripcion`, `reason` y `evidence_text` no deben referirse a fuentes genéricas como “fuente 1”, “CONTEXTO 1” o “las evidencias”; deben mencionar enlaces, dominios o títulos concretos y el fragmento usado.
- Si no hay enlace o fragmento suficiente para confirmar o contradecir la aserción, el validador debe devolver `UNKNOWN`.
- `VALIDATOR_TYPE=1` (`LLM_MEMORY_VALIDATION`) no inventa enlaces; si necesita evidencias externas para decidir, devuelve `UNKNOWN`.

Ejemplo RAG:

```json
{
  "resultado": "TRUE | FALSE | UNKNOWN",
  "descripcion": "Justificación breve basada en URLs y fragmentos concretos",
  "confidence": "HIGH | MEDIUM | LOW",
  "evidence_used": [
    {
      "source_id": "source-1",
      "context_id": "source-1-context-1",
      "chunk_id": "source-1-chunk-3",
      "url": "https://example.org/source",
      "title": "Título de la fuente",
      "supports": true,
      "evidence_text": "Fragmento literal breve usado para decidir",
      "reason": "Por qué el fragmento confirma o contradice la aserción"
    }
  ]
}
```

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
- `VALIDATOR_TYPE=2`: activa validación online; en OpenRouter añade `:online` al modelo en tiempo de petición.
- `VALIDATOR_TYPE=3`: activa integración RAG/evidence-search.
- `EVIDENCE_SEARCH_URL`: URL del servicio evidence-search.
- `EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS`, `EVIDENCE_SEARCH_PREFERRED_PROFILE_ID`, `EVIDENCE_SEARCH_MAX_DOMAINS`, `EVIDENCE_SEARCH_MAX_SOURCES`, `EVIDENCE_SEARCH_MAX_QUERIES_PER_DOMAIN`: política de búsqueda de evidencias.
- `TEMPERATURE`: temperatura del modelo.
- `KAFKA_BROKER` o `KAFKA_BOOTSTRAP`: bootstrap Kafka.
- `KAFKA_USERNAME`, `KAFKA_PASSWORD`, `KAFKA_SECURITY_PROTOCOL`, `KAFKA_MECHANISM`: seguridad Kafka.
- `TOPIC_LIGHT_VALIDATION_REQUESTS`: tópico de solicitudes light.
- `TOPIC_RESPONSES` o `KAFKA_RESPONSE_TOPIC`: tópico de respuestas.
- `IPFS_API_URL`: URL del servicio IPFS usada para leer/subir configuraciones.
