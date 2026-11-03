# Annex: Kafka courier and cases of use Assermetry

## General Vision

Assermetry uses Kafka as an asynchronic bus between microservices. The main pattern is:

1. news-handler creates an order and publishes a petition.
2. A specialized microservice consumes that request.
3. The microservice publishes a response or event.
4. news-handler consumes responses, updates MongoDB and advances the order status.

The main order collection is maintained in MongoDB, usually orders. Events are also recorded in events for traceability.

## Services involved

| Service | Rol |
|---|---|
| news-handler | Main Orchestrator, API consumed by frontend/gateway, command status, validator cache |
| generate-asertions | Generates assertions from text |
| ipfs-fastapi | Upload and read documents from IPFS |
| news-chain | Integrates smart contract and listens to blockchain events |
| validate-asertions | Validator validation worker |
| evidence-search | Internal HTTP service for RAG evidence; does not consume Kafka |
| admin | Assessments and model recommendations |

## Topics principales

Names can be set by environment, but the usual values are:

| Topic | Productor | Consumidor | Main messages |
|---|---|---|---|
| fake_news_requests_generate | news-handler | generate-asertions | generate_assertions |
| fake_news_requests_ipfs | news-handler | ipfs-fastapi | upload_ipfs |
| fake_news_requests_blockchain | news-handler | news-chain | register_blockchain |
| fake_news_requests_validate | news-chain or inherited flow | validate-asertions/orquestacion heredada | request_validation |
| fake_news_requests_light_validation | news-handler | validate-asertions | light_validation_request |
| fake_news_responses | All workers | news-handler | responses and events |

Note: in code there are historical faults trustnews.validation.requests and trustnews.validation.responses, but the current ConfigMaps point the flow light to fake_news_requests_light_validation and fake_news_responses.

## Acciones Kafka normalizadas

### generate_assertions

Posted by news-handler a fake_news_requests_generate.

Payload conceptual:

{ "action": "generate_assertions", "order_id": "uuid", "payload": { "text": "texto de la noticia", "validation_mode": "BLOCKCHAIN | LIGHT" } }

Expected response:

{
  "action": "assertions_generated",
  "order_id": "uuid",
  "payload": {
    "text": "texto original",
    "assertions": [
      {
        "idAssertion": "1",
        "text": "asercion factual",
        "categoryId": 1
      }
    ],
    "publisher": "generate-asertions",
    "validation_mode": "BLOCKCHAIN | LIGHT",
    "assertions_document": {
      "schema_version": "assertions-document-v2",
      "assertions": []
    }
  }
}

If failed, statements_not_generated is published with error and number of attempts.

## Use case 1: normal publication with blockchain

Objective: to publish a news story, generate assertions, upload document to IPFS, register post in blockchain and request automatic validations.

Flow:

1. Cliente llama a news-handler, normalmente POST /publishNew.
2. news-handler creates order in MongoDB with initial status.
3. news-handler publishes generation_assertions in fake_news_requests_generate.
4. generate-assertions consumes, generates assertions and publishes assertions_generated in fake_news_responses.
5. news-handler consume assertions_generated.
6. If validation_mode=BLOCKCHAIN, valida/normaliza statements-document-v2 and publishes upload_ipfs in fake_news_requests_ipfs.
7. ipfs-fastapi uploads document to IPFS and responds ipfs_uploaded.
8. news-handler consumes ipfs_uploaded, saves cid and publishes register_blockchain in fake_news_requests_blockchain.
9. news-chain records the post in the contract. The contract selects validators by category.
10. news-chain publishes blockchain_registered in fake_news_responses.
11. news-handler saves postId, tx_hash, assertions, validations expected by assertion and validators_pending.
12. The contract issues ValidationRequested for each validador/asercion.
13. Each validation-aserstions instance listens to blockchain events filtered by its ACCOUNT_ADDRESS.
14. If VALIDATOR_TYPE is automatic, it validates the assertion: type 1 memory, type 2 online, type 3 RAG.
15. validate-aserstions uploads validation document to IPFS and registers validation in blockchain.
16. news-chain detects or consumes validation and publishes validation_completed.
17. news-handler consumes validation_completed, updates validations, recalculates pending and, if it all ends, marks status=VALIDATED.
18. The order endpoint returns assertion_results with weighted scores.

