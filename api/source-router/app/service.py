from datetime import timedelta

from common.search import search_with_provider
from common.search.normalization import normalize_domain

from .classifier import classify_candidates
from .config import Settings
from .eligibility import eligible_sources
from .models import CandidateSource, ResolveRouteRequest, ResolveRouteResponse, RouteDocument, SourceClassification
from .query_builder import build_discovery_queries
from .ranking import rank_sources
from .repository import SourceRouteRepository, utc_now
from .signatures import build_route_signature, route_key


class SourceRouterService:
    def __init__(self, repository: SourceRouteRepository, settings: Settings):
        self.repository = repository
        self.settings = settings

    async def _discover(self, request: ResolveRouteRequest) -> list[CandidateSource]:
        signature = build_route_signature(request)
        candidates: dict[str, CandidateSource] = {}
        for query in build_discovery_queries(signature, request):
            response = await search_with_provider(self.settings.search_provider, query, self.settings.discovery_max_results)
            for row in response.get("results") or []:
                url = str(row.get("url") or "").strip()
                domain = normalize_domain(url)
                if not url or not domain or domain in candidates:
                    continue
                candidates[domain] = CandidateSource(
                    domain=domain, url=url, title=row.get("title") or "", snippet=row.get("content") or "",
                    provider_score=row.get("score"), provider_metadata=row.get("provider_metadata") or {},
                )
        return list(candidates.values())

    async def resolve(self, request: ResolveRouteRequest) -> ResolveRouteResponse:
        signature = build_route_signature(request)
        key = route_key(signature)
        now = utc_now()
        previous = await self.repository.get(key)
        if previous and previous.refresh_after > now:
            return ResolveRouteResponse(route_key=key, route_state="FRESH", sources=previous.sources, router_version=previous.router_version)

        initial_state = "STALE" if previous else "MISSING"
        try:
            candidates = await self._discover(request)
            classifications = await classify_candidates(signature, request, candidates, self.settings)
            if previous:
                current = {item.domain: item for item in classifications}
                for old in previous.sources:
                    current.setdefault(
                        old.domain,
                        SourceClassification.model_validate(old.model_dump(exclude={"rank", "routing_score"})),
                    )
                classifications = list(current.values())
            ranked = rank_sources(signature, eligible_sources(signature, classifications), self.settings.max_sources)
            created_at = previous.created_at if previous else now
            route = RouteDocument(
                route_key=key, route_signature=signature, category=request.category,
                entities=[item.name for item in request.entities], sources=ranked,
                router_version=self.settings.router_version, discovery_provider=self.settings.search_provider,
                classification_model=self.settings.llm_model, created_at=created_at, updated_at=now,
                last_refreshed_at=now, refresh_after=now + timedelta(seconds=self.settings.refresh_seconds),
            )
            await self.repository.save(route)
            return ResolveRouteResponse(route_key=key, route_state=initial_state, sources=ranked, router_version=route.router_version)
        except Exception:
            if previous:
                return ResolveRouteResponse(route_key=key, route_state="STALE", sources=previous.sources, router_version=previous.router_version, stale_route_used=True)
            raise
