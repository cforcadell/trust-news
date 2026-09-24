import json
import logging

from pydantic import ValidationError

from common.llm import LLMProviderError, LLMRequest, LLMResponseError, acomplete, parse_structured_json
from common.routing_taxonomy import AuthorityLevel
from common.search.normalization import normalize_domain

from .config import Settings
from .models import CandidateSource, ClassificationBatch, ResolveRouteRequest, RouteSignature, SourceClassification
from .signatures import route_key


logger = logging.getLogger(__name__)


class ClassificationResults(list):
    """Valid classifications plus unresolved domains for retries and auditing."""

    def __init__(self, values, failed_domains):
        super().__init__(values)
        self.failed_domains = sorted(failed_domains)


def normalize_classification(row):
    """Repair redundant codes only; never expand geographic coverage."""
    if not isinstance(row, dict):
        return row
    result = dict(row)
    jurisdictions = result.get("jurisdictions")
    if not isinstance(jurisdictions, list):
        return result
    result["jurisdictions"] = []
    for value in jurisdictions:
        if not isinstance(value, dict):
            result["jurisdictions"].append(value)
            continue
        value = dict(value)
        scope = str(value.get("scope") or "").strip().upper()
        value["scope"] = scope
        country = str(value.get("country_code") or "").strip().upper()
        code = str(value.get("jurisdiction_code") or "").strip().upper()
        region = str(value.get("region_code") or "").strip().upper()
        if scope == "COUNTRY" and country:
            if code == country:
                value["jurisdiction_code"] = None
            countries = value.get("applicable_country_codes")
            if isinstance(countries, list) and countries and all(
                str(item).strip().upper() == country for item in countries
            ):
                value["applicable_country_codes"] = []
        elif scope == "REGION" and region and code == region:
            value["jurisdiction_code"] = None
        result["jurisdictions"].append(value)
    return result


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
Jurisdiction rules (null means JSON null, not a string):
- COUNTRY: country_code is required; region_code and jurisdiction_code must be null;
  applicable_country_codes must be [].
- REGION: country_code and region_code are required; jurisdiction_code must be null;
  applicable_country_codes must be [].
- LOCAL: country_code, region_code and jurisdiction_code are required;
  applicable_country_codes must be [].
- SUPRANATIONAL: jurisdiction_code is required (for example EU); country_code and
  region_code must be null; applicable_country_codes lists supported member countries.
- GLOBAL and UNKNOWN: all codes must be null and applicable_country_codes must be [].
Use the source's actual coverage. Never invent missing country or membership codes.
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
    allowed = {normalize_domain(candidate.domain) for candidate in candidates}
    provider_scores = {normalize_domain(candidate.domain): candidate.provider_score for candidate in candidates}
    accepted: dict[str, SourceClassification] = {}
    key = route_key(signature)
    for attempt in range(CLASSIFICATION_MAX_ATTEMPTS):
        try:
            response = await acomplete(
                settings.llm_provider,
                LLMRequest(
                    prompt=prompt,
                    model=settings.llm_model,
                    temperature=settings.llm_temperature,
                    response_model=ClassificationBatch,
                    # A malformed row must not discard valid classifications.
                    # The provider still receives the complete strict schema.
                    strict_response_validation=False,
                ),
            )
        except (LLMProviderError, LLMResponseError):
            if not accepted:
                raise
            logger.warning("Classification retry failed route_key=%s; retaining valid domains=%s", key, sorted(accepted), exc_info=True)
            break
        feedback = []
        try:
            batch = parse_structured_json(response.content)
            if not isinstance(batch, dict) or not isinstance(batch.get("classifications"), list):
                raise LLMResponseError("Expected an object containing a classifications array")
            for row in batch["classifications"]:
                domain = normalize_domain(str(row.get("domain") or "")) if isinstance(row, dict) else ""
                if domain not in allowed or domain in accepted:
                    continue
                try:
                    normalized = normalize_classification(row)
                    item = SourceClassification.model_validate(normalized)
                except ValidationError as exc:
                    detail = f"{domain}: {exc}"
                    feedback.append(detail)
                    logger.warning("Classification rejected route_key=%s domain=%s attempt=%s errors=%s input=%s",
                                   key, domain, attempt + 1, str(exc)[:2000], json.dumps(row, ensure_ascii=False)[:4000])
                    continue
                if normalized != row:
                    logger.info("Classification normalized redundant jurisdiction codes route_key=%s domain=%s", key, domain)
                item.provider_score = provider_scores.get(domain)
                accepted[domain] = item
        except LLMResponseError as exc:
            feedback.append(str(exc))
        missing = allowed - accepted.keys()
        if not missing:
            break
        prompt = (
            f"{prompt}\n\nYour previous JSON response failed schema validation or omitted candidates:\n"
            f"{' '.join(feedback)[:3000]}\nReturn corrected classifications only for: {', '.join(sorted(missing))}."
            " Use the jurisdiction rules above and return the complete JSON object."
        )

    missing = allowed - accepted.keys()
    logger.info("Classification finished route_key=%s accepted=%s failed=%s", key, sorted(accepted), sorted(missing))
    if not accepted:
        raise LLMResponseError(
            f"Source classification failed for domains: {', '.join(sorted(missing))}"
        )
    return ClassificationResults(accepted.values(), missing)
