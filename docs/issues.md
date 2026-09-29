# Incidences of Assermetry

Review: **2026-09-29 (`d051f18`)**. Cumulative inventory of findings and closure criteria for [v0.0.13](version.md). This revision checks the current repository, the external review supplied with this update, focused local evidence and the saved evaluation campaign. It is not a complete regression or a target-environment acceptance. 011, 012 and 018 are recorded as deployed in Hetzner; local implementation and deployment alone do not establish every closure check.

Execution order and benchmark protocol: [working.md](working.md).

## Management

States: **Open → In progress → Pending validation → Solved**. **Mitigated** retains the cause; a failed validation reopens the incidence. **Discarded** requires justification. Each change records commit, case, environment and evidence; no credentials or personal data are saved.

Gravity: **P0** Critical/loss commitment of datos/indisponibilidad; **P1** Safety, flow or incorrect essential result; **P2** Degradation with alternative; **P3** Cosmetics. Work order and blocking are decided separately. 005–008 move from historical P0 to P1 by functional impact: continuing blocking the cloud of 13, except for validating 008. Its urgency is not reduced.

| ID | Gravedad | Current status/evidence | Objective |
| --- | --- | --- | --- |
| 001 | P1 | Mitigado; concurrencia pendiente | 13 |
| 002 | — | Solved 2026-08-19 | History |
| 003–004 | P1 | Open; CI configuration confirmed, formal deferral from 13 pending | 16 proposed |
| 005 | P1 | Open; reproduced in GUI and functions | 13 |
| 006 | P1 | Open; confirmed contradiction in rendering | 13 |
| 007 | P1 | Pending validation; local solution, target deployment evidence pending | 13 |
| 008 | P1 | Pending validation; exclusion of errors already implemented | 13 |
| 009 | P1 | Open; optional edition already exists | 14 |
| 010 | P1 | Open; detailed evidence already exists | 14 |
| 011 | P1 | Pending validation; deployed, two-identity target evidence pending | 13 |
| 012 | P1 | Pending validation; deployed, negative-token target evidence pending | 13 |
| 013 | P1 | Pending validation; canonical grounding local, target pending | 13 |
| 014 | P1 | Open; confirmed in local code/probes | 13 |
| 015 | P1 | Pending validation; local LIGHT route checked, target pending | 13 |
| 016 | P1 | Open; incomplete dependencies and mobile/HTTP assertions | 13 |
| 017 | P1 | In progress; benchmark infrastructure exists, representative corpus and thresholds pending | 13, expand by 14 |
| 018 | P1 | Pending validation; deployed, browser link check pending | 13 |
| 019 | P1 | Pending validation; local polling fix, partial/duplicate matrix missing | 13 |
| 020 | P2 | Open; document width captured but overflow is not asserted | 13 |
| 021 | P1 | In progress; canonical grounding and official filter applied, PDF and independence pending | 13 |
| 022 | P2 | Pending validation; taxonomy/route-v2 local, Hetzner and cache measurements pending | 13 |
| 023 | P1 | Pending validation; local BLOCKCHAIN E2E passed, target pending | 13 |

Unclosed P1 findings targeted at 13 block its closure. 003/004 are proposed for 16 but still require a recorded owner, mitigation and explicit deferral decision for 13; private-demo scope is not automatic risk acceptance. 009–010 block the review/evidence experience of 14. 020 must pass an actual overflow check before mobile accreditation. 022 must complete target deployment and route/cache measurements before the route cache is considered stable.

## Incidencias previas, revisadas

### ISSUE-001 - Initialization career in the LIGHT validator cache

- **Falazgo:** a set boot selected one of three validators.
manual soda recovered nine validations for three assertions.
- **Review:** `load_validators_cache_from_chain` replaces cache even
for an empty list; it does not credit limited freshness or coordination with events. The current LIGHT 3×3 passes, but does not prove a concurrent restart.
- **Close:** shared soda, last valid cache conservation, events
Concurrent lossless and step-up 3×3 without intervention in Kind and Hetzner. Source: `api/news-handler/main.py`.

