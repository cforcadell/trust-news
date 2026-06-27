# Validadores TrustNews: workers, tipos y comportamiento

## Objetivo

Este documento describe como funcionan los workers de validacion de TrustNews, que tipos de validadores existen, que algoritmo ejecuta cada uno y que modulos intervienen en el flujo.

En la implementacion actual un worker es una instancia del microservicio `api/validate-asertions`. Cada worker se identifica por su `ACCOUNT_ADDRESS`, se registra como validador en blockchain, publica su configuracion en IPFS y Kafka, y, si su tipo es automatico, escucha solicitudes de validacion para ejecutar una decision factual..

## Vision general del worker

Cada pod `validate-asertions` cumple cuatro responsabilidades:

1. **Identidad y registro**
   - Usa `ACCOUNT_ADDRESS` y `PRIVATE_KEY` como identidad del validador.
   - Construye un `ValidatorConfig` con `name`, `type`, `provider`, `model`, fechas y `status`.
   - Sube esa configuracion a IPFS.
   - Registra o actualiza el validador en el smart contract con sus categorias (`VALIDATOR_CATEGORIES`) y el CID de configuracion.
   - Publica un evento `new_validator_config` para que `news-handler` actualice su cache operativa.

2. **API administrativa**
   - Expone endpoints como `/registrar_validador`, `/desregistrar_validador`, `/admin/config` y `/verificar`.
   - Permite cambiar proveedor, modelo o categorias desde el endpoint admin.

3. **Worker automatico de validacion**
   - Solo se activa si `VALIDATOR_TYPE` pertenece a los tipos automaticos: `1`, `2` o `3`.
   - Levanta un listener blockchain para eventos `ValidationRequested`.
   - Levanta un consumidor Kafka para solicitudes `LIGHT` en `TOPIC_LIGHT_VALIDATION_REQUESTS`.
   - Convierte cada solicitud a `assertion-validation-payload-v2`, ejecuta el algoritmo del tipo configurado y devuelve/verifica el resultado.

4. **Persistencia del resultado**
   - En modo `BLOCKCHAIN`, genera un documento de validacion, lo sube a IPFS y llama a `addValidation` en el smart contract.
   - En modo `LIGHT`, no toca blockchain ni IPFS para el resultado; responde por Kafka con `light_validation_completed`.

## Modulos principales

| Modulo | Responsabilidad |
|---|---|
| `api/validate-asertions/main.py` | Worker/API de validacion. Selecciona algoritmo por `VALIDATOR_TYPE`, llama al LLM, llama a `evidence-search` cuando aplica, escucha Kafka/blockchain y registra resultados. |
| `api/common/models/async_models.py` | Define `ValidatorType`, `ValidatorConfig`, pesos por tipo, modelos Kafka y normalizacion de resultados. |
| `api/common/models/protocol_models.py` | Define `assertions-document-v2` y `assertion-validation-payload-v2`, usados tanto en LIGHT como en BLOCKCHAIN. |
| `api/common/utils/validator_registry.py` | Filtra validadores activos, automaticos y compatibles con una categoria. |
| `api/common/utils/scoring.py` | Calcula pesos por validador y resultado ponderado por asercion. |
| `api/evidence-search/main.py` | Servicio RAG: resuelve dominios, construye queries, consulta Tavily si esta configurado, cachea y devuelve evidencias normalizadas. |
| `api/news-handler/main.py` | Orquesta ordenes, genera solicitudes LIGHT, consume respuestas y calcula resultados ponderados. |
| `api/news-chain/main.py` | Escucha eventos on-chain, recupera documentos IPFS y reenvia solicitudes/resultados al backend via Kafka. |

## Tipos de validadores

Los tipos se definen en `ValidatorType`:

| ID | Tipo | Automatico | Peso | Comportamiento |
|---:|---|---|---:|---|
| 1 | `LLM_MEMORY_VALIDATION` | Si | 0.25 | Valida con conocimiento interno del modelo y razonamiento. |
| 2 | `LLM_SEARCH_VALIDATION` | Si | 0.50 | Valida con LLM y busqueda online cuando el proveedor/modelo lo soporta. |
| 3 | `RAG_EVIDENCE_VALIDATION` | Si | 0.80 | Valida con LLM, pero usando evidencias recuperadas por `evidence-search`. |
| 4 | `DETERMINISTIC_VALIDATION` | No | 1.00 | Reservado para validadores no LLM con reglas deterministas. En el worker actual no ejecuta listeners automaticos. |
| 5 | `HUMAN` | No | 0.10 | Representa validacion humana/manual. En el worker actual solo se registra/configura, no valida automaticamente. |

Los tipos `1`, `2` y `3` son los unicos que ejecutan `validate_payload_v2()`. Los tipos `4` y `5` pueden existir como configuracion de validador, pero `validate-asertions` no crea cliente LLM ni arranca listeners de Kafka/blockchain para ellos.

## Algoritmo comun de validacion automatica

Para cualquier tipo automatico el flujo base es:

