from typing import Annotated
import logging
from common.utils.evaluation_context import evaluation_context

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..models import ResolveRouteRequest, ResolveRouteResponse, StoredRouteResponse
from ..repository import utc_now
from ..query_builder import build_discovery_queries
from ..signatures import build_route_signature

router = APIRouter(prefix="/routes", tags=["source-routes"])


def service(request: Request):
    return request.app.state.source_router_service


@router.post("/resolve", response_model=ResolveRouteResponse, response_model_exclude_none=True)
async def resolve_route(payload: ResolveRouteRequest, source_router=Depends(service), request: Request = None):
    cold, run_id = evaluation_context(request)
    trace = {} if run_id else None
    if run_id:
        response = await source_router.resolve(payload, force_refresh=cold, evaluation_trace=trace)
    else:
        response = await source_router.resolve(payload, force_refresh=True) if cold else await source_router.resolve(payload)
    if run_id:
        planned = build_discovery_queries(build_route_signature(payload), payload)
        executed = {item["query"]: item for item in trace.get("query_execution", [])}
        response.evaluation_trace = {
            **trace,
            "run_id": run_id,
            "decision_source": "cached_route" if response.route_state == "FRESH" else
                               "stale_route" if response.stale_route_used else "recomputed_or_missing",
            "cache_hit": response.route_state == "FRESH" or response.stale_route_used,
            "planned_queries": [{"query": query, "executed": query in executed,
                                 "status": executed[query]["status"] if query in executed else "NOT_EXECUTED"}
                                for query in planned],
            "execution_detail": "CAPTURED" if trace.get("query_execution") else "NOT_EXECUTED_CACHE"
                                if response.route_state == "FRESH" else "NOT_EXECUTED",
            "diagnostics_origin": trace.get("diagnostics_origin") or
                                  ("stored_route" if response.route_state == "FRESH" else "current_resolution"),
            "discovered_domains": response.diagnostics.discovered_domains,
            "classified_domains": response.diagnostics.classified_domains,
            "rejected_domains": trace.get("rejected_domains", []),
            "failed_domains": trace.get("failed_domains", response.diagnostics.failed_domains),
            "fallback_domains": trace.get("fallback_domains", response.diagnostics.fallback_domains),
            "selection": [{"domain": source.domain, "rank": source.rank,
                           "route_score": source.route_score, "reason": source.reason}
                          for source in response.sources],
        }
        logging.getLogger(__name__).info({"event": "evaluation.route", "run_id": run_id,
                                         "route_key": response.route_key, "route_state": response.route_state, "cold": cold})
    return response


def stored_response(route) -> StoredRouteResponse:
    state = "FRESH" if route.refresh_after > utc_now() else "STALE"
    return StoredRouteResponse(**route.model_dump(), route_state=state)


@router.get("", response_model=list[StoredRouteResponse])
async def list_routes(
    source_router=Depends(service), route_key: str | None = None, topic_code: str | None = None,
    evidence_kind: str | None = None, jurisdiction_key: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    filters = {
        "route_key": route_key,
        "route_signature.topic_code": topic_code.upper() if topic_code else None,
        "route_signature.evidence_kind": evidence_kind.upper() if evidence_kind else None,
        "route_signature.jurisdiction_key": jurisdiction_key.upper() if jurisdiction_key else None,
    }
    routes = await source_router.repository.list(filters, limit)
    return [stored_response(route) for route in routes]


@router.get("/{route_key}", response_model=StoredRouteResponse)
async def get_route(route_key: str, source_router=Depends(service)):
    route = await source_router.repository.get(route_key)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return stored_response(route)
