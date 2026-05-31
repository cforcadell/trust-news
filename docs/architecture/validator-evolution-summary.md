# Evolucion de validadores TrustNews: resumen tecnico

## Objetivo

Se incorpora soporte explicito para tipos de validadores, validacion RAG mediante el nuevo microservicio evidence-search, reputacion operativa en cache de validadores y calculo ponderado de resultados por asercion para backend/frontend.

La implementacion mantiene el flujo existente y anade comportamiento incremental. El contrato sigue registrando validadores y validaciones como hasta ahora; la nueva logica vive principalmente en servicios backend, cache operativa, ConfigMaps y frontend.

## Cambios principales

### 1. Tipos de validadores compartidos

Archivo: api/common/async_models.py

Se actualiza ValidatorType con los tipos nuevos:

- LLM_MEMORY_VALIDATION = 1
- LLM_SEARCH_VALIDATION = 2
- RAG_EVIDENCE_VALIDATION = 3
- DETERMINISTIC_VALIDATION = 4
- HUMAN = 5

Se mantienen alias de compatibilidad para configuraciones previas: General_AI, Trained_AI, Dedicated_Agent y Human.

Tambien se anade la funcion centralizada get_validator_type_weight().

Pesos definidos:

| Tipo | Peso |
|---|---:|
| LLM_MEMORY_VALIDATION | 0.25 |
| LLM_SEARCH_VALIDATION | 0.5 |
| RAG_EVIDENCE_VALIDATION | 0.8 |
| DETERMINISTIC_VALIDATION | 1.0 |
| HUMAN | 0.1 |

Tambien se anade normalize_validation_result(), que mapea TRUE/SUPPORTED a TRUE, FALSE/REFUTED a FALSE, y UNKNOWN/INSUFFICIENT/CONFLICTED/PARTIAL a UNKNOWN.

## 2. validate-asertions

Archivo: api/validate-asertions/main.py

El worker ahora lee estas variables:

- VALIDATOR_TYPE
- USE_EVIDENCE_SEARCH
- ONLINE_SEARCH_ENABLED
- EVIDENCE_SEARCH_URL
- LLM_MEMORY_VALIDATION_PROMPT
- LLM_SEARCH_VALIDATION_PROMPT
- RAG_EVIDENCE_VALIDATION_PROMPT

Comportamiento por tipo:

| Tipo | LLM | Online | evidence-search | Kafka automatico |
|---|---|---|---|---|
| LLM_MEMORY_VALIDATION | Si | No | No | Si |
| LLM_SEARCH_VALIDATION | Si | Si, si aplica | No | Si |
| RAG_EVIDENCE_VALIDATION | Si | No | Si | Si |
| DETERMINISTIC_VALIDATION | No | No | No | No |
| HUMAN | No | No | No | No |

Para validadores no automaticos, el servicio se registra contra smart contract, pero no levanta listeners automaticos de validacion blockchain/Kafka ni ejecuta LLM.

### Prompts diferenciados

El prompt se selecciona con selected_validation_prompt() segun VALIDATOR_TYPE.

- Memory: valida con conocimiento general, prudencia y UNKNOWN ante duda.
- Search: solicita busqueda online y fuentes si el proveedor lo soporta.
- RAG: obliga a usar exclusivamente evidencias proporcionadas.

Se mantiene compatibilidad con VALIDATION_PROMPT: si existe, actua como fallback para los nuevos prompts.

### Modo online OpenRouter

Para LLM_SEARCH_VALIDATION, si ONLINE_SEARCH_ENABLED=true y el proveedor es OpenRouter, el modelo se envia con sufijo :online.

Ejemplo: openai/gpt-5-mini pasa a openai/gpt-5-mini:online.

### Integracion RAG con evidence-search

Para RAG_EVIDENCE_VALIDATION, si USE_EVIDENCE_SEARCH=true, el worker llama a POST {EVIDENCE_SEARCH_URL}/search/evidence usando evidence-search-request-v2.

El resultado sources se inyecta en el prompt RAG como evidencias. Si el servicio falla, el validador continua con evidencias vacias y el prompt debe devolver UNKNOWN o INSUFFICIENT.

### Respuestas enriquecidas

ValidatorAPIResponse y LightValidationResponsePayload soportan ahora:

- confidence
- sources
- evidence_used

Esto permite conservar fuentes online y evidencias RAG hasta el frontend.

## 3. Microservicio evidence-search

Directorio: api/evidence-search/

Ficheros creados:

- api/evidence-search/main.py
- api/evidence-search/Dockerfile
- api/evidence-search/requirements.txt
- api/evidence-search/__init__.py

Endpoints:

- GET /health
- POST /search/evidence, flujo unico usado por validadores RAG. Recibe una asercion enriquecida, aplica domain_router y devuelve evidence-search-response-v2.

Responsabilidad: seleccionar dominios preferentes desde perfiles Mongo (`evidence_domain_profiles`) usando category, subcategory, entidades, ubicacion y tipos de fuente preferidos; construir queries; consultar Tavily si esta configurado; devolver evidencias normalizadas. Si Mongo no tiene perfiles, usa un fallback minimo en codigo.