1. Recibir una solicitud `assertion-validation-payload-v2`.
2. Comprobar que el worker es automatico y tiene cliente AI inicializado.
3. Si el tipo es RAG (`VALIDATOR_TYPE=3`), solicitar evidencias a `evidence-search`.
4. Construir el prompt con prompt especifico del tipo, contexto de noticia serializado, evidencias solo en RAG y texto de la asercion.
5. Enviar el prompt al proveedor configurado (`mistral`, `gemini`, `openrouter` o `grok`).
6. Parsear JSON del modelo con `resultado`, `descripcion` y, opcionalmente, `confidence`, `sources` y `evidence_used`.
7. Aceptar como resultado efectivo solo `TRUE`, `FALSE` o `UNKNOWN`; cualquier otra etiqueta devuelta por el modelo se degrada a `UNKNOWN`.
8. Devolver por Kafka en LIGHT o registrar en IPFS/blockchain en BLOCKCHAIN.

## Clasificacion por comportamiento

### 1. LLM de memoria (`LLM_MEMORY_VALIDATION`)

**Algoritmo:** inferencia directa con LLM.

El worker usa el prompt `LLM_MEMORY_VALIDATION_PROMPT`. El modelo razona sobre la asercion con su conocimiento interno y el contexto incluido en el payload. No llama a `evidence-search` y no activa busqueda online.

**Variables clave:** `VALIDATOR_TYPE=1`, `LLM_MEMORY_VALIDATION_PROMPT`.

**Uso esperado:** validador rapido y barato, util como senal inicial. Su peso es bajo (`0.25`) porque no aporta fuentes externas ni evidencia recuperada en tiempo de validacion.

### 2. LLM con busqueda online (`LLM_SEARCH_VALIDATION`)

**Algoritmo:** inferencia con LLM y capacidad online del proveedor.

El worker usa `LLM_SEARCH_VALIDATION_PROMPT`, que pide buscar evidencias actuales y devolver fuentes. No llama al microservicio `evidence-search`; delega la capacidad de busqueda al proveedor/modelo.

En OpenRouter, cuando `VALIDATOR_TYPE=2`, el modelo se transforma automaticamente con sufijo `:online`. Por ejemplo, `openai/gpt-5-mini` pasa a `openai/gpt-5-mini:online`.

**Variables clave:** `VALIDATOR_TYPE=2`, `LLM_SEARCH_VALIDATION_PROMPT`.

**Uso esperado:** validador con mas contexto temporal que el tipo 1, pero con menos control sobre recuperacion y ranking de fuentes que RAG. Su peso es medio (`0.50`).

### 3. RAG con evidencias (`RAG_EVIDENCE_VALIDATION`)

**Algoritmo:** recuperacion de evidencias + validacion estricta con LLM.

El worker llama a `evidence-search` siempre que `VALIDATOR_TYPE=3`. Ese servicio recibe la asercion enriquecida, construye una politica de busqueda y devuelve evidencias normalizadas. Despues el worker inyecta esas evidencias en el prompt `RAG_EVIDENCE_VALIDATION_PROMPT`.

El prompt RAG exige validar solo con las evidencias proporcionadas. Si no hay evidencias suficientes, el comportamiento esperado es `UNKNOWN` o insuficiencia equivalente.

**Variables clave:** `VALIDATOR_TYPE=3`, `EVIDENCE_SEARCH_URL`, `EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS`, `RAG_EVIDENCE_VALIDATION_PROMPT`.

**Subcomportamientos RAG:**

| Variante | Configuracion | Comportamiento |
|---|---|---|
| RAG general | `EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS=NONE` | Construye queries desde texto, entidades, ubicaciones y contexto temporal, con busqueda general como fallback. |
| RAG con dominios preferentes | `EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS=LOCAL` | Usa perfiles Mongo `evidence_domain_profiles` para priorizar dominios por categoria, subcategoria, entidades y ubicaciones. |
| RAG sin Tavily | `TAVILY_API_KEY` vacio | Devuelve dominios seleccionados como evidencias placeholder; util para desarrollo, no para validacion factual completa. |
| RAG con Tavily | `TAVILY_API_KEY` configurado | Ejecuta queries reales, fusiona resultados, deduplica URLs y limita resultados por dominio. |

**Uso esperado:** validador de mayor confianza operacional porque la decision queda ligada a evidencias explicitamente recuperadas. Su peso es alto (`0.80`).

### 4. Deterministico (`DETERMINISTIC_VALIDATION`)

**Algoritmo:** reglas exactas o comprobaciones programaticas.

Este tipo esta definido para validadores que no dependen de LLM: por ejemplo, validaciones contra bases de datos oficiales, reglas de formato, comprobaciones criptograficas o APIs deterministas.

En el worker actual no hay implementacion automatica para este tipo. Si `VALIDATOR_TYPE=4`, el servicio se registra como validador, pero no crea cliente AI ni escucha solicitudes automaticas.

**Uso esperado:** maxima confianza cuando el dominio permite una comprobacion objetiva. Por eso su peso es `1.00`.

### 5. Humano (`HUMAN`)

**Algoritmo:** decision manual externa al worker automatico.

