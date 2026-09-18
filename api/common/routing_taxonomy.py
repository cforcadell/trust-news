from __future__ import annotations

from enum import Enum


TAXONOMY_VERSION = "routing-taxonomy-v1"


class TopicCode(str, Enum):
    ECONOMY_MACRO = "ECONOMY_MACRO"
    FINANCE_MARKETS = "FINANCE_MARKETS"
    BUSINESS_CORPORATE = "BUSINESS_CORPORATE"
    EMPLOYMENT = "EMPLOYMENT"
    TAXATION_PUBLIC_FINANCE = "TAXATION_PUBLIC_FINANCE"
    TRADE = "TRADE"
    HOUSING_REAL_ESTATE = "HOUSING_REAL_ESTATE"
    POLITICS_GOVERNMENT = "POLITICS_GOVERNMENT"
    ELECTIONS = "ELECTIONS"
    LAW_JUSTICE = "LAW_JUSTICE"
    SECURITY_DEFENCE = "SECURITY_DEFENCE"
    INTERNATIONAL_RELATIONS = "INTERNATIONAL_RELATIONS"
    HEALTH_PUBLIC_HEALTH = "HEALTH_PUBLIC_HEALTH"
    MEDICINE = "MEDICINE"
    SCIENCE_RESEARCH = "SCIENCE_RESEARCH"
    TECHNOLOGY = "TECHNOLOGY"
    CYBERSECURITY = "CYBERSECURITY"
    ENVIRONMENT = "ENVIRONMENT"
    CLIMATE = "CLIMATE"
    ENERGY = "ENERGY"
    AGRICULTURE_FOOD = "AGRICULTURE_FOOD"
    EDUCATION = "EDUCATION"
    DEMOGRAPHY = "DEMOGRAPHY"
    MIGRATION = "MIGRATION"
    SOCIAL_WELFARE = "SOCIAL_WELFARE"
    TRANSPORT_INFRASTRUCTURE = "TRANSPORT_INFRASTRUCTURE"
    SPORTS = "SPORTS"
    CULTURE = "CULTURE"
    ENTERTAINMENT = "ENTERTAINMENT"
    CRIME_PUBLIC_SAFETY = "CRIME_PUBLIC_SAFETY"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class EvidenceKind(str, Enum):
    STATISTICAL_DATA = "STATISTICAL_DATA"
    LEGAL_TEXT = "LEGAL_TEXT"
    REGULATORY_DECISION = "REGULATORY_DECISION"
    JUDICIAL_DECISION = "JUDICIAL_DECISION"
    ELECTION_RESULT = "ELECTION_RESULT"
    RESEARCH_PUBLICATION = "RESEARCH_PUBLICATION"
    COMPANY_DISCLOSURE = "COMPANY_DISCLOSURE"
    SPORTS_RECORD = "SPORTS_RECORD"
    WEATHER_OBSERVATION = "WEATHER_OBSERVATION"
    GOVERNMENT_RECORD = "GOVERNMENT_RECORD"
    PUBLIC_STATEMENT = "PUBLIC_STATEMENT"
    PRIMARY_DOCUMENT = "PRIMARY_DOCUMENT"
    GENERAL = "GENERAL"
    UNKNOWN = "UNKNOWN"


class JurisdictionScope(str, Enum):
    GLOBAL = "GLOBAL"
    SUPRANATIONAL = "SUPRANATIONAL"
    COUNTRY = "COUNTRY"
    REGION = "REGION"
    LOCAL = "LOCAL"
    UNKNOWN = "UNKNOWN"