### ISSUE-002 - Secret OIDC no vacio como valor por defecto en tests

- **Resolved:** deleted default value; operator confirmed that it was not
productive secrecy. No productive rotation is required for this finding.
- **Follow-up:** check by secure means if the historical test card
remains active; the fixture must still fail soon if configuration is missing (016).

### ISSUE-003 - IC does not authenticate the K3s API with its CA

- **Confirmado:** `.gitlab-ci.yml` conserva `--insecure-skip-tls-verify=true`.
- **Close:** verify the K3s API CA and TLS name and reject a wrong CA or server name before deployment. v0.0.16 is the proposed implementation target; v0.0.13 still needs an explicit owner, mitigation, private-demo scope and risk decision before deferral.

### ISSUE-004 - CI does not set the server SSH key

- ** Confirmed:** `.gitlab-ci.yml` feeds `known_hosts` from `ssh-keyscan`.
- **Close:** pin the independently verified host key, reject a missing or changed key and document rotation. v0.0.16 is the proposed implementation target; record the v0.0.13 risk decision and demo restriction before deferral.

### ISSUE-005 - Dates, time zones and time states inconsistent with the results GUI

- **Reproduced:** Blockchain activity at 19:16 and last update to
21:16. `parseEventTimestamp` interprets `04/09` as April; the command parser interprets it as September.
- **Close:** API UTC ISO 8601 with area; single parser and local presentation
ES/EN, with zone tests, time change and events. Decision goes to 006.

### ISSUE-006 - provisional/final status mixed in process screen

- ** Confirmed:** `renderOrderProcess` keeps the provisional card without
completion condition; other parts show definitive result for any state starting with `VALIDATED`, including errors.
- **Close:** distinguish process, sufficiency of evidence and decision; messages
At the end, with errors, without evidence and without consensus.

### ISSUE-007 - Global verification and consensus calculation do not explain draws or decisions

- ** Status:** locally resolved and validated (2026-09-07).
display and check with real LIGHT/BLOCKCHAIN paths in browser.
- **Cause:** `calculate_assertion_result` normalized the accumulated by number of
answers and selected with `max` between TRUE/FALSE/UNKNOWN. The tie was resolved in order of keys, UNKNOWN competed as factual statement and the GUI reused the scores as percentages without explaining the decision.
- ** Implemented policy:** `consensus-v2`, centralized in
`api/common/utils/scoring.py`, with minimal decisive coverage `0.5` (required to be strictly superior) and `tie_epsilon=1e-9`. Distinguish `CONSENSUS`, `WEIGHTED_MAJORITY`, `NO_CONSENSUS`, `INSUFFICIENT_EVIDENCE` and `NO_VALID_RESPONSES`; UNKNOWN is abstaining and ERROR is excluded.
- **Contract:** adds `verdict`, `decision_status`, `reason_code`, gross weights,
decisive weight quota, coverage, abstention, margin, counting and policy version. `winner` and `scores` are preserved as legacy aliases: `winner` is null and void without factual decision and `scores` now represents gross weights, not probabilities or the previous average.
- **Reproducibility:** the new LIGHT and BLOCKCHAIN responses keep type,
Type weight, reputation, effective weight and `validator-weights-v1`. Previous records maintain the fallback to current cache/configuration and are identified by `legacy_dynamic_weight=true`; do not rewrite Blockchain or MongoDB.
- **GUI:** presents motive, decisive votes, abstentions, errors and weight
TRUE/FALSE/UNKNOWN in ES/EN. Percents are labeled as weight quota decisivo/completado. The documentary and state is conservative (`SUPPORTED`, `CONTRADICTED`, `MIXED`, `PARTIALLY_VERIFIED`, `INCONCLUSIVE`); FALSE+UNKNOWN is partial and not "Demented".
- **Exams:** 38 Python focused tests and Node consensus suites,
Status and evidence pass. Python regression: **181 PASS, 2 FAIL**; the known bugs of 015 and 016 remain exactly. JS syntax correct.
- **Pending for ISSUE-017:** calibration with evaluation corpus,
`min_winner_share` or other statistical thresholds, and `HUMAN=0.1` weight review. That value does not express automatic epistemological authority.

