from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..models import ResolveRouteRequest, ResolveRouteResponse, StoredRouteResponse
from ..repository import utc_now

router = APIRouter(prefix="/routes", tags=["source-routes"])


def service(request: Request):
    return request.app.state.source_router_service


@router.post("/resolve", response_model=ResolveRouteResponse)
async def resolve_route(payload: ResolveRouteRequest, source_router=Depends(service)):
    return await source_router.resolve(payload)


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