Este tipo representa un validador humano o una organizacion que emite validaciones fuera del flujo automatico de `validate-asertions`.

En el worker actual no hay listener automatico para `HUMAN`. Se usa como clasificacion y configuracion, no como agente LLM.

**Uso esperado:** senal auxiliar o de auditoria. Su peso por defecto es `0.10`, bajo porque el sistema no modela aun un flujo formal de revision humana con SLA, evidencia o consenso.

## Modos de ejecucion

### Modo LIGHT

`news-handler` selecciona validadores desde su cache con `light_validators_for_category()`. El filtro exige validador activo, tipo automatico (`1`, `2` o `3`) y soporte de la categoria de la asercion.

Por cada asercion y validador, publica un `light_validation_request` en Kafka. El worker que coincide con `validator_id == ACCOUNT_ADDRESS` procesa el mensaje y responde con `light_validation_completed`.

LIGHT no publica el documento en IPFS ni registra la validacion en blockchain. Guarda resultados en Mongo con fuentes, evidencias, confianza, error y tiempo de respuesta.

### Modo BLOCKCHAIN

El documento de aserciones se sube a IPFS y se registra on-chain. Cuando el contrato emite `ValidationRequested`, el worker automatico correspondiente recupera el documento desde IPFS, reconstruye `AssertionsDocumentV2` si hace falta, localiza la asercion por `assertion_index`, construye `assertion-validation-payload-v2`, ejecuta el algoritmo, sube el documento de validacion a IPFS y registra el resultado con `addValidation`.

`news-chain` tambien escucha eventos del contrato y reenvia trazas/resultados hacia Kafka para mantener sincronizado el backend.

## Configuracion por worker

La clasificacion real de cada worker se decide por variables de entorno:

| Variable | Funcion |
|---|---|
| `VALIDATOR_NAME` | Nombre publico del validador en su config IPFS. |
| `VALIDATOR_TYPE` | Tipo de algoritmo/comportamiento. |
| `VALIDATOR_CATEGORIES` | Categorias que el validador acepta. |
| `AI_PROVIDER` | Proveedor LLM: `mistral`, `gemini`, `openrouter`, `grok` o `none`. |
| `MODEL` | Modelo usado por el proveedor. |
| `API_URL` | Endpoint del proveedor. |
| `TEMPERATURE` | Temperatura del LLM. |
| `EVIDENCE_SEARCH_URL` | URL interna del microservicio de evidencias. |
| `EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS` | Estrategia de dominios: `NONE`, `LOCAL`, `EXT_OFFICIAL_FIRST` o `EXT_ONLY_OFFICIAL`. |

En Kubernetes, `k8s/apis/validate-asertions/base/configmap-common.yaml` define defaults y prompts. Los overlays locales especializan cada worker. En la configuracion local actual:

| Worker | Tipo | Provider/modelo | Comportamiento |
|---|---:|---|---|
| `worker-1` | 1 | OpenRouter + `mistralai/mistral-small-24b-instruct-2501` | LLM de memoria, sin evidence-search ni online. |
| `worker-2` | 3 | Groq-compatible + `llama-3.1-8b-instant` | RAG con `evidence-search`, sin dominios preferentes. |
| `worker-3` | 3 | OpenRouter + `openai/gpt-5-mini` | RAG con `evidence-search` y dominios preferentes. |

## Scoring y resultado ponderado

El backend no decide solo por conteo de votos. Cada validacion se transforma en un detalle ponderado:

```text
effective_weight = validator_type_weight * reputation
score_result = suma(effective_weight para ese resultado) / numero_de_validadores
```

Los pesos por tipo son:

| Tipo | Peso |
|---|---:|
| `LLM_MEMORY_VALIDATION` | 0.25 |
| `LLM_SEARCH_VALIDATION` | 0.50 |
| `RAG_EVIDENCE_VALIDATION` | 0.80 |
| `DETERMINISTIC_VALIDATION` | 1.00 |
| `HUMAN` | 0.10 |

`reputation` vive en la cache operativa del backend, no en el JSON IPFS del validador. Si no hay reputacion explicita, se usa `1.0`.

El ganador por asercion es el resultado con mayor score entre `TRUE`, `FALSE` y `UNKNOWN`. Los detalles incluyen tipo de validador, peso, reputacion, peso efectivo, descripcion, fuentes y evidencias usadas.

## Resumen de clasificacion

| Clase | Tipos | Fuente de verdad | Automatizacion | Confianza operacional |
|---|---|---|---|---|
| LLM puro | `LLM_MEMORY_VALIDATION` | Conocimiento del modelo + contexto | Alta | Baja-media |
| LLM online | `LLM_SEARCH_VALIDATION` | Proveedor LLM con busqueda | Alta | Media |
| RAG | `RAG_EVIDENCE_VALIDATION` | Evidencias recuperadas y cacheadas | Alta | Alta |
| Programatico | `DETERMINISTIC_VALIDATION` | Reglas/APIs exactas | No implementada en worker actual | Muy alta si se implementa por dominio |
| Manual | `HUMAN` | Revision humana | No implementada en worker actual | Depende del proceso externo |
