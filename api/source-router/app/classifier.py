import json

from common.llm import LLMRequest, LLMResponseError, acomplete, parse_structured_json
from common.routing_taxonomy import AuthorityLevel
from common.search.normalization import normalize_domain

from .config import Settings
from .models import CandidateSource, ClassificationBatch, ResolveRouteRequest, RouteSignature, SourceClassification


CLASSIFIER_PROMPT = """You classify discovered web sources for routing factual evidence searches.
Return exactly one JSON object with a top-level \"classifications\" array.
Return one classification for each candidate and only candidates in the input. Never return a bare JSON array.
Do not decide eligibility, selection, ranking, or truth. Do not add domains.
Classify stable domain properties (source_type, authority_level, jurisdictions, topics,
evidence kinds and languages) separately from this route's match fields.
The only allowed authority_level values are: {authority_levels}.
Use these exact authority_level values. For example, use NATIONAL_PRIMARY, never NATIONAL.
Use only enum values exposed by the JSON schema for every other taxonomy field. Never invent taxonomy values.
Allowed match values are EXACT, PARTIAL, NONE and UNKNOWN.
Input:\n{payload}"""

CLASSIFICATION_MAX_ATTEMPTS = 2


async def classify_candidates(
    signature: RouteSignature,
    request: ResolveRouteRequest,
    candidates: list[CandidateSource],
    settings: Settings,
) -> list[SourceClassification]:
    if not candidates:
        return []
    payload = {
        "route_signature": signature.model_dump(),
        "claim_metadata": request.model_dump(),
        "candidates": [item.model_dump() for item in candidates],
    }
    prompt = CLASSIFIER_PROMPT.format(
        authority_levels=", ".join(item.value for item in AuthorityLevel),
        payload=json.dumps(payload, ensure_ascii=False),
    )
    batch = None
    for attempt in range(CLASSIFICATION_MAX_ATTEMPTS):
        response = await acomplete(
            settings.llm_provider,
            LLMRequest(
                prompt=prompt,
                model=settings.llm_model,
                temperature=settings.llm_temperature,
                response_schema=ClassificationBatch.model_json_schema(),
            ),
        )
        try:
            batch = parse_structured_json(response.content, ClassificationBatch)
            break
        except LLMResponseError as exc:
            if attempt + 1 >= CLASSIFICATION_MAX_ATTEMPTS:
                raise
            prompt = (
                f"{prompt}\n\nYour previous JSON response failed schema validation:\n"
                f"{str(exc)[:1500]}\nCorrect the validation errors and return only the complete JSON object."
            )

    if batch is None:  # pragma: no cover - defensive guard
        raise LLMResponseError("Source classification produced no result")
    allowed = {normalize_domain(candidate.domain) for candidate in candidates}
    provider_scores = {normalize_domain(candidate.domain): candidate.provider_score for candidate in candidates}
    accepted: dict[str, SourceClassification] = {}
    for item in batch.classifications:
        domain = normalize_domain(item.domain)
        if domain not in allowed or domain in accepted:
            continue
        item.domain = domain
        item.provider_score = provider_scores.get(domain)
        accepted[domain] = item
    return list(accepted.values())
