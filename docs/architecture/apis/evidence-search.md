# Evidence Search

`api/evidence-search` recovers specific documents for RAG validators. It does not uncover authorities, does not classify domains, and does not consult `source-router`.

## Contract v2

`POST /search/evidence` recibe:

- `assertion`: Full `assertions-document-v2` assertion.
- `origin_document`: URL/dominio of the news, or both to `null` if unknown.
- `search_policy`: A RAG strategy, boundaries and `preferred_sources`.

There are only three strategies:

| Estrategia | Dominios | Plan |
|---|---|---|
| `LOCAL` | Required `preferred_sources` produced by Source Router | Restricted search and refill within those same domains |
| `EXT_OFFICIAL_FIRST` | No acepta `preferred_sources` | Preferential official request and then general search |
| `EXT_ONLY_OFFICIAL` | No acepta `preferred_sources` | Official single request and subsequent deterministic filter by `source_type` |

`NONE` does not exist. The autonomous web search is already represented by `LLM_SEARCH_VALIDATION` and does not go through this service.

The answer contains the plan executed as structured objects, the resolution of normalized domains and evidences. Each evidence retains `source_type`, `authority_level`, `route_score`, `profile_version` and `relationship_to_origin`. The original document may appear as context, but grounding does not admit it as independent decisive evidence.

A source is only citationable when Evidence Search downloads the document, extracts its text and generates contexts with `context_id`, `text_sha256`, `origin=fetched_document` and `citation_eligible=true`. If the download fails or the extracting of text is disabled, URL, title and snippet are preserved for diagnosis, but `contexts` is empty and `citation_status=unavailable`. A supplier snippet does not constitute documentary evidence of a citation.

The retrieval pipeline detects HTML, PDF and textual payloads from their content before trusting the HTTP header. Each source reports the effective format/extractor, HTTP status, downloaded bytes, individual attempts and a stable failure object (`stage`, `code`, `retryable`). Candidate selection is round-robin by domain and limits concentration from one host.

If the first documents do not yield enough citationable contexts, the service performs one refill round without relaxing the active source policy: `LOCAL` remains inside the routed domains and `EXT_ONLY_OFFICIAL` remains official-only. The response exposes `retrieval_summary` (budgets, extracted/citationable documents, failure counts and stop reason) and `cache_policy`.

The validator selects only `context_id`; it does not control the URL or the text that persists. Validate Asers reconstructs `evidence_used` from the canonical context and rejects missing or ambiguous identifiers.

MongoDB only saves `evidence_search_cache_v2` with TTL. The key includes standardized assertion, origin, full strategy, routed profiles and search backend settings, including the retrieval contract version. Changing any of them separates the cache entry. Positive responses use the normal TTL; empty or retryable failures use a short negative TTL; non-retryable unusable documents use an intermediate TTL. The new version does not reuse old responses, so it does not require deleting the collection.

Relevant tuning variables are `EVIDENCE_CANDIDATE_MULTIPLIER`, `EVIDENCE_MAX_RESULTS_PER_DOMAIN`, `EVIDENCE_TARGET_CITABLE_SOURCES`, `EVIDENCE_SEARCH_TRANSIENT_FAILURE_TTL_SECONDS` and `EVIDENCE_SEARCH_UNUSABLE_TTL_SECONDS`.

`DELETE /admin/cache` empties that cache exclusively. Old collections are removed by `scripts/k8s/realign-source-routing-mongodb.sh`.