Coleccion MongoDB de configuracion contextual: evidence_domain_profiles.


Variables principales:

- TAVILY_API_URL=https://api.tavily.com/search
- TAVILY_SEARCH_DEPTH=advanced
- TAVILY_INCLUDE_ANSWER=false
- TAVILY_INCLUDE_RAW_CONTENT=true
- TAVILY_MAX_RESULTS=5
- TAVILY_TIMEOUT=30
- TAVILY_API_KEY desde Secret

## 4. Kubernetes y Skaffold

Kubernetes creado en:

- k8s/apis/evidence-search/base/
- k8s/apis/evidence-search/overlays/local/
- k8s/apis/evidence-search/overlays/prod/

Recursos:

- ConfigMap evidence-search-config
- Secret tavily-secret
- Deployment evidence-search
- Service evidence-search, ClusterIP, puerto 8074
- Kustomization local/prod

Skaffold actualizado en skaffold.yaml:

- Artifact Docker evidence-search.
- Deploy en perfil local apis-frontend.
- Deploy en perfil prod apis-frontend-prod.
- Port-forward local localhost:8074 -> service/evidence-search:8074.

## 5. ConfigMaps validate-asertions

Archivo base: k8s/apis/validate-asertions/base/configmap-common.yaml

Se anaden defaults:

- VALIDATOR_TYPE: "1"
- USE_EVIDENCE_SEARCH: "false"
- ONLINE_SEARCH_ENABLED: "false"
- EVIDENCE_SEARCH_URL: "http://evidence-search.apis.svc.cluster.local:8074"

Y prompts:

- LLM_MEMORY_VALIDATION_PROMPT
- LLM_SEARCH_VALIDATION_PROMPT
- RAG_EVIDENCE_VALIDATION_PROMPT

Overlays locales actualizados:

| Worker | Tipo | Uso esperado |
|---|---:|---|
| worker-1 | 1 | LLM memoria |
| worker-2 | 2 | LLM online |
| worker-3 | 3 | RAG con evidence-search |

Overlays prod actualizados con defaults tipo 1 para mantener compatibilidad.

## 6. Cache operativa de validadores

Archivos:

- api/news-chain/main.py
- api/news-handler/main.py

La reputacion se mueve al plano operativo de cache. El JSON de config IPFS no incluye reputation.

Ejemplo conceptual de cache operativa:

{
  "validator": "0x...",
  "categories": [1, 2],
  "validator_type": 3,
  "reputation": 1.0,
  "ipfs_hash": "Qm...",
  "config": {
    "name": "Gemini RAG Validator",
    "type": 3,
    "provider": "gemini",
    "model": "gemini-2.5-flash",
    "status": 1
  }
}

news-chain devuelve reputation=1.0 hacia backend. news-handler garantiza default 1.0 al cargar o actualizar cache.

## 7. Calculo ponderado por asercion

Archivo: api/news-handler/main.py

Funciones nuevas:

- validation_weight_detail()
- calculate_assertion_result()
- calculate_order_assertion_results()

Formula:

- effective_weight = validator_type_weight * reputation
- score_result = sum(effective_weight del grupo resultado) / num_validators

Importante: se divide por numero de validadores, no por suma de pesos.

El endpoint de orden devuelve assertion_results con scores, winner, validations_count y detalles por validador.

## 8. Frontend

Archivos:

- web_classic/app/js/app.js
- web_classic/app/css/style.css

Cambios:

- Usa assertion_results si existe.
- Mantiene fallback por conteo de votos si no existe.
- Muestra winner, score TRUE/FALSE/UNKNOWN, tipo de validador, peso, reputation, peso efectivo, resultado, descripcion y fuentes/evidencias.
- El resumen global de noticia usa winners ponderados cuando estan disponibles.

## 9. Tests

Ficheros creados:

- api/tests/test_evidence_search_units.py
- api/tests/test_validator_types_and_scores.py

Cubren normalizacion/hash de aserciones, excerpt, clasificacion de fuentes, forma de fuentes Tavily normalizadas, pesos por tipo, normalizacion de resultados y formula de score dividida por num_validators.

No hacen llamadas reales a Tavily.

## 10. Validaciones realizadas

Se comprobo sintaxis Python sin generar pyc mediante compile().

Se comprobo JavaScript con:

node --check web_classic/app/js/app.js

pytest no pudo ejecutarse porque el entorno base no tenia instalado pytest.

## 11. Riesgos y notas

- TAVILY_API_KEY se inyecta desde el Secret tavily-secret. En local se genera con kustomize desde tavily.env no versionado; en prod debe crearse previamente en el servidor o pipeline.
- DETERMINISTIC_VALIDATION y HUMAN no participan en el flujo automatico Kafka/LLM, pero siguen pudiendo registrarse.
- El smart contract conserva su campo reputation, pero backend usa reputation operativa 1.0 en cache.
- Las ordenes antiguas sin assertion_results siguen renderizando por conteo simple en frontend.
- El flujo RAG depende de que evidence-search este desplegado y resoluble como evidence-search.apis.svc.cluster.local:8074.
