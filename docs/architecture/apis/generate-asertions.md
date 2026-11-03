# Generate Asertions

## Description

`api/generate-asertions` generates structured assertions from a text using an LLM provider. You can work by HTTP direct or as a Kafka worker within the asynchronous command stream.

## Endpoints

- `POST /extraer`: Receives text and `client_id`, validates `news_generation` quota in `admin`, calls the selected LLM provider, increases consumption and returns a `assertions_generated` response with assertions document.

## Validation context

The generation of assertions must return each assertion with verifiable context in the existing fields of `assertions-document-v2`: `context.locations`, `context.entities`, `context.temporal_context`, `search_hints` and `context_confidence`. The context that appears literally in the assertion uses `origin=explicit`; the context deduced from the full text of the news uses `origin=inferred`. No new communications are added or the blockchain contract changes.

`suggested_queries` should be autonomous and incorporate the time context, entities and locations needed for `evidence-search` to be able to consult Tavily/Exa accurately.

## Daemons

- Consumer Kafka `consume_and_process`: listen `INPUT_TOPIC` with `group_id=generate-assertions-group`. Processes `generate_assertions` messages, calls LLM and publishes `assertions_generated` or `assertions_not_generated` messages in `OUTPUT_TOPIC`.
- Local Kafka Producer: created with the consumer to publish responses.

## Initialisation

When booting `.env` load, configures single-line logging JSON, selects AI provider, Kafka topics, prompt, temperature, limits and re-attempts. Message line breaks and exceptions are kept escaped within the JSON so that CRI, Fluent Bit and Loki maintain a single event. The full LLM response prompts and bodies are not recorded at `INFO` level; metadata are issued as a supplier, model, duration and sizes. At `startup`, Kafka consumer launches second-hand. If executed as a script, it starts ovicorn at `PORT`.

## Environment variables

- `LOG_LEVEL`: logging level.
- `AI_PROVIDER`: LLM supplier (`mistral`, `gemini`, `openrouter`, depending on code support).
- `KAFKA_BROKER` or `KAFKA_BOOTSTRAP`: bootstrap Kafka.
- `KAFKA_INPUT_TOPIC` or `ASSERTIONS_REQUEST_TOPIC`: entry topic.
- `KAFKA_OUTPUT_TOPIC` or `ASSERTIONS_RESPONSE_TOPIC`: output topic.
- `MISTRAL_API_URL`, `MISTRAL_API_KEY`, `MISTRAL_MODEL`: Mistral configuration.
- `GEMINI_API_URL`, `GEMINI_API_KEY`, `GEMINI_MODEL`: Gemini configuration.
- `OPENROUTER_API_URL`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`: OpenRouter configuration.
- `ADMIN_URL`: URL of the admin service to query and update quotas.
- `PROMPT`: prompt base used to extract assertions.
- `TEMPERATURE`: model temperature.
- `MAX_ASSERTIONS`: maximum of returned assertions.
- `HTTP_TIMEOUT`: total timeout, in seconds, of each attempt against the provider. It is modifiable by `PUT /admin/config` (`http_timeout`) and its default value is `60`.
- `NUM_REINTENTOS` or `MAX_RETRIES`: Number of retry.
- `RETRY_DELAY`: wait between retryings.
- `PORT`: uvicorn port if executed directly.