### ISSUE-008 - Timeout Validators treated as a valid result

- **Delivered advance:**backend, models and GUI distinguish `ERROR`; tests
The original diagnosis no longer describes the entire current code.
- **Pending:** induce real timeout in LIGHT/BLOCKCHAIN and validate message,
count, final status and absence of voto/evidencia; try individual retry without duplicates. The final presentation is coordinated with 006 and 019.

### ISSUE-009 - Extraction flow and unrevisable statement classification

- **Advance:** `renderEditableAssertionsTable` allows editing texto/categoria,
add and delete. It remains available to publish directly; the human revision path is not guaranteed or covered by regression.
- **Close at 14:** human path text → extraction → revision → confirmation
→ validation; explicit automatic API. Test units, dates, denial, composite statements and context; do not confuse category with truthfulness.

### ISSUE-010 - Result does not present main evidence or reusable report

- **Advance:**There are Evidences, Fragments and Link-by-Validator tabs.
The main summary by statement and the reusable report are missing.
- **Close on 14:** original text, verdict, source, date, fragment and
Visible and exportable limitations. Differentiate Blockchain traceability from factual evidence; use "Check Content" consistently.

## Hallazgos nuevos — 2026-09-05

### ISSUE-011 - Consultation of validations without effective isolation

- ** Status:** resolved and deployed in Hetzner (2026-09-06).

- **Cause:** Gateway omitted identity in `/validators/cache/{hash}/validations`;
News Handler assumed `admin=True` and could return orders from others.
- **Implementado:** Gateway deriva el propietario del token y codifica los
filters; News Handler requires identity and filters validations, texts, links and statistics. The `admin` parameter does not expand access, nor does `trust-admin`.
- **Local validation:**15 HTTP Gateway tests → News Handler with two
owners and simulated collections; include subpoenas by parameters, missing identity, empty scope and orphan orders.
- **Pending evidence:** repeat the deployed Gateway → News Handler flow with two real identities and preserve results for indirect links and exports. This internal endpoint relies on identity transmitted by Gateway and must remain internal. Organizations are single-user in the current model; do not infer isolation of routes not exercised.

### ISSUE-012 - JWT without audience validation or client presenter

- ** Status:** resolved and deployed in Hetzner (2026-09-06).

- **Original cause:** `get_current_user` disabled `aud` validation and
did not require a list of `azp/client_id`. Source: `api/gateway/main.py`.
- **Implemented:** mandatory `TrustNewsGateway` audience and client list
Local verification: 6 helpers tests and 11 JWT probes signed correctly; the latter are not yet incorporated into the suite.
- **Target validation:** confirm Keycloak configuration and negative tokens for both client presenters in Hetzner. The reconciliation script also needs a portable `sh` check because local `sh -n` rejects its `<<<` syntax.
- **Cierre:** audiencia `TrustNewsGateway`, presentadores permitidos
  (`TrustNewsWeb` y `TrustNewsApi`) y pruebas negativas de token válido para
  otra API/cliente. Las organizaciones son uniusuarias; no se introduce un
  modelo adicional de roles organizativos.

### ISSUE-013 - Verdicts without proven evidence and automatic attribution

