# Anexo: mensajeria Kafka y casos de uso TrustNews

## Vision general

TrustNews usa Kafka como bus asincrono entre microservicios. El patron principal es:

1. news-handler crea una orden y publica una peticion.
2. Un microservicio especializado consume esa peticion.
3. El microservicio publica una respuesta o evento.
4. news-handler consume respuestas, actualiza MongoDB y avanza el estado de la orden.

La coleccion principal de ordenes se mantiene en MongoDB, normalmente orders. Los eventos se registran tambien en events para trazabilidad.

## Servicios implicados

| Servicio | Rol |
|---|---|
| news-handler | Orquestador principal, API consumida por frontend/gateway, estado de ordenes, cache de validadores |
| generate-asertions | Genera aserciones desde texto |
| ipfs-fastapi | Sube y lee documentos desde IPFS |
| news-chain | Integra smart contract y escucha eventos blockchain |
| validate-asertions | Worker de validacion por validador |
| evidence-search | Servicio HTTP interno para evidencias RAG; no consume Kafka |
| admin | Cuotas y recomendaciones de modelos |

## Topics principales

Los nombres pueden configurarse por entorno, pero los valores habituales son:

| Topic | Productor | Consumidor | Mensajes principales |
|---|---|---|---|
| fake_news_requests_generate | news-handler | generate-asertions | generate_assertions |
| fake_news_requests_ipfs | news-handler | ipfs-fastapi | upload_ipfs |
| fake_news_requests_blockchain | news-handler | news-chain | register_blockchain |
| fake_news_requests_validate | news-chain o flujo heredado | validate-asertions/orquestacion heredada | request_validation |
| fake_news_requests_light_validation | news-handler | validate-asertions | light_validation_request |
| fake_news_responses | Todos los workers | news-handler | respuestas y eventos |

Nota: en codigo existen defaults historicos trustnews.validation.requests y trustnews.validation.responses, pero los ConfigMaps actuales apuntan el flujo light a fake_news_requests_light_validation y fake_news_responses.

## Acciones Kafka normalizadas

### generate_assertions

Publicado por news-handler a fake_news_requests_generate.

Payload conceptual:

{
  "action": "generate_assertions",
  "order_id": "uuid",
  "payload": {
    "text": "texto de la noticia",
    "validation_mode": "BLOCKCHAIN | LIGHT"
  }
}

Respuesta esperada:

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

Si falla, se publica assertions_not_generated con error y numero de intentos.

## Caso de uso 1: publicacion normal con blockchain

Objetivo: publicar una noticia, generar aserciones, subir documento a IPFS, registrar post en blockchain y solicitar validaciones automaticas.

Flujo:

1. Cliente llama a news-handler, normalmente POST /publishNew.
2. news-handler crea orden en MongoDB con estado inicial.
3. news-handler publica generate_assertions en fake_news_requests_generate.
4. generate-asertions consume, genera aserciones y publica assertions_generated en fake_news_responses.
5. news-handler consume assertions_generated.
6. Si validation_mode=BLOCKCHAIN, valida/normaliza assertions-document-v2 y publica upload_ipfs en fake_news_requests_ipfs.
7. ipfs-fastapi sube documento a IPFS y responde ipfs_uploaded.
8. news-handler consume ipfs_uploaded, guarda cid y publica register_blockchain en fake_news_requests_blockchain.
9. news-chain registra el post en el contrato. El contrato selecciona validadores por categoria.
10. news-chain publica blockchain_registered en fake_news_responses.
11. news-handler guarda postId, tx_hash, assertions, validadores esperados por asercion y validators_pending.
12. El contrato emite ValidationRequested por cada validador/asercion.
13. Cada instancia validate-asertions escucha eventos blockchain filtrados por su ACCOUNT_ADDRESS.
14. Si VALIDATOR_TYPE es automatico, valida la asercion: tipo 1 memoria, tipo 2 online, tipo 3 RAG.
15. validate-asertions sube documento de validacion a IPFS y registra validacion en blockchain.
16. news-chain detecta o consume la validacion y publica validation_completed.
17. news-handler consume validation_completed, actualiza validations, recalcula pendientes y, si termina todo, marca status=VALIDATED.
18. El endpoint de orden devuelve assertion_results con scores ponderados.

## Caso de uso 2: validacion LIGHT sin blockchain/IPFS

Objetivo: validar aserciones de forma rapida usando Kafka, sin registrar noticia ni validaciones en blockchain.

Flujo:

1. Cliente publica con validation_mode=LIGHT.
2. Se generan aserciones igual que en el flujo normal.
3. news-handler detecta validation_mode=LIGHT al recibir assertions_generated.
4. No envia a IPFS ni blockchain.
5. Crea documento local y calcula validadores activos desde validators_cache por categoria on-chain.
6. Filtra validadores no automaticos: excluye DETERMINISTIC_VALIDATION y HUMAN.
7. Publica un mensaje por asercion/validador en fake_news_requests_light_validation con action=light_validation_request y assertion-validation-payload-v2 inline.
8. Cada worker validate-asertions consume el topic, pero solo procesa mensajes cuyo validator_id coincide con su ACCOUNT_ADDRESS.
9. El worker valida segun VALIDATOR_TYPE y publica light_validation_completed en fake_news_responses.
10. news-handler guarda la validacion en la orden y en la coleccion validations.
11. Cuando no quedan pendientes, marca la orden como VALIDATED.

Payload conceptual de light_validation_request:

{
  "action": "light_validation_request",
  "order_id": "uuid",
  "payload": {
    "validation_mode": "LIGHT",
    "assertion_index": 0,
    "idAssertion": "1",
    "assertion_text": "asercion",
    "category": 1,
    "validator_id": "0x...",
    "original_text": "texto completo",
    "correlation_id": "order:assertion:validator"
  }
}

Respuesta conceptual light_validation_completed:

{
  "action": "light_validation_completed",
  "order_id": "uuid",
  "payload": {
    "validation_mode": "LIGHT",
    "assertion_index": 0,
    "idAssertion": "1",
    "validator_id": "0x...",
    "category": 1,
    "verdict": 1,
    "description": "...",
    "confidence": "HIGH",
    "sources": [],
    "evidence_used": [],
    "correlation_id": "order:assertion:validator",
    "error": null
  }
}

## Caso de uso 3: validador RAG con evidence-search

Objetivo: validar una asercion usando evidencias externas gestionadas por TrustNews, no por el proveedor LLM.

Configuracion del worker:

- VALIDATOR_TYPE: "3"
- USE_EVIDENCE_SEARCH: "true"
- EVIDENCE_SEARCH_URL: "http://evidence-search.apis.svc.cluster.local:8074"

Flujo:

1. El worker recibe una solicitud de validacion por blockchain event o Kafka light.
2. Antes de llamar al LLM, ejecuta POST /search/evidence en evidence-search con evidence-search-request-v2.
3. evidence-search carga perfiles desde Mongo `evidence_domain_profiles` o usa fallback minimo en codigo.
4. domain_router resuelve dominios por category, subcategory, ubicaciones, entidades y preferred_source_types.
5. Si Tavily esta configurado, consulta dominios preferentes y busqueda general de fallback; si no, devuelve dominios simulados para trazabilidad.
6. El worker inyecta sources en el prompt RAG.
7. El LLM debe responder usando exclusivamente esas evidencias.
8. La respuesta puede incluir confidence y evidence_used.
9. news-handler conserva esos campos y frontend los muestra.

## Caso de uso 4: validador online via OpenRouter

Objetivo: usar un modelo con busqueda online propia del proveedor.

Configuracion:

- VALIDATOR_TYPE: "2"
- USE_EVIDENCE_SEARCH: "false"
- ONLINE_SEARCH_ENABLED: "true"
- AI_PROVIDER: "openrouter"
- MODEL: "openai/gpt-5-mini"

Comportamiento:

- El worker no llama a evidence-search.
- Para OpenRouter, envia el modelo con sufijo :online.
- El prompt pide buscar evidencias actuales y devolver fuentes si el proveedor lo permite.

## Caso de uso 5: validador humano o determinista

Objetivo: registrar validadores que no deben participar todavia en validacion automatica.

Configuracion determinista:

- VALIDATOR_TYPE: "4"
- AI_PROVIDER: "none"

Configuracion humana:

- VALIDATOR_TYPE: "5"
- AI_PROVIDER: "none"

Comportamiento:

- Se registran contra smart contract.
- Publican o actualizan config de validador para cache.
- No levantan listeners automaticos de validacion.
- No consumen Kafka light.
- No llaman LLM.
- No llaman evidence-search.

## Eventos de configuracion de validadores

Cuando un validador se registra, actualiza config o arranca, validate-asertions publica new_validator_config en fake_news_responses.

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

news-handler consume este evento y actualiza validators_cache.

La cache agrega campos operativos que no forman parte de IPFS:

{
  "validator_type": 3,
  "reputation": 1.0,
  "metrics_reset_at": null
}

## Calculo de resultado despues de mensajes de validacion

Cada vez que news-handler devuelve una orden, adjunta assertion_results.

Para cada asercion:

1. Lee validaciones completadas.
2. Obtiene tipo y reputation desde validator_config o cache.
3. Calcula effective_weight = validator_type_weight * reputation.
4. Agrupa por resultado normalizado.
5. Calcula score_result = sum(effective_weight del resultado) / num_validators.
6. El ganador es el resultado con mayor score.

Ejemplo:

| Validador | Tipo | Resultado | Peso efectivo |
|---|---|---|---:|
| A | Memory | TRUE | 0.25 |
| B | Search | TRUE | 0.5 |
| C | RAG | FALSE | 0.8 |

Resultado:

- score_TRUE = (0.25 + 0.5) / 3 = 0.25
- score_FALSE = 0.8 / 3 = 0.2667
- winner = FALSE

## Estados de orden relevantes

| Estado | Significado |
|---|---|
| ASSERTIONS_REQUESTED | Se pidio generacion de aserciones |
| DOCUMENT_CREATED | Documento preparado localmente |
| IPFS_UPLOADED | Documento subido a IPFS |
| BLOCKCHAIN_REGISTERED | Noticia registrada en smart contract |
| VALIDATION_PENDING | Hay validaciones pendientes |
| VALIDATED | Todas las validaciones esperadas terminaron |
| NO_VALIDATORS_AVAILABLE | No hay validadores para la categoria |
| QUOTA_EXCEEDED | Cuota insuficiente |

## Trazabilidad

news-handler registra cada evento en MongoDB en db.events.

Campos principales:

- order_id
- action
- topic
- timestamp
- payload

Las validaciones se guardan tambien en db.validations.

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

- Todos los consumidores deben ser idempotentes: news-handler ignora validaciones duplicadas por order_id + idAssertion + idValidator.
- new_validator_config puede llegar sin order_id; se procesa como evento global de cache.
- En modo light, correlation_id permite enlazar request/response.
- En modo blockchain, el contrato es la fuente de verdad para solicitudes y validaciones on-chain.
- evidence-search no esta expuesto por gateway/frontend; solo se usa por red interna del namespace apis.
