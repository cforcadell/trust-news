from datetime import datetime, timezone
from typing import Any

from .models import RouteDocument


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SourceRouteRepository:
    def __init__(self, collection):
        self.collection = collection

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("route_key", unique=True)
        await self.collection.create_index([
            ("route_signature.claim_type", 1), ("route_signature.subcategory", 1),
            ("route_signature.country_code", 1), ("route_signature.region_code", 1),
        ])

    async def get(self, route_key: str) -> RouteDocument | None:
        document = await self.collection.find_one({"route_key": route_key}, {"_id": 0})
        return RouteDocument.model_validate(document) if document else None

    async def save(self, route: RouteDocument) -> RouteDocument:
        payload = route.model_dump(mode="python")
        await self.collection.update_one({"route_key": route.route_key}, {"$set": payload}, upsert=True)
        return route

    async def list(self, filters: dict[str, Any], limit: int = 100) -> list[RouteDocument]:
        query = {key: value for key, value in filters.items() if value is not None}
        cursor = self.collection.find(query, {"_id": 0}).sort("updated_at", -1).limit(limit)
        return [RouteDocument.model_validate(item) async for item in cursor]