- **Locally valid (2026-09-06):**RAG requires URL, fragment and membership
A documentary verdict TRUE/FALSE without support is degraded to UNKNOWN; invented, empty or foreign to the corpus is rejected. Retrieved evidence, `evidence_used` and `sources_declared` are distinguished.
- **Types:** memory and delegated search can emit a signal without sources,
identified respectively as `MODEL_KNOWLEDGE` and `PROVIDER_SEARCH_UNVERIFIED`; not presented as documentary evidence. RAG retains only proven evidence.
- **Evidence:** Grounding tests, contracts and UI; LIGHT order
`943346a6-1071-45f2-b97c-f10d746c150a` executed with three RAG validators and persistence of verificadas/rechazadas evidence in MongoDB.
- **Reinforcement implemented (2026-09-19, `d7b4308`):** the model reference
must include a unique, citationable, and server-created `context_id`. URL, title, text, hash and public chunk are reconstructed exclusively from that canonical context. Recovered ambiguos/no identifiers, non-citationable text and sources that are the original document are rejected; the supplier snippets are left as a diagnosis, never as an citation.
- **New local validation:**27 grounding and Evidence Search tests pass;
cover invented, ambiguous, non-quota context, injected URL/texto and original source. The cache incorporates `citation_contract=retrieved-context-id-v1` to prevent the reuse of incompatible responses.
- **Formal closure:**E of the three types and routes
Kafka/IPFS/MongoDB/navegador, especially BLOCKCHAIN and the target environment. The semantic implication check between affirmation and quote is maintained as scope of ISSUE-017.
- **Limit discovered:** check that an appointment belongs to the corpus does not prove
Independency and quality of the source. Self-confirmation and documentary eligibility are separated in ISSUE-021 so as not to reopen the scope already implemented.

### ISSUE-014 - Summary breaks with missing weighted results

- **Reproduced:** `buildVerificationSummary` declares the number
`completedValidations` and then try calling it a function; an unweighted validation command releases `TypeError`.
- **Close:**correct collision and render old, partial and with orders
only errors without exception. Source: `web_classic/app/js/app.js`.

### ISSUE-015 - Local selection of sources without accredited regional relevance

- ** Status:** locally resolved and validated; MongoDB was re-established in
`kind-trust-news`. Pending deployment and execution with external suppliers.
- **Deleted cause:** `LOCAL` used a massive static allowlist without
Proven regional relevance. Evidence Search mixed domain selection and recovery, and could manufacture placeholders without supplier.
- **Implyd:** internal microservice `source-router`; current discovery by
`common/search`, a batch classification by `common/llm`, rejection of invented domains, strict geographical eligibility, deterministic ranking and `source_routes_v2` FRESH/STALE/MISSING. memory Validators orchestrate `source-router → evidence-search(preferred_sources)` only for RAG+LOCAL.
- **Deleted:**Static perfiles/seeds/generadores and collections
`evidence_domain_profiles`/`evidence_normalization_configs`. Bootstrap explicitly removes them. External RAG strategies are maintained as `EXT_OFFICIAL_FIRST` and `EXT_ONLY_OFFICIAL`; `NONE` is removed.
- **Validation:** unit tests cover regional, national and EU routes,
standard signature, FRESH cache, stale failback, rejection of invented domains and `router -> evidence-search` order. The script was applied and double-checked on local MongoDB. The E2E LIGHT of 2026-09-19 resolved four `FRESH` routes and restricted search to their domains before calling Evidence Search; all 12 validators ended and the order was left `VALIDATED`. It was not repeated in BLOCKCHAIN and the target environment.
- **Follow-up:** Italian route classified
`gazzettaufficiale.biz` as `OFFICIAL_GAZETTE/NATIONAL_PRIMARY` at `gazzettaufficiale.it` level. You must correct the profile or enter a denial of mirror before considering stable documentary eligibility.
- **Limit remaining:** PDF extraction and fine documentary classification is
they are dealt with in ISSUE-021; the stability of the signature is resolved in ISSUE-022.

### ISSUE-016 - Regression with false positives and incomplete diagnosis

