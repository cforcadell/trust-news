import logging
from datetime import timedelta

from common.llm import LLMProviderError, LLMResponseError
from common.search import search_with_provider
from common.search.normalization import normalize_domain
from common.routing_taxonomy import MatchLevel

from .classifier import classify_candidates
from .config import Settings
from .eligibility import eligible_sources
from .models import (
    CandidateSource,
    DomainProfile,
    ResolveRouteRequest,
    ResolveRouteResponse,
    RouteDocument,
    RouteDiagnostics,
    SourceClassification,
)
from .query_builder import build_discovery_queries
from .ranking import rank_sources, route_candidate
from .repository import SourceRouteRepository, utc_now
from .signatures import build_route_signature, route_key


logger = logging.getLogger(__name__)


class SourceRouterService:
    def __init__(self, repository: SourceRouteRepository, settings: Settings):
        self.repository = repository
        self.settings = settings

    async def _discover(self, request: ResolveRouteRequest) -> list[CandidateSource]:
        signature = build_route_signature(request)
        candidates: dict[str, CandidateSource] = {}
        for query in build_discovery_queries(signature, request):
            response = await search_with_provider(self.settings.search_provider, query, self.settings.discovery_max_results)
            logger.info("Discovery route_key=%s provider=%s query=%r requested_results=%s urls=%s",
                        route_key(signature), self.settings.search_provider, query,
                        self.settings.discovery_max_results,
                        [row.get("url") for row in response.get("results") or []])
            for row in response.get("results") or []:
                url = str(row.get("url") or "").strip()
                domain = normalize_domain(url)
                if not url or not domain or domain in candidates:
                    continue
                candidates[domain] = CandidateSource(
                    domain=domain,
                    url=url,
                    title=row.get("title") or "",
                    snippet=row.get("content") or "",
                    provider_score=row.get("score"),
                    provider_metadata=row.get("provider_metadata") or {},
                )
        return list(candidates.values())

    async def _rank_route(self, route: RouteDocument, request: ResolveRouteRequest):
        profiles = await self.repository.get_profiles([item.domain for item in route.candidates])
        return rank_sources(route.candidates, profiles, request.language, self.settings.max_sources)

    async def _profile_fallback(self, signature, domains, now):
        """Reuse only recent, compatible profiles of discovered but failed domains."""
        profiles = await self.repository.get_profiles(list(domains))
        sources = []
        for profile in profiles.values():
            if (profile.profile_version != self.settings.router_version
                    or profile.last_verified_at + timedelta(seconds=self.settings.refresh_seconds) <= now
                    or signature.topic_code not in profile.topic_codes
                    or signature.evidence_kind not in profile.evidence_kinds):
                continue
            source = SourceClassification(
                **profile.model_dump(include={
                    "domain", "source_type", "authority_level", "jurisdictions",
                    "topic_codes", "evidence_kinds", "languages", "classification_confidence",
                }),
                topic_match=MatchLevel.EXACT,
                evidence_kind_match=MatchLevel.EXACT,
                reason="Reused previously classified domain profile after classification failure",
            )
            sources.append(source)
        return eligible_sources(signature, sources)

    async def _profiles_from_classifications(
        self,
        classifications: list[SourceClassification],
        now,
    ) -> list[DomainProfile]:
        existing = await self.repository.get_profiles([item.domain for item in classifications])
        profiles = []
        for item in classifications:
            previous = existing.get(item.domain)
            jurisdictions_by_key = {
                value.routing_key(): value
                for value in ((previous.jurisdictions if previous else []) + item.jurisdictions)
            }
            profiles.append(DomainProfile(
                domain=item.domain,
                source_type=item.source_type,
                authority_level=item.authority_level,
                jurisdictions=list(jurisdictions_by_key.values()),
                topic_codes=list(dict.fromkeys((previous.topic_codes if previous else []) + item.topic_codes)),
                evidence_kinds=list(dict.fromkeys((previous.evidence_kinds if previous else []) + item.evidence_kinds)),
                languages=list(dict.fromkeys((previous.languages if previous else []) + item.languages)),
                classification_confidence=item.classification_confidence,
                reason=item.reason,
                profile_version=self.settings.router_version,
                classification_model=self.settings.llm_model,
                created_at=previous.created_at if previous else now,
                updated_at=now,
                last_verified_at=now,
            ))
        return profiles

    async def resolve(self, request: ResolveRouteRequest) -> ResolveRouteResponse:
        signature = build_route_signature(request)
        key = route_key(signature)
        now = utc_now()
        previous = await self.repository.get(key)
        if previous and previous.refresh_after > now:
            sources = await self._rank_route(previous, request)
            return ResolveRouteResponse(
                route_key=key, route_state="FRESH", sources=sources, router_version=previous.router_version,
                degraded=previous.degraded, diagnostic_code=previous.diagnostic_code,
                diagnostics=previous.diagnostics,
            )

        initial_state = "STALE" if previous else "MISSING"
        try:
            candidates = await self._discover(request)
            diagnostics = RouteDiagnostics(discovered_domains=[item.domain for item in candidates])
            try:
                classified = await classify_candidates(signature, request, candidates, self.settings)
                diagnostics.failed_domains = list(getattr(classified, "failed_domains", []))
            except (LLMProviderError, LLMResponseError):
                logger.warning("Classification failed route_key=%s; checking prior profiles", key, exc_info=True)
                classified = []
                diagnostics.failed_domains = diagnostics.discovered_domains.copy()
            diagnostics.classified_domains = [item.domain for item in classified]
            classifications = eligible_sources(signature, classified)
            eligible_domains = {item.domain for item in classifications}
            diagnostics.rejected_domains = [item.domain for item in classified if item.domain not in eligible_domains]
            profiles = await self._profiles_from_classifications(classifications, now)
            await self.repository.save_profiles(profiles)

            fallback = await self._profile_fallback(signature, diagnostics.failed_domains, now)
            diagnostics.fallback_domains = [item.domain for item in fallback]
            classifications.extend(fallback)
            # Fallback profiles are deliberately not re-saved: their verification date
            # must not be extended by a failed classification.
            diagnostic_code = None
            if diagnostics.failed_domains:
                diagnostic_code = ("PROFILE_FALLBACK" if fallback else
                                   "CLASSIFICATION_PARTIAL" if classified else "CLASSIFICATION_FAILED")
            elif not candidates:
                diagnostic_code = "NO_DISCOVERY_CANDIDATES"
            elif not classifications:
                diagnostic_code = "NO_ELIGIBLE_SOURCES"
            logger.info("Routing selection route_key=%s diagnostic=%s details=%s", key, diagnostic_code, diagnostics.model_dump())

            if not classifications:
                if previous:
                    return ResolveRouteResponse(
                        route_key=key, route_state="STALE", sources=await self._rank_route(previous, request),
                        router_version=previous.router_version, stale_route_used=True,
                        degraded=True, diagnostic_code=diagnostic_code, diagnostics=diagnostics,
                    )
                return ResolveRouteResponse(
                    route_key=key, route_state="MISSING", sources=[], router_version=self.settings.router_version,
                    degraded=bool(diagnostics.failed_domains), diagnostic_code=diagnostic_code, diagnostics=diagnostics,
                )

            current = {item.domain: route_candidate(signature, item) for item in classifications}
            if previous:
                for old in previous.candidates:
                    current.setdefault(old.domain, old)
            route = RouteDocument(
                route_key=key,
                route_signature=signature,
                candidates=list(current.values()),
                router_version=self.settings.router_version,
                discovery_provider=self.settings.search_provider,
                classification_model=self.settings.llm_model,
                created_at=previous.created_at if previous else now,
                updated_at=now,
                last_refreshed_at=now,
                refresh_after=now + timedelta(seconds=min(self.settings.refresh_seconds, 300)
                                              if diagnostics.failed_domains else self.settings.refresh_seconds),
                degraded=bool(diagnostics.failed_domains),
                diagnostic_code=diagnostic_code,
                diagnostics=diagnostics,
            )
            await self.repository.save(route)
            return ResolveRouteResponse(
                route_key=key,
                route_state=initial_state,
                sources=await self._rank_route(route, request),
                router_version=route.router_version,
                degraded=route.degraded,
                diagnostic_code=route.diagnostic_code,
                diagnostics=route.diagnostics,
            )
        except Exception:
            if previous:
                logger.warning("Route refresh failed route_key=%s; reusing stale route", key, exc_info=True)
                return ResolveRouteResponse(
                    route_key=key,
                    route_state="STALE",
                    sources=await self._rank_route(previous, request),
                    router_version=previous.router_version,
                    stale_route_used=True,
                    degraded=True,
                    diagnostic_code=previous.diagnostic_code,
                    diagnostics=previous.diagnostics,
                )
            raise