class EntityType(str, Enum):
    PERSON = "PERSON"
    ORGANIZATION = "ORGANIZATION"
    GOVERNMENT_BODY = "GOVERNMENT_BODY"
    COMPANY = "COMPANY"
    PRODUCT = "PRODUCT"
    LAW = "LAW"
    STUDY = "STUDY"
    EVENT = "EVENT"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class EntityRole(str, Enum):
    SUBJECT = "SUBJECT"
    OBJECT = "OBJECT"
    SOURCE = "SOURCE"
    AUTHORITY = "AUTHORITY"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class TemporalType(str, Enum):
    DATE = "DATE"
    DATE_RANGE = "DATE_RANGE"
    YEAR = "YEAR"
    PERIOD = "PERIOD"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class SourceType(str, Enum):
    STATISTICAL_OFFICE = "STATISTICAL_OFFICE"
    CENTRAL_BANK = "CENTRAL_BANK"
    GOVERNMENT_AGENCY = "GOVERNMENT_AGENCY"
    OFFICIAL_GAZETTE = "OFFICIAL_GAZETTE"
    LEGISLATURE = "LEGISLATURE"
    COURT = "COURT"
    REGULATOR = "REGULATOR"
    ELECTORAL_AUTHORITY = "ELECTORAL_AUTHORITY"
    PUBLIC_HEALTH_AUTHORITY = "PUBLIC_HEALTH_AUTHORITY"
    INTERGOVERNMENTAL_ORGANIZATION = "INTERGOVERNMENTAL_ORGANIZATION"
    RESEARCH_INSTITUTION = "RESEARCH_INSTITUTION"
    ACADEMIC_PUBLISHER = "ACADEMIC_PUBLISHER"
    COMPANY = "COMPANY"
    ORGANIZATION = "ORGANIZATION"
    SPORTS_GOVERNING_BODY = "SPORTS_GOVERNING_BODY"
    NEWS_AGENCY = "NEWS_AGENCY"
    MEDIA = "MEDIA"
    FACT_CHECKER = "FACT_CHECKER"
    NGO = "NGO"
    THINK_TANK = "THINK_TANK"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class AuthorityLevel(str, Enum):
    LOCAL_PRIMARY = "LOCAL_PRIMARY"
    REGIONAL_PRIMARY = "REGIONAL_PRIMARY"
    NATIONAL_PRIMARY = "NATIONAL_PRIMARY"
    SUPRANATIONAL_PRIMARY = "SUPRANATIONAL_PRIMARY"
    INTERNATIONAL_PRIMARY = "INTERNATIONAL_PRIMARY"
    GLOBAL_PRIMARY = "GLOBAL_PRIMARY"
    SECONDARY_AUTHORITATIVE = "SECONDARY_AUTHORITATIVE"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class MatchLevel(str, Enum):
    EXACT = "EXACT"
    PARTIAL = "PARTIAL"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"


TOPIC_CATEGORY_IDS: dict[TopicCode, frozenset[int]] = {
    TopicCode.ECONOMY_MACRO: frozenset({1, 3, 10}),
    TopicCode.FINANCE_MARKETS: frozenset({1}),
    TopicCode.BUSINESS_CORPORATE: frozenset({1, 4}),
    TopicCode.EMPLOYMENT: frozenset({1, 3, 10}),
    TopicCode.TAXATION_PUBLIC_FINANCE: frozenset({1, 3}),
    TopicCode.TRADE: frozenset({1, 3}),
    TopicCode.HOUSING_REAL_ESTATE: frozenset({1, 3, 10}),
    TopicCode.POLITICS_GOVERNMENT: frozenset({3}),
    TopicCode.ELECTIONS: frozenset({3}),
    TopicCode.LAW_JUSTICE: frozenset({3, 10}),
    TopicCode.SECURITY_DEFENCE: frozenset({3, 10}),
    TopicCode.INTERNATIONAL_RELATIONS: frozenset({3}),
    TopicCode.HEALTH_PUBLIC_HEALTH: frozenset({5, 10}),
    TopicCode.MEDICINE: frozenset({5, 7}),
    TopicCode.SCIENCE_RESEARCH: frozenset({7}),
    TopicCode.TECHNOLOGY: frozenset({4, 7}),
    TopicCode.CYBERSECURITY: frozenset({4, 3}),
    TopicCode.ENVIRONMENT: frozenset({9, 7}),
    TopicCode.CLIMATE: frozenset({9, 7}),
    TopicCode.ENERGY: frozenset({1, 4, 9}),
    TopicCode.AGRICULTURE_FOOD: frozenset({1, 5, 9, 10}),
    TopicCode.EDUCATION: frozenset({3, 8, 10}),
    TopicCode.DEMOGRAPHY: frozenset({1, 3, 10}),
    TopicCode.MIGRATION: frozenset({3, 10}),
    TopicCode.SOCIAL_WELFARE: frozenset({3, 10}),
    TopicCode.TRANSPORT_INFRASTRUCTURE: frozenset({1, 3, 9, 10}),
    TopicCode.SPORTS: frozenset({2}),
    TopicCode.CULTURE: frozenset({8}),
    TopicCode.ENTERTAINMENT: frozenset({6, 8}),
    TopicCode.CRIME_PUBLIC_SAFETY: frozenset({3, 10}),
    TopicCode.OTHER: frozenset(range(1, 11)),
    TopicCode.UNKNOWN: frozenset(range(1, 11)),
}