- **Confirmed:** the mobile E2E now captures `documentSize.width` and viewport size, but its `mobile-viewport` check only asserts the viewport dimensions; it does not fail on `scrollWidth > innerWidth`. The historical 847 px document in a 390 px viewport remains unaccredited. Earlier Blockchain checks could accept HTTP 500, and early exits could miss HTTP/console failures in the summary.
- **In addition:** the log test uses `caplog` and the search request was rechecked. `tests/api/requirements.txt` contains only `aiokafka`, `pytest` and `pytest-asyncio`; it does not assemble the full API test dependency set. The fixture still needs a fail-fast credential check.
- **Test 2026-09-19:** isolated tests of grounding/busqueda (27),
scoring (29) and polling GUI (3) pass, but the 12 `test_validator_source_orchestration.py` tests do not even load scholarship the virtual testing environment does not contain `hexbytes`. This confirms the reproducible environment defective; a green global baseline should not be published.
- **Close:** one reproducible command from a clean environment for API, frontend and contract checks; fail on HTTP/console errors and on `document.documentElement.scrollWidth > window.innerWidth` at 390 px; collect diagnostics in `finally`. Record effective identity, deployed revision and metadata. Prove the LIGHT and BLOCKCHAIN paths separately.

### ISSUE-017 - Representative evaluation of factual quality and adverse content

- **Current state:** benchmark infrastructure now exists: the historical OpenRouter CLI records profiles, repeated LIGHT orders, SQLite history, cost/latency estimates and comparisons; shared evaluation runners provide full, gold-domain, gold-evidence and replay modes, versioned artifacts and offline `--analyze` per validation. See [evaluation.md](tests/evaluation.md) and [llm-benchmark.md](tests/llm-benchmark.md). This is implementation progress, not factual-quality certification.
- **Coverage gap:** the current `eu-news-2025-v1` and `eu-official-statistics-2025-v1` cases contain four and three synthetic assertions respectively. They lack a representative human-reviewed TRUE/FALSE/UNKNOWN corpus, reviewed source/domain annotations, adversarial content and thresholds agreed before scoring. The synthetic population fixture checks arithmetic and abstention only.
- **Observed evaluation:** the 2026-09-29 three-repetition official-statistics run saved 27 validator records and five upstream HTTP 429 failures. The recovered pipeline report marks 2/9 assertion/repetition units end-to-end correct under its strict technical/error criteria. It cannot establish product quality or routing correctness: the case has no reviewed acceptable domains or reference sources. The artifacts are local and Git-ignored until retained durably.
- **Close:** create a versioned, human-reviewed corpus with TRUE/FALSE/UNKNOWN, dates, quantities, negation, attribution, primary and secondary evidence, PDFs, insufficient evidence and adversarial instructions. Measure extraction, domain selection, retrieval, citation eligibility and semantic support, verdict errors, abstention, latency and cost. Define acceptance thresholds and a simple LLM plus web-search comparison before measuring; run repeated frozen-evidence and full-pipeline evaluations. Extend coverage through v0.0.14 without postponing the minimum v0.0.13 quality gate.

### ISSUE-018 - Evidence links without validating the schema

- ** Status:** resolved and deployed in Hetzner (2026-09-06).

- **Reproduced in isolated rendering:** `renderEvidenceLinks` conserves
`href="javascript:void(0)"`; `safeText` escapes HTML, but does not validate protocols. The model accepts fonts as free dictionaries. A payload has not been executed in the browser nor tested exploitation with the deployed CSP.
- **Close:** accept HTTP(S) only on server and client; inert text for URLs
invalid; tests with dangerous schemes and malformed links.
- **Impplemented (2026-09-06):** sanitation in evidence models and
Link validation in rendering. Malformed URLs do not invalidate the entire object; they are preserved in `url_text`/`source_url_text`, only to display escaped text. Absent or invalid hosts, invalid ports, dangerous schemas and ambiguous characters are rejected.
- **Local validation:** 38 URL/model Python tests and 15 rendering tests passed in the recorded run. The fix is recorded as deployed in Hetzner; preserve a browser check of invalid and valid links before marking target validation complete.

