import gettext

import pycountry

from common.routing_taxonomy import EvidenceKind

from .models import ResolveRouteRequest, RouteSignature


EVIDENCE_TERMS = {
    EvidenceKind.STATISTICAL_DATA: "official statistics data authority",
    EvidenceKind.LEGAL_TEXT: "official law legislation gazette",
    EvidenceKind.REGULATORY_DECISION: "official regulator decision",
    EvidenceKind.JUDICIAL_DECISION: "official court judgment",
    EvidenceKind.ELECTION_RESULT: "official election results authority",
    EvidenceKind.RESEARCH_PUBLICATION: "research publication study institute",
    EvidenceKind.COMPANY_DISCLOSURE: "official company disclosure filing regulator",
    EvidenceKind.SPORTS_RECORD: "official sports results governing body",
    EvidenceKind.WEATHER_OBSERVATION: "official weather climate observation authority",
    EvidenceKind.GOVERNMENT_RECORD: "official government record",
    EvidenceKind.PUBLIC_STATEMENT: "official statement transcript",
    EvidenceKind.PRIMARY_DOCUMENT: "official primary document",
    EvidenceKind.GENERAL: "authoritative primary source",
    EvidenceKind.UNKNOWN: "authoritative primary source",
}


SUPRANATIONAL_NAMES = {
    "EU": "European Union",
}


def _localized_iso_name(domain: str, name: str, language: str) -> str:
    language = str(language or "").strip().lower().replace("-", "_")
    if not language or language == "unknown":
        return name
    translation = gettext.translation(
        domain,
        pycountry.LOCALES_DIR,
        languages=[language, language.split("_", 1)[0]],
        fallback=True,
    )
    return translation.gettext(name)


def _iso_name_variants(name: str) -> list[str]:
    if name.endswith("]") and " [" in name:
        primary, alias = name[:-1].split(" [", 1)
        return [primary, alias]
    return [name]


def _jurisdiction_search_terms(signature: RouteSignature, request: ResolveRouteRequest) -> list[str]:
    jurisdiction = signature.jurisdiction
    terms: list[str] = []

    if jurisdiction.jurisdiction_code:
        terms.append(SUPRANATIONAL_NAMES.get(jurisdiction.jurisdiction_code, jurisdiction.jurisdiction_code))

    if jurisdiction.region_code:
        subdivision = pycountry.subdivisions.get(code=jurisdiction.region_code)
        if subdivision:
            terms.extend(_iso_name_variants(subdivision.name))
            terms.extend(_iso_name_variants(
                _localized_iso_name("iso3166-2", subdivision.name, request.language)
            ))
        else:
            terms.append(jurisdiction.region_code)

    if jurisdiction.country_code:
        country = pycountry.countries.get(alpha_2=jurisdiction.country_code)
        if country:
            terms.extend(_iso_name_variants(country.name))
            terms.extend(_iso_name_variants(
                _localized_iso_name("iso3166-1", country.name, request.language)
            ))
        else:
            terms.append(jurisdiction.country_code)

    return list(dict.fromkeys(term for term in terms if term))


def build_discovery_queries(signature: RouteSignature, request: ResolveRouteRequest) -> list[str]:
    jurisdiction = " ".join(_jurisdiction_search_terms(signature, request))
    topic = signature.topic_code.value.replace("_", " ").lower()
    return [" ".join(filter(None, (EVIDENCE_TERMS[signature.evidence_kind], topic, jurisdiction)))]
