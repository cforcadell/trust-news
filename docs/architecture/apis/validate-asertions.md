# Validate Asertions

## Description

`api/validate-asertions` implements an automatic assertion validator for Assermetry. It can validate by LLM memory, online search or RAG with evidence, registrar/desregistrar the blockchain validator, publish its configuration in IPFS and respond to validation requests both from blockchain events and from Kafka in light mode.

## Endpoints

- `POST /verificar`: directly validates a contexted assertion and returns the result.
- `GET /tx/status/{tx_hash}`: Consult the status of a blockchain transaction.
- `POST /registrar_validador`: uploads the validation configuration to IPFS, registers the validator in the contract and publications configuration event.
- `POST /desregistrar_validador`: Sets settings as low, updates blockchain, unregisters the validator and publish events.
- `GET /admin/config`: devuelve proveedor, modelo, categorías y configuración runtime del validador. `private_key` y `api_key` se devuelven ofuscados como `********`.
- `PUT /admin/config`: actualiza proveedor/modelo/categorías y permite cambiar `api_url`, `validator_type`, `evidence_search_url`, `evidence_search_strategy`, `private_key`, `account_address` y `api_key`. Si se envía `private_key` o `api_key` como solo asteriscos, se conserva el valor actual. Refresca configuración IPFS y actualiza blockchain cuando cambia el hash público de configuración.

## Evidence of decision

Only RAG validators produce documentary evidence that is verifiable by Assermetry.

The orchestration of dependencies is explicit: MEMORY and SEARCH call only `common/llm`; SEARCH activates the provider's own search. RAG with a `EXT_*` strategy calls Evidence Search directly; RAG with `LOCAL` calls Source Router first and passes `preferred_sources` with all its metadata to Evidence Search. LIGHT and BLOCKCHAIN reuse the same function.

- `VALIDATOR_TYPE=2` (`LLM_SEARCH_VALIDATION`) delegates the search to the provider. You can return `TRUE`, `FALSE` or `UNKNOWN` without sources. Optional links are published in `sources_declared` and labeled `PROVIDER_SEARCH_UNVERIFIED`; they are not converted to `evidence_used` because the server does not have the corpus consulted to check them.
- `VALIDATOR_TYPE=3` (`RAG_EVIDENCE_VALIDATION`) allows the model to select exclusively `context_id` citations provided by `evidence-search`. The model only returns `context_id`, `supports` and `reason`.
- The server solves the identifier and builds `evidence_used` with `source_id`, URL, title, `chunk_id`, canonical text and hash. The free URL, title or citation values sent by the model are ignored.
- `supports` indicates whether the evidence supports the assertion: `true` if it confirms it, `false` if it contradicts it. It does not mean “support the verdict.”
- `descripcion`, `reason` and `evidence_text` should not refer to generic sources such as “source 1”, “CONTEXT 1” or “evidence”; they should mention links, domain or specific titles and the fragmentation used.
- The online validator returns `UNKNOWN` when the provider does not have sufficient information; the absence of declared sources does not in itself invalidate his non-documentary vote.
- `VALIDATOR_TYPE=1` (`LLM_MEMORY_VALIDATION`) does not invent links; if you need external evidence to decide, returns `UNKNOWN`.

Example RAG:

```json
{
  "resultado": "TRUE | FALSE | UNKNOWN",
  "descripcion": "Justificación breve basada en URLs y fragmentos concretos",
  "confidence": "HIGH | MEDIUM | LOW",
  "evidence_used": [
    {
      "context_id": "source-1-context-1",
      "supports": true,
      "reason": "Por qué el fragmento confirma o contradice la aserción"
    }
  ]
}
```

After validating the reference, the server persists a canonical input such as:

```json
{
  "source_id": "source-1",
  "context_id": "source-1-context-1",
  "chunk_id": "source-1-chunk-3",
  "url": "https://example.org/source",
  "title": "Título de la fuente",
  "supports": true,
  "evidence_text": "Contexto recuperado por el servidor",
  "evidence_text_sha256": "...",
  "reason": "Por qué el contexto confirma la aserción"
}
```

## Daemons

- `BlockchainEventAgent`: listen to `ValidationRequested` events from the contract for the validator account. Recover the document from IPFS, build the validation payload, validate the assertion and record the result in blockchain.
- Consumer Kafka `consume_light_validation_requests`: listen `TOPIC_LIGHT_VALIDATION_REQUESTS` to validate light mode assertions and publish `LightValidationResponse` in `TOPIC_RESPONSES`.
- Kafka light/configuracion: publisher light validation responses and validation configuration events.

## Initialisation

During the module load, configure Web3, contract, LLM provider, prompts, categories and Kafka connection. In `startup`, if the validator type is automatic, start the blockchain event lister and the Kafka light consumer. Then check if the account is already registered as a validator; if it is, sync the IPFS configuration hash if it has changed and publishes cache event. If it is not registered, try to register it automatically with `VALIDATOR_NAME` and `VALIDATOR_CATEGORIES`.

## Environment variables

- `LOG_LEVEL`: logging level.
- `RPC_URL`: endpoint RPC Ethereum.
- `PRIVATE_KEY`: clave privada de la cuenta validadora.
- `ACCOUNT_ADDRESS`: Validator address.
- `CONTRACT_ADDRESS`: address of TrustNews contract.
- `CONTRACT_ABI_PATH`: route to ABI.
- `API_URL`, `API_KEY`, `MODEL`: configuración genérica del proveedor LLM.
- `AI_PROVIDER`: LLM supplier (`mistral`, `gemini`, `openrouter`, `grok`).
- `LLM_MEMORY_VALIDATION_PROMPT`, `LLM_SEARCH_VALIDATION_PROMPT`, `RAG_EVIDENCE_VALIDATION_PROMPT`: specific proposals per strategy.
- `VALIDATOR_NAME`: Name of the validator published.
- `VALIDATOR_TYPE`: type of validator.
- `VALIDATOR_CATEGORIES`: JSON list of supported categories.
- `VALIDATOR_ACTIVE_DATE`, `VALIDATOR_UPDATED_DATE`: temporary configuration metadata.
- `VALIDATOR_TYPE=2`: active online validation; in OpenRouter adds `:online` to the model at request time.
- `VALIDATOR_TYPE=3`: active RAG/evidence-search. integration
- `EVIDENCE_SEARCH_URL`: URL of the evidence-search service.
- `SOURCE_ROUTER_URL`: Internal URL used exclusively in `RAG + LOCAL`.
- `EVIDENCE_SEARCH_STRATEGY`: mandatory strategy for type 3: `LOCAL`, `EXT_OFFICIAL_FIRST` or `EXT_ONLY_OFFICIAL`.
- `EVIDENCE_SEARCH_MAX_DOMAINS`, `EVIDENCE_SEARCH_MAX_SOURCES`, `EVIDENCE_SEARCH_MAX_QUERIES`: limits of evidence search.
- `TEMPERATURE`: model temperature.
- `KAFKA_BROKER` or `KAFKA_BOOTSTRAP`: bootstrap Kafka.
- `KAFKA_USERNAME`, `KAFKA_PASSWORD`, `KAFKA_SECURITY_PROTOCOL`, `KAFKA_MECHANISM`: Kafka security.
- `TOPIC_LIGHT_VALIDATION_REQUESTS`: topic of light requests.
- `TOPIC_RESPONSES` or `KAFKA_RESPONSE_TOPIC`: topic of answers.
- `IPFS_API_URL`: URL of IPFS service used for leer/subir configurations.