### ISSUE-019 - Total of contradictory validations during the process

- **Noted in Blockchain:** two statements, six pending and card
‘0/4’. `buildVerificationSummary` prioritizes partial requests over other counts. It can produce premature percentages or messages.
- **Close:** an authoritative source for esperadas/recibidas/error/pendientes;
always total=received+pending, not exceeding 100 %. Prove partial arrival, duplicates and retrying in both modes.
- **Locally implemented (2026-09-19, `d7b4308`):** the summary prioritizes the
Complete validation requests, calculates pending as the maximum between the persistent field and the difference against the completed ones, and the polling tab retains the Process until you have a clean terminal render. The three estado/polling Node tests pass. The closing matrix is missing: partial arrival, duplicates, retrying, induced error and both modes.

### ISSUE-020 - Mobile overflow and inconsistent interface language

- **Reproduced:** 847 px document with 390 px viewport in LIGHT and
BLOCKCHAIN; navigation occupies much of the screen and the warning comes out of the visible width. In Spanish, "valid", "errors" and "Publish News" appear.
- **Close:** without horizontal page scroll at 390 px, compact navigation,
Content warnings and accessible result; ES/EN complete and consistent actions. Validate keyboard and focus, not just viewport size.

## Hallazgos nuevos — 2026-09-11

### ISSUE-021 - A recovered source can self-confirm the news and circumvent documentary policy

- ** Status:** partially resolved. Reproduced in the LIGHT order
`355f6090-cec0-4ed3-a29a-46763fe66cc6`, first assertion.
- **Impact:** all three RAG validators issued TRUE using the
The quotation is literal and surpasses the ISSUE-013 grounding, but it is not independent corroboration.
- **Original causes:** the original URL is lost after importing the text; Source Router
allows media if they comply with jurisdiction; `EXT_ONLY_OFFICIAL` guides the provider but does not filter its response; the validator passes only domains to Evidence Search and loses metadata; the recoverer rejects PDF, so the primary localized IEA report did not provide usable context.
- **Close:** propagate source URL/dominio; classify primary source,
secondary, copy and relationship to the document submitted; apply the policy after recovering results; keep metadata from the router; extract PDF with page and auditable error. A submitted source or copy cannot be the only decisive evidence. For a claim attributable to a study, the primary document recovered or the actual verdict is UNKNOWN.
- **Implemented:** origin URL/domain travel in `v2` contracts; Evidence Search retains source type, authority, score, profile version and relation to origin; `EXT_ONLY_OFFICIAL` filters after retrieval. Grounding rejects `relationship_to_origin=ORIGINAL` against the canonical `context_id`, so a free model URL/text/hash cannot bypass that check.
- **Remaining mechanism:** `document_type` is still `UNKNOWN`; same URL becomes `ORIGINAL`, same domain `UNKNOWN`, and another domain `INDEPENDENT`. Different domains can repeat the same wire story or study, so this classification is not proof of independence. PDF extraction with page and auditable fragment, copy/derived-source detection and a primary-source rule for attributed claims remain open.
- **Return:** the order indicated should prioritize and quote the IEA report.
This cannot be recovered, Freedom Digital can be preserved as context or track, without producing TRUE/FALSE documentary alone.
- **Relationship:** expands the factual quality of 017; does not invalidate grounding
Syntactic of 013 nor the geographical eligibility resolved by 015.

### ISSUE-022 - Subcategories and free types generate duplicate or too wide routes

