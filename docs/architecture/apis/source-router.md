# Source Router

Internal service used exclusively by `RAG_EVIDENCE_VALIDATION + LOCAL`. Discover real domains, rank candidates with closed enums, apply geographic eligibility and deterministic ranking, and separate two memories in MongoDB:

- `domain_profiles_v1`: Stable Domain Properties (`source_type`,
`authority_level`, jurisdictions, topics, types of evidence and languages).
- `source_routes_v2`: reusable routes formed by `topic_code`,
`evidence_kind` and canonical jurisdiction; they contain only references and scores that are typical of that path.

```text
RouteSignature -> source_routes_v2 -> FRESH -> unir DomainProfile -> ranking
                                  `-> MISSING/STALE -> SearchProvider -> LLM batch
                                                     -> eligibility -> upsert
```

## API

`POST /routes/resolve` accepts `topic_code`, `evidence_kind`, `jurisdiction` and `language`. All except for the language are `routing-taxonomy-v1` closed vocabulary. Returns `route_key`, `route_state`, `router_version` and `sources[]` with domain, type, authority, jurisdictions, score, and profile version. A `FRESH` path does not make external calls.

The key is:

```text
route-v2|routing-taxonomy-v1|TOPIC_CODE|EVIDENCE_KIND|JURISDICTION_KEY
```

Text, entities and dates do not fragment this thematic memory. These data appear later in the specific query of Evidence Search.

`GET /routes` supports `route_key`, `topic_code`, `evidence_kind`, `jurisdiction_key` and `limit` filters. `GET /routes/{route_key}` recovers an exact route. Both endpoints are Mongo-only and never run Discovery or LLM.

## Resolution and interconnection flow

The usual caller is `validate-asertions`. For an assertion in LOCAL mode, build the payload from `assertion.topic_code`, `assertion.evidence_kind`, `assertion.context.jurisdiction` and the context language. `source-router` does not receive the text of the assertion, entities or dates: that data remains in `evidence-search` and is used when constructing the final query.

The resolution follows these steps:

1. `signatures.py` builds `RouteSignature` and the canonical `route_key`.
2. If there is a route whose `refresh_after` has not yet expired, your
domain profiles and recalculates the ranking without calling search engine or LLM.
3. For a `MISSING` or expired (`STALE`), `query_builder.py` generates the
Discovery query based on the type of evidence, subject and jurisdiction. ISO codes remain the internal representation and identity of the route, but expand to complete geographical names — including the variant of the language requested when available — before calling Exa or Tavily. `search_with_provider` doubles the results by standard domain.
4. `classifier.py` ranks all candidates in an LLM batch. The output is
valid per candidate against `SourceClassification`; LLM describes properties and compatibility, but does not decide the selection or veracity.
5. `eligibility.py` applies deterministic rules: theme matching and
evidence, type of source allowed by `EVIDENCE_SOURCE_TYPES`, jurisdictional coverage and authority other than `UNKNOWN`/`OTHER`.
6. Eligible ratings update `domain_profiles_v1` and become
in `RouteCandidate`. `ranking.py` commands them; the default limit is `SOURCE_ROUTER_MAX_SOURCES` (8).
7. The path is persistent and `ResolveRouteResponse` is returned.

The rear connection is unidirectional: `validate-asertions` passes `sources[]` as `search_policy.preferred_sources` to `evidence-search`; the latter creates requests with `include_domains` and never calls Source Router again. If LOCAL does not receive eligible sources, the search is omitted with `no_eligible_local_sources`.

## Contracts and metadata

The metadata deliberately separates between route identity, stable profile and selection decision:

- `RouteSignature` contiene `taxonomy_version`, `topic_code`, `evidence_kind`,
la `jurisdiction` completa y `jurisdiction_key`. La jurisdicción admite `GLOBAL`, `SUPRANATIONAL`, `COUNTRY`, `REGION`, `LOCAL` y `UNKNOWN`, con códigos validados según el ámbito.
- `DomainProfile` retains reusable domain properties: `source_type`,
`authority_level`, jurisdictions, topics, types of evidence, languages, `classification_confidence`, `classification_model`, `profile_version` and `last_verified_at`. The update combines previous and new coverage; a fallback does not prolong `last_verified_at`.
- `RouteCandidate` retains only the path dependent fields:
thematic and evidence coincidences, semantic relevance, supplier score, justification and `base_score`.
- `RoutedSource` is the metadata that crosses the boundary to Evidence Search:
domain, type, authority, jurisdictions, themes, supported evidence, languages, `route_score`, `rank`, `reason` and `profile_version`.

The `route_score` combines authority (30%), geographic specificity (25%), match of the type of evidence (16%), theme (14%), semantic relevance (8%), rating confidence (5%) and vendor score (2%). A bonus of 0.03 is added when the requested language is on the profile. The draws are resolved by domain to maintain reproducible results.

Evidence Search recopy this metadata in every evidence: `source_type`, `authority_level`, `route_score`, `why_selected` and `profile_version`. It also calculates `relationship_to_origin` (`ORIGINAL`, `INDEPENDENT` or `UNKNOWN`), so that evidence and decision of routing remain auditable from end to end.

The classifier cannot add domains or decide truthfulness. A candidate with the theme or evidence `NONE`, desconocida/no authority admitted or incompatible jurisdiction is ruled out. A failed refresh can reuse a `STALE` path; a failed `MISSING` does not manufacture domains.

## Partial classification and recovery

The LLM response is validated by candidate. Valid domains are retained between attempts; a correction is requested only of invalids or omitted ones, with a maximum of two calls. A format or supplier error in the second attempt also does not eliminate the valid results of the first attempt. Domains that do not appear in the discovery are not accepted.

The prompt explains the restrictions of each jurisdiction. Standardisation only eliminates unequivocal redundancys (e.g., `COUNTRY/ES` with `jurisdiction_code=ES`). It does not remove a real region or invent absent codes or member countries of a supranational entity; such cases require correction of the classifier.

For discovered domains whose classification fails, existing profiles of `domain_profiles_v1` can be reused. They must have the same version of the router, a more recent verification than `SOURCE_ROUTE_REFRESH_SECONDS`, include theme and type of evidence, and exceed the rules of authority, source type, and jurisdiction. This recovery does not update the date of profile verification. It does not incorporate domains without classifying or changing LOCAL to external search.

Partial or recovered routes carry `degraded=true` and expire in up to five minutes to allow reconstruction. The diagnosis is preserved in MongoDB and cache responses. An answer without eligible candidates does not create an empty route with 30 days expiration; if there is an earlier route it is reused as `STALE`.

`diagnostic_code` distinguishes `CLASSIFICATION_PARTIAL`, `CLASSIFICATION_FAILED`, `PROFILE_FALLBACK`, `NO_DISCOVERY_CANDIDATES` and `NO_ELIGIBLE_SOURCES`. `diagnostics` lists domains that have been discovered, classified, rejected by eligibility, failed and recovered from profiles. The validator keeps these fields in `evidence_search_response.route`, and continues to look for evidence when the degraded response contains sources.

Logs include the path key, query and URLs of the discovery, errors per candidate and the JSON of the rejected candidate (limited to 4000 characters). The complete raw response of the supplier is not stored. This trace allows to distinguish absence of results, schema errors and eligibility rejections.

Persistence variables: `SOURCE_ROUTES_COLLECTION=source_routes_v2`, `SOURCE_DOMAIN_PROFILES_COLLECTION=domain_profiles_v1` and `SOURCE_ROUTER_VERSION=source-router-v2`.

`SOURCE_ROUTER_DISCOVERY_MAX_RESULTS` controls the candidates requested by the router (12 default). The shared search layer respects that value; `SEARCH_PROVIDER_MAX_RESULTS` is only a common technical guardrail (50 default), not the functional limit of Evidence Search.
