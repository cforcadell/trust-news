import json

from common.llm import LLMRequest, acomplete, parse_structured_json
from common.search.normalization import normalize_domain

from .config import Settings
from .models import CandidateSource, ClassificationBatch, ResolveRouteRequest, RouteSignature, SourceClassification


CLASSIFIER_PROMPT = """You classify discovered web sources for routing factual evidence searches.
Return exactly one JSON object with a top-level \"classifications\" array.
Return one classification for each candidate and only candidates in the input. Never return a bare JSON array.
Do not decide eligibility, selection, ranking, or truth. Do not add domains.
Use structured jurisdiction codes and applicable_country_codes when supported by the candidate metadata.
Allowed match values: exact, partial, none, unknown.
Input:\n{payload}"""


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
    response = await acomplete(
        settings.llm_provider,
        LLMRequest(
            prompt=CLASSIFIER_PROMPT.format(payload=json.dumps(payload, ensure_ascii=False)),
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            response_schema=ClassificationBatch.model_json_schema(),
            response_model=ClassificationBatch,
        ),
    )
    batch = parse_structured_json(response.content, ClassificationBatch)
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