- **Status:** pending validation. Closed taxonomy and `route-v2` are coded and the local `kind-trust-news` collections were realigned; Hetzner deployment, indexes and route/cache behavior still need evidence. Before the change, nearby combinations created different routes and free `subcategory` values fragmented the cache.
- **Impact:** synonyms, tildes, translations or variable choices create
new entries; at the same time, a broad thematic route can reuse sources discovered for a particular study. It increases cost and can degrade relevance without producing an explicit failure.
- **Causes:** the signature only normalizes spaces and capitals; there is no catalogue or
subcategories alias; `claim_type_for_assertion` can choose the first `preferred_source_type` in alphabetical order; authors and title influence discovery, but do not separate from thematic memory.
- **Implemented:** `subcategory` is removed and free values replaced
by `topic_code`, `evidence_kind`, `source_type`, `authority_level` and jurisdiction of `routing-taxonomy-v1`. Pydantic and JSON Schema reject invented values and combinations tema/categoria incompatible. The signature is `route-v2|taxonomy|topic|evidence|jurisdiction`; text, entity and date are left out of the thematic cache and used in the specific documentary search.
- **Realineamiento:** colecciones nuevas `source_routes_v2`,
`domain_profiles_v1` and `evidence_search_cache_v2`. The `scripts/k8s/realign-source-routing-mongodb.sh` idepotent script removes obsolete data, secures indexes and records the version; CI runs `--apply` and `--check`.
- **Close:** deploy the same revision and run MongoDB realignment in Hetzner; check indexes and prove that equivalent aliases share a key while distinct topics do not. Record new-route rate, reuse, collisions and `OTHER` candidates. Reopen design only if these checks expose an actual defect.

### ISSUE-023 - The BLOCKCHAIN registry loses the fields of the v2 assertions contract

- **Reproduced (2026-09-19):** the E2E GUI Blockchain published the order
`11ea41f6-c315-4c13-9ab8-00fbbcc686f0`, generated four assertions and uploaded the document to IPFS (`QmQrPwqsPZafEvCuZ1xvoTk5XwNk2Z4bQJ3QkoAd4eedBo`). The order was left in `BLOCKCHAIN_PENDING`, without `post_id` or `tx_hash`.
- **Cause:** after `ipfs_uploaded`, `news-handler` converts the v2 document with
`to_chain_assertion()` and delivers it to `RegisterBlockchainRequest`. That conversion retains only `idAssertion`, `text` and `categoryId`, while the `RegisterBlockchainPayload` model also requires `topic_code`, `evidence_kind` and `context`. The Pydatic validation rejects the four assertions and `handle_blockchain_request` captures the error; the flow continues to mark the order as pending although it never publishes `register_blockchain`.
- **Impact:** no post or transaction created and no request or receipt
Blockchain validations. GUI case cannot satisfy CID/post/tx/IPFS or reach `VALIDATED`.
- **Solution (2026-09-20):** `register_blockchain` uses now
`register-blockchain-v2` and transports only CID and publisher. `news-chain` recovers and validates IPFS `AssertionsDocumentV2`, derives its categories and sends only these to the existing contract. The response uses compact mappings and `news-handler` combines them with MongoDB canonical document. Request or registration failures persist as `BLOCKCHAIN_ERROR` with stage, code and retry capacity; no fictitious slope is announced.
- **Associated correction:** the listers of `news-chain` and
`validate-asertions` unpack IPFS `{cid, content}` response before validating V2; an invalid event no longer ends the lister of a validator.
- **Closing validation:**28 focused tests pass.
`synthetic-blockchain-01` creó la orden `a237441b-f1aa-4c32-8468-fe79163f865c`, CID `QmNaWX2Ra7SKUzoswZERE7GGHwFpRxT3WZVwHaaWCbpXR3`, post `36` y transacción `0x019cff71a2bf46fea9a5840f7b1426ad1b0fa44eb740b779caea2e64861a051b`. Alcanzó `VALIDATED` con cuatro aserciones, doce validaciones y cero pendientes; comprobó pestaña IPFS, escritorio/móvil y ausencia de errores HTTP/consola inesperados. Artefactos: `/tmp/assermetry-e2e-blockchain-v2-retry-20260920`.
- **Limit:** This evidence is from the local cluster, not from the target environment.
