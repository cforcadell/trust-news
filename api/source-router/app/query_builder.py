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


def build_discovery_queries(signature: RouteSignature, request: ResolveRouteRequest) -> list[str]:
    jurisdiction = " ".join(filter(None, (
        signature.jurisdiction.jurisdiction_code,
        signature.jurisdiction.region_code,
        signature.jurisdiction.country_code,
    )))
    topic = signature.topic_code.value.replace("_", " ").lower()
    return [" ".join(filter(None, (EVIDENCE_TERMS[signature.evidence_kind], topic, jurisdiction)))]