EVIDENCE_SOURCE_TYPES: dict[EvidenceKind, frozenset[SourceType]] = {
    EvidenceKind.STATISTICAL_DATA: frozenset({SourceType.STATISTICAL_OFFICE, SourceType.CENTRAL_BANK, SourceType.GOVERNMENT_AGENCY, SourceType.INTERGOVERNMENTAL_ORGANIZATION}),
    EvidenceKind.LEGAL_TEXT: frozenset({SourceType.OFFICIAL_GAZETTE, SourceType.LEGISLATURE, SourceType.GOVERNMENT_AGENCY}),
    EvidenceKind.REGULATORY_DECISION: frozenset({SourceType.REGULATOR}),
    EvidenceKind.JUDICIAL_DECISION: frozenset({SourceType.COURT}),
    EvidenceKind.ELECTION_RESULT: frozenset({SourceType.ELECTORAL_AUTHORITY, SourceType.GOVERNMENT_AGENCY}),
    EvidenceKind.RESEARCH_PUBLICATION: frozenset({SourceType.RESEARCH_INSTITUTION, SourceType.ACADEMIC_PUBLISHER, SourceType.INTERGOVERNMENTAL_ORGANIZATION}),
    EvidenceKind.COMPANY_DISCLOSURE: frozenset({SourceType.COMPANY, SourceType.REGULATOR}),
    EvidenceKind.SPORTS_RECORD: frozenset({SourceType.SPORTS_GOVERNING_BODY}),
    EvidenceKind.WEATHER_OBSERVATION: frozenset({SourceType.GOVERNMENT_AGENCY, SourceType.INTERGOVERNMENTAL_ORGANIZATION, SourceType.RESEARCH_INSTITUTION}),
    EvidenceKind.GOVERNMENT_RECORD: frozenset({SourceType.GOVERNMENT_AGENCY, SourceType.OFFICIAL_GAZETTE, SourceType.LEGISLATURE}),
    EvidenceKind.PUBLIC_STATEMENT: frozenset({SourceType.GOVERNMENT_AGENCY, SourceType.COMPANY, SourceType.ORGANIZATION}),
    EvidenceKind.PRIMARY_DOCUMENT: frozenset(SourceType),
    EvidenceKind.GENERAL: frozenset(SourceType),
    EvidenceKind.UNKNOWN: frozenset(SourceType),
}


TOPIC_PROMPT = "\n".join(f"- {topic.value}" for topic in TopicCode)
EVIDENCE_KIND_PROMPT = "\n".join(f"- {kind.value}" for kind in EvidenceKind)
TOPIC_CATEGORY_PROMPT = "\n".join(
    f"- {topic.value}: {', '.join(str(category_id) for category_id in sorted(category_ids))}"
    for topic, category_ids in TOPIC_CATEGORY_IDS.items()
)


def validate_topic_category(topic: TopicCode, category_id: int) -> TopicCode:
    if category_id not in TOPIC_CATEGORY_IDS[topic]:
        raise ValueError(f"Topic {topic.value} is not compatible with categoryId {category_id}")
    return topic
