# Generate Asertions

## Descripción

`api/generate-asertions` genera aserciones estructuradas a partir de un texto usando un proveedor LLM. Puede trabajar por HTTP directo o como worker Kafka dentro del flujo asíncrono de órdenes.

## Endpoints

- `POST /extraer`: recibe un texto y un `client_id`, valida cuota `news_generation` en `admin`, llama al proveedor LLM seleccionado, incrementa consumo y devuelve una respuesta `assertions_generated` con documento de aserciones.

## Contexto de validación

La generación de aserciones debe devolver cada aserción con contexto verificable en los campos existentes de `assertions-document-v2`: `context.locations`, `context.entities`, `context.temporal_context`, `search_hints` y `context_confidence`. El contexto que aparece literalmente en la aserción usa `origin=explicit`; el contexto deducido del texto completo de la noticia usa `origin=inferred`. No se añaden comunicaciones nuevas ni cambia el contrato blockchain.

Las `suggested_queries` deben ser autónomas e incorporar el contexto temporal, entidades y lugares necesarios para que `evidence-search` pueda consultar Tavily/Exa con precisión.

## Daemons

- Consumidor Kafka `consume_and_process`: escucha `INPUT_TOPIC` con `group_id=generate-assertions-group`. Procesa mensajes `generate_assertions`, llama al LLM y publica `assertions_generated` o `assertions_not_generated` en `OUTPUT_TOPIC`.
- Productor Kafka local: se crea junto al consumidor para publicar respuestas.

## Inicialización

Al arrancar carga `.env`, configura logging JSON de una sola línea, selecciona proveedor de IA, tópicos Kafka, prompt, temperatura, límites y reintentos. Los saltos de línea de mensajes y excepciones se conservan escapados dentro del JSON para que CRI, Fluent Bit y Loki mantengan un único evento. Los prompts y cuerpos completos de las respuestas LLM no se registran en nivel `INFO`; se emiten metadatos como proveedor, modelo, duración y tamaños. En `startup` lanza el consumidor Kafka en segundo plano. Si se ejecuta como script, arranca uvicorn en `PORT`.

## Variables de entorno

- `LOG_LEVEL`: nivel de logging.
- `AI_PROVIDER`: proveedor LLM (`mistral`, `gemini`, `openrouter`, según soporte del código).
- `KAFKA_BROKER` o `KAFKA_BOOTSTRAP`: bootstrap Kafka.
- `KAFKA_INPUT_TOPIC` o `ASSERTIONS_REQUEST_TOPIC`: tópico de entrada.
- `KAFKA_OUTPUT_TOPIC` o `ASSERTIONS_RESPONSE_TOPIC`: tópico de salida.
- `MISTRAL_API_URL`, `MISTRAL_API_KEY`, `MISTRAL_MODEL`: configuración Mistral.
- `GEMINI_API_URL`, `GEMINI_API_KEY`, `GEMINI_MODEL`: configuración Gemini.
- `OPENROUTER_API_URL`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`: configuración OpenRouter.
- `ADMIN_URL`: URL del servicio admin para consultar y actualizar cuotas.
- `PROMPT`: prompt base usado para extraer aserciones.
- `TEMPERATURE`: temperatura del modelo.
- `MAX_ASSERTIONS`: máximo de aserciones devueltas.
- `HTTP_TIMEOUT`: timeout total, en segundos, de cada intento contra el proveedor. Es modificable mediante `PUT /admin/config` (`http_timeout`) y su valor predeterminado es `60`.
- `NUM_REINTENTOS` o `MAX_RETRIES`: número de reintentos.
- `RETRY_DELAY`: espera entre reintentos.
- `PORT`: puerto de uvicorn si se ejecuta directamente.
