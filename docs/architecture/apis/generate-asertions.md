# Generate Asertions

## Descripción

`api/generate-asertions` genera aserciones estructuradas a partir de un texto usando un proveedor LLM. Puede trabajar por HTTP directo o como worker Kafka dentro del flujo asíncrono de órdenes.

## Endpoints

- `POST /extraer`: recibe un texto y un `client_id`, valida cuota `news_generation` en `admin`, llama al proveedor LLM seleccionado, incrementa consumo y devuelve una respuesta `assertions_generated` con documento de aserciones.

## Daemons

- Consumidor Kafka `consume_and_process`: escucha `INPUT_TOPIC` con `group_id=generate-assertions-group`. Procesa mensajes `generate_assertions`, llama al LLM y publica `assertions_generated` o `assertions_not_generated` en `OUTPUT_TOPIC`.
- Productor Kafka local: se crea junto al consumidor para publicar respuestas.

## Inicialización

Al arrancar carga `.env`, configura logging, selecciona proveedor de IA, tópicos Kafka, prompt, temperatura, límites y reintentos. En `startup` lanza el consumidor Kafka en segundo plano. Si se ejecuta como script, arranca uvicorn en `PORT`.

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
- `HTTP_TIMEOUT`: timeout de llamadas al proveedor.
- `NUM_REINTENTOS` o `MAX_RETRIES`: número de reintentos.
- `RETRY_DELAY`: espera entre reintentos.
- `PORT`: puerto de uvicorn si se ejecuta directamente.
