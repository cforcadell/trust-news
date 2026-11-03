# Shared provider infrastructure

`api/common/llm` centralizes provider selection, sync/async HTTP execution,
timeouts, retry policy, error mapping, structured JSON parsing and usage
metadata. It supports the existing Gemini, OpenRouter, Mistral and Grok
(OpenAI-compatible) providers. Business prompts and response schemas remain in
`generate-asertions`, `validate-asertions` and `source-router`.

`api/common/search` centralizes `SearchProvider`, `SearchRequest/SearchResult`,
the Exa and Tavily adapters, URL/domain normalization, provider selection,
timeouts, retries and errors. Its consumers are `evidence-search` and
`source-router`; query construction, routing policy, evidence chunks and
grounding remain with their owning services.

The dependency direction is one-way: common packages do not import service
modules.
