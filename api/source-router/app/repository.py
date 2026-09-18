from datetime import datetime, timezone
from typing import Any

from .models import DomainProfile, RouteDocument


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SourceRouteRepository:
    def __init__(self, collection, profiles_collection):
        self.collection = collection
        self.profiles_collection = profiles_collection

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("route_key", name="route_key_1", unique=True)
        await self.collection.create_index([
            ("route_signature.topic_code", 1), ("route_signature.evidence_kind", 1),
            ("route_signature.jurisdiction_key", 1),
        ], name="route_signature_v2")
        await self.profiles_collection.create_index("domain", name="domain_1", unique=True)
        await self.profiles_collection.create_index("topic_codes", name="profile_topic_codes_v1")
        await self.profiles_collection.create_index("evidence_kinds", name="profile_evidence_kinds_v1")
        await self.profiles_collection.create_index(
            "jurisdictions.country_code",
            name="profile_country_v1",
        )

    async def get(self, route_key: str) -> RouteDocument | None:
        document = await self.collection.find_one({"route_key": route_key}, {"_id": 0})
        return RouteDocument.model_validate(document) if document else None

    async def save(self, route: RouteDocument) -> RouteDocument:
        payload = route.model_dump(mode="python")
        await self.collection.update_one({"route_key": route.route_key}, {"$set": payload}, upsert=True)
        return route

    async def get_profiles(self, domains: list[str]) -> dict[str, DomainProfile]:
        if not domains:
            return {}
        cursor = self.profiles_collection.find({"domain": {"$in": domains}}, {"_id": 0})
        profiles = [DomainProfile.model_validate(item) async for item in cursor]
        return {profile.domain: profile for profile in profiles}

    async def save_profiles(self, profiles: list[DomainProfile]) -> None:
        for profile in profiles:
            await self.profiles_collection.update_one(
                {"domain": profile.domain},
                {"$set": profile.model_dump(mode="python")},
                upsert=True,
            )

    async def list(self, filters: dict[str, Any], limit: int = 100) -> list[RouteDocument]:
        query = {key: value for key, value in filters.items() if value is not None}
        cursor = self.collection.find(query, {"_id": 0}).sort("updated_at", -1).limit(limit)
        return [RouteDocument.model_validate(item) async for item in cursor]