## Use case 2: LIGHT validation without blockchain/IPFS

Objective: to validate assertions quickly using Kafka, without registering news or validations in blockchain.

Flow:

1. Client publishes with validation_mode=LIGHT.
2. Assertions are generated as in normal flow.
3. news-handler detects validation_mode=LIGHT upon receiving assertions_generated.
4. No envia a IPFS ni blockchain.
5. Create local document and calculate active validators from validators_cache by on-chain category.
6. Non-automatic validators filter: excludes DETERMINISTIC_VALIDATION and HUMAN.
7. Post a message by asercion/validador in fake_news_requests_light_validation with action=light_validation_request and assertion-validation-payload-v2 online.
8. Each worker validate-asers consumes the topic, but only processes messages whose validater_id matches your ACCOUNT_ADDRESS.
9. The worker validates according to VALIDATOR_TYPE and publishes light_validation_completed in fake_news_responses.
10. news-handler saves validation in order and in validations collection.
11. When no outstanding, mark the command as VALIDATED.

Payload conceptual de light_validation_request:

{
  "action": "light_validation_request",
  "order_id": "uuid",
  "payload": {
    "validation_mode": "LIGHT",
    "assertion_index": 0,
    "idAssertion": "1",
    "assertion_text": "asercion",
    "categoryId": 1,
    "validator_id": "0x...",
    "original_text": "texto completo",
    "correlation_id": "order:assertion:validator"
  }
}

Concept answer light_validation_completed:

{
  "action": "light_validation_completed",
  "order_id": "uuid",
  "payload": {
    "validation_mode": "LIGHT",
    "assertion_index": 0,
    "idAssertion": "1",
    "validator_id": "0x...",
    "categoryId": 1,
    "verdict": 1,
    "description": "...",
    "confidence": "HIGH",
    "sources": [],
    "sources_declared": [],
    "evidence_used": [],
    "evidence_validation": {
      "status": "UNVERIFIED | VERIFIED | UNSUPPORTED | NOT_APPLICABLE",
      "basis": "PROVIDER_SEARCH_UNVERIFIED | RETRIEVED_EVIDENCE | MODEL_KNOWLEDGE"
    },
    "correlation_id": "order:assertion:validator",
    "error": null
  }
}

## Use case 3: RAG validator with evidence-search

Objective: to validate an assertion using external evidence managed by Assermetry, not by the LLM provider.

Worker Configuration:

- VALIDATOR_TYPE: "3"
- EVIDENCE_SEARCH_URL: "http://evidence-search.apis.svc.cluster.local:8074"

Flow:

1. The worker receives a request for validation by blockchain event or Kafka light.
2. For `LOCAL`, run `POST /routes/resolve` on Source Router; `EXT_*` strategies omit this step.
3. Source Router consults `source_routes_v2` and `domain_profiles_v1`; in MISSING/STALE discovers real URLs, ranks in a LLM batch and applies elegibilidad/ranking in code.
4. The worker runs `POST /search/evidence`; with `LOCAL` attached `preferred_sources[]` complete.
5. Evidence Search query Exa/Tavily and build evidencia/chunks; does not know path memory.
6. The worker injects the evidence into the RAG prompt by `common/llm`.
7. The LLM must respond using those evidence only.
8. The answer may include confidence and evidence_used.
9. news-handler keeps those fields and frontend shows them.

## Use case 4: Validator online via OpenRouter

Objective: to use a model with online search of the supplier.

Configuration:

