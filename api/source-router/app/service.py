import logging
import math
import os
from copy import copy
from dataclasses import is_dataclass, replace
from datetime import timedelta

from common.llm import LLMProviderError, LLMResponseError
from common.search import search_with_provider
from common.search.normalization import normalize_domain
from common.routing_taxonomy import MatchLevel

from .classifier import classify_candidates
from .config import Settings
from .eligibility import eligible_sources
from .evaluation_trace import classification_score_components, ranking_rows, rejection_reasons
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
from .ranking import classification_score, rank_sources, route_candidate
from .repository import SourceRouteRepository, utc_now
from .signatures import build_route_signature, route_key


logger = logging.getLogger(__name__)


class SourceRouterService:
    def __init__(self, repository: SourceRouteRepository, settings: Settings):
        self.repository = repository
        self.settings = settings
        self.llm_provider = settings.llm_provider
        self.llm_model = settings.llm_model
        self.llm_temperature = settings.llm_temperature
        self.llm_config_version = 0

    def llm_runtime_config(self) -> dict:
        return {
            "provider": self.llm_provider,
            "model": self.llm_model,
            "temperature": self.llm_temperature,
            "config_version": self.llm_config_version,
            "credentials_configured": {
                "openrouter": bool(os.environ.get("OPENROUTER_API_KEY") or os.environ.get("API_KEY")),
                "gemini": bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("API_KEY")),
                "mistral": bool(os.environ.get("MISTRAL_API_KEY") or os.environ.get("API_KEY")),
                "grok": bool(os.environ.get("GROK_API_KEY") or os.environ.get("API_KEY")),
            },
        }

    def update_llm_runtime_config(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        config_version: int | None = None,
    ) -> dict:
        allowed = {"openrouter", "gemini", "mistral", "grok"}
        if provider is not None:
            normalized = provider.strip().lower()
            if normalized not in allowed:
                raise ValueError("provider no soportado")
            self.llm_provider = normalized
        if model is not None:
            normalized_model = model.strip()
            if not normalized_model:
                raise ValueError("model no puede estar vacío")
            self.llm_model = normalized_model
        if temperature is not None:
            if not math.isfinite(temperature) or temperature < 0:
                raise ValueError("temperature debe ser un número finito mayor o igual que cero")
            self.llm_temperature = float(temperature)
        if config_version is not None:
            if int(config_version) <= 0:
                raise ValueError("config_version debe ser positivo")
            self.llm_config_version = int(config_version)
        return self.llm_runtime_config()

    def classifier_settings(self) -> Settings:
        if is_dataclass(self.settings):
            return replace(
                self.settings,
                llm_provider=self.llm_provider,
                llm_model=self.llm_model,
                llm_temperature=self.llm_temperature,
            )
        # Test and embedding callers historically supplied a lightweight
        # settings object rather than Settings. Keep the effective config
        # isolated from that shared object as well.
        effective = copy(self.settings)
        effective.llm_provider = self.llm_provider
        effective.llm_model = self.llm_model
        effective.llm_temperature = self.llm_temperature
        return effective

    async def _discover(self, request: ResolveRouteRequest, trace: dict | None = None) -> list[CandidateSource]:
        signature = build_route_signature(request)
        candidates: dict[str, CandidateSource] = {}
        for query in build_discovery_queries(signature, request):
            query_trace = None
            if trace is not None:
                query_trace = {"query": query, "provider": self.settings.search_provider,
                               "requested_results": self.settings.discovery_max_results,
                               "status": "EXECUTED", "returned_urls": [], "result_decisions": []}
                trace.setdefault("query_execution", []).append(query_trace)
            try:
                response = await search_with_provider(self.settings.search_provider, query, self.settings.discovery_max_results)
            except Exception as exc:
                if query_trace is not None:
                    query_trace.update(status="FAILED", error_type=type(exc).__name__)
                raise
            if query_trace is not None:
                query_trace["returned_urls"] = [str(row.get("url") or "") for row in response.get("results") or []]
                query_trace["outcome"] = "RESULTS" if query_trace["returned_urls"] else "EMPTY"
            logger.info("Discovery route_key=%s provider=%s query=%r requested_results=%s urls=%s",
                        route_key(signature), self.settings.search_provider, query,
                        self.settings.discovery_max_results,
                        [row.get("url") for row in response.get("results") or []])
            for row in response.get("results") or []:
                url = str(row.get("url") or "").strip()
                domain = normalize_domain(url)
                if query_trace is not None:
                    reason = "EMPTY_URL" if not url else "INVALID_DOMAIN" if not domain else (
                        "DUPLICATE_DOMAIN" if domain in candidates else "RETAINED")
                    query_trace["result_decisions"].append({"url": url, "domain": domain or None, "decision": reason})
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

    async def _rank_route(self, route: RouteDocument, request: ResolveRouteRequest, trace: dict | None = None):
        profiles = await self.repository.get_profiles([item.domain for item in route.candidates])
        sources = rank_sources(route.candidates, profiles, request.language, self.settings.max_sources)
        if trace is not None:
            try:
                trace["ranking"] = ranking_rows(route, profiles, request.language, sources)
            except Exception as exc:
                logger.warning("Evaluation ranking trace failed", exc_info=True)
                trace["trace_error_type"] = type(exc).__name__
        return sources

    async def _profile_fallback(self, signature, domains, now, trace: dict | None = None):
        """Reuse only recent, compatible profiles of discovered but failed domains."""
        profiles = await self.repository.get_profiles(list(domains))
        sources = []
        if trace is not None:
            trace["profile_fallback_candidates"] = [
                {"domain": domain, "precheck_reasons": ["PROFILE_NOT_FOUND"], "decision": "PRECHECK_REJECTED"}
                for domain in domains if domain not in profiles]
        for profile in profiles.values():
            if trace is not None:
                reasons = []
                if profile.profile_version != self.settings.router_version:
                    reasons.append("PROFILE_VERSION_MISMATCH")
                if profile.last_verified_at + timedelta(seconds=self.settings.refresh_seconds) <= now:
                    reasons.append("PROFILE_EXPIRED")
                if signature.topic_code not in profile.topic_codes:
                    reasons.append("PROFILE_TOPIC_MISMATCH")
                if signature.evidence_kind not in profile.evidence_kinds:
                    reasons.append("PROFILE_EVIDENCE_KIND_MISMATCH")
                trace.setdefault("profile_fallback_candidates", []).append({"domain": profile.domain,
                    "precheck_reasons": reasons})
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
        eligible = eligible_sources(signature, sources)
        if trace is not None:
            accepted = {source.domain for source in eligible}
            for item in trace.get("profile_fallback_candidates", []):
                if item["precheck_reasons"]:
                    item["decision"] = "PRECHECK_REJECTED"
                elif item["domain"] in accepted:
                    item["decision"] = "REUSED"
                else:
                    source = next((value for value in sources if value.domain == item["domain"]), None)
                    item["decision"] = "ELIGIBILITY_REJECTED"
                    item["rejection_reasons"] = rejection_reasons(signature, source) if source else []
        return eligible

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
                classification_model=self.llm_model,
                classification_config_version=self.llm_config_version,
                created_at=previous.created_at if previous else now,
                updated_at=now,
                last_verified_at=now,
            ))
        return profiles

    async def resolve(self, request: ResolveRouteRequest, *, force_refresh: bool = False,
                      evaluation_trace: dict | None = None) -> ResolveRouteResponse:
        signature = build_route_signature(request)
        key = route_key(signature)
        now = utc_now()
        previous = None if force_refresh else await self.repository.get(key)
        if evaluation_trace is not None:
            evaluation_trace.update(cache_lookup="BYPASSED_COLD" if force_refresh else
                                    "FRESH" if previous and previous.refresh_after > now else
                                    "STALE" if previous else "MISSING",
                                    previous_route_present=previous is not None,
                                    query_execution=[], classification=[], rejected_domains=[],
                                    ranking=[], preserved_domains=[])
        if previous and previous.refresh_after > now:
            sources = await self._rank_route(previous, request, evaluation_trace)
            return ResolveRouteResponse(
                route_key=key, route_state="FRESH", sources=sources, router_version=previous.router_version,
                degraded=previous.degraded, diagnostic_code=previous.diagnostic_code,
                diagnostics=previous.diagnostics,
            )

        initial_state = "STALE" if previous else "MISSING"
        try:
            candidates = await self._discover(request, evaluation_trace)
            diagnostics = RouteDiagnostics(discovered_domains=[item.domain for item in candidates])
            try:
                classified = await classify_candidates(signature, request, candidates, self.classifier_settings())
                diagnostics.failed_domains = list(getattr(classified, "failed_domains", []))
            except (LLMProviderError, LLMResponseError):
                logger.warning("Classification failed route_key=%s; checking prior profiles", key, exc_info=True)
                classified = []
                diagnostics.failed_domains = diagnostics.discovered_domains.copy()
                if evaluation_trace is not None:
                    evaluation_trace["classification_error_type"] = "LLM_CLASSIFICATION_ERROR"
            diagnostics.classified_domains = [item.domain for item in classified]
            classifications = eligible_sources(signature, classified)
            eligible_domains = {item.domain for item in classifications}
            diagnostics.rejected_domains = [item.domain for item in classified if item.domain not in eligible_domains]
            if evaluation_trace is not None:
                try:
                    evaluation_trace["classification"] = [{
                        "domain": item.domain, "source_type": item.source_type.value,
                        "authority_level": item.authority_level.value, "reason": item.reason,
                        "jurisdictions": [value.model_dump(mode="json") for value in item.jurisdictions],
                        "topic_match": item.topic_match.value,
                        "evidence_kind_match": item.evidence_kind_match.value,
                        "semantic_relevance": item.semantic_relevance,
                        "classification_confidence": item.classification_confidence,
                        "provider_score": item.provider_score,
                        "score_components": classification_score_components(signature, item),
                        "classification_score": classification_score(signature, item),
                        "eligible": item.domain in eligible_domains,
                        "rejection_reasons": rejection_reasons(signature, item) if item.domain not in eligible_domains else [],
                    } for item in classified]
                    evaluation_trace["rejected_domains"] = [
                        {"domain": item["domain"], "reasons": item["rejection_reasons"]}
                        for item in evaluation_trace["classification"] if not item["eligible"]]
                except Exception as exc:
                    logger.warning("Evaluation classification trace failed", exc_info=True)
                    evaluation_trace["trace_error_type"] = type(exc).__name__
            profiles = await self._profiles_from_classifications(classifications, now)
            await self.repository.save_profiles(profiles)

            fallback = [] if force_refresh else await self._profile_fallback(signature, diagnostics.failed_domains, now,
                                                                               evaluation_trace)
            diagnostics.fallback_domains = [item.domain for item in fallback]
            if evaluation_trace is not None:
                evaluation_trace["failed_domains"] = diagnostics.failed_domains.copy()
                evaluation_trace["unclassified_domains"] = [
                    {"domain": domain, "reason": "NO_VALID_CLASSIFICATION"}
                    for domain in diagnostics.failed_domains]
                evaluation_trace["fallback_domains"] = diagnostics.fallback_domains.copy()
                evaluation_trace["fallback_reason"] = "RECENT_COMPATIBLE_PROFILE" if fallback else None
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
                    if evaluation_trace is not None:
                        evaluation_trace["diagnostics_origin"] = "current_resolution"
                    return ResolveRouteResponse(
                        route_key=key, route_state="STALE", sources=await self._rank_route(previous, request, evaluation_trace),
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
                    if evaluation_trace is not None and old.domain not in current:
                        evaluation_trace["preserved_domains"].append(old.domain)
                    current.setdefault(old.domain, old)
            route = RouteDocument(
                route_key=key,
                route_signature=signature,
                candidates=list(current.values()),
                router_version=self.settings.router_version,
                discovery_provider=self.settings.search_provider,
                classification_model=self.llm_model,
                classification_config_version=self.llm_config_version,
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
                sources=await self._rank_route(route, request, evaluation_trace),
                router_version=route.router_version,
                degraded=route.degraded,
                diagnostic_code=route.diagnostic_code,
                diagnostics=route.diagnostics,
            )
        except Exception as exc:
            if evaluation_trace is not None:
                evaluation_trace["refresh_error_type"] = type(exc).__name__
            if previous:
                if evaluation_trace is not None:
                    evaluation_trace["diagnostics_origin"] = "stored_route"
                logger.warning("Route refresh failed route_key=%s; reusing stale route", key, exc_info=True)
                return ResolveRouteResponse(
                    route_key=key,
                    route_state="STALE",
                    sources=await self._rank_route(previous, request, evaluation_trace),
                    router_version=previous.router_version,
                    stale_route_used=True,
                    degraded=True,
                    diagnostic_code=previous.diagnostic_code,
                    diagnostics=previous.diagnostics,
                )
            raise