- VALIDATOR_TYPE: "2"
- AI_PROVIDER: "openrouter"
- MODEL: "openai/gpt-5-mini"

Comportamiento:

- The worker does not call evidence-search; the online search is derived from `VALIDATOR_TYPE=2`.
- For OpenRouter, send the model with suffix :online.
- The prompt asks to search for current information; it does not require sources because Assermetry does not receive the supplier's private corpus.
- The vote is retained with `basis=PROVIDER_SEARCH_UNVERIFIED`.
- Optional links are published as `sources_declared`; never as `evidence_used`.

## Use case 5: human or deterministic validator

Objective: to register validators that should not yet participate in automatic validation.

Deterministic configuration:

- VALIDATOR_TYPE: "4"
- AI_PROVIDER: "none"

Human configuration:

- VALIDATOR_TYPE: "5"
- AI_PROVIDER: "none"

Comportamiento:

- They're registered against smart contract.
- They post or update cache validator config.
- They don't raise automatic validation listeners.
- No consumen Kafka light.
- No llaman LLM.
- No llaman evidence-search.

## Validator configuration events

When a validator is registered, updates config or bootes, validate-aserstions publishes new_validator_config in fake_news_responses.

Payload conceptual:

{
  "action": "new_validator_config",
  "order_id": "",
  "payload": {
    "validator": "0x...",
    "ipfs_hash": "Qm...",
    "config": {
      "name": "...",
      "type": 3,
      "provider": "openrouter",
      "model": "...",
      "status": 1
    },
    "categories": [1, 2],
    "source": "startup_existing",
    "timestamp": "ISO-8601"
  }
}

news-handler consumes this event and updates validators_cache.

The cache adds operating fields that are not part of IPFS:

{
  "validator_type": 3,
  "reputation": 1.0,
  "metrics_reset_at": null
}

## Result calculation after validation messages

Each time newshandler returns an order, attach assertion_results.

For each assertion:

1. Lee validaciones completadas.
2. It gets type and reputation from validation_config or cache.
3. Calcula effective_weight = validator_type_weight * reputation.
4. Group by normalized result.
5. Calculate score_result = sum(effective_weight of the result) / num_validators.
6. The winner is the result with the highest score.

Example:

| Validator | Tipo | Outcome | Peso efectivo |
|---|---|---|---:|
| A | Memory | TRUE | 0.25 |
| B | Search | TRUE | 0.5 |
| C | RAG | FALSE | 0.8 |

Outcome:

- score_TRUE = (0.25 + 0.5) / 3 = 0.25
- score_FALSE = 0.8 / 3 = 0.2667
- winner = FALSE

## Relevant order states

| State | Significado |
|---|---|
| ASSERTIONS_REQUESTED | It was requested to generate assertions |
| DOCUMENT_CREATED | Documento preparado localmente |
| IPFS_UPLOADED | Documento subido a IPFS |
| BLOCKCHAIN_REGISTERED | Notice registered in smart contract |
| VALIDATION_PENDING | Hay validaciones pendientes |
| VALIDATED | All expected validations ended |
| NO_VALIDATORS_AVAILABLE | No validators for the category |
| QUOTA_EXCEEDED | Cuota insuficiente |

## Trazabilidad

news-handler records each event in MongoDB at db.events.

Campos principales:

- order_id
- action
- topic
- timestamp
- payload

Validations are also saved in db.validations.

Campos principales:

- order_id
- postId
- idAssertion
- idValidator
- approval
- tx_hash
- payload
- response_time_seconds

## Consideraciones operativas

- All consumers must be idepotent: news-handler ignores duplicate validations by order_id + idAssertion + idValidator.
- new_validator_config can arrive without order_id; it is processed as a global cache event.
- In light mode, correlation_id allows linking request/response.
- In blockchain mode, the contract is the source of truth for on-chain applications and validations.
- evidence-search is not exposed by gateway/frontend; it is only used by internal network of namespace apis.
