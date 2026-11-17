"""Keycloak-only identity engine for service-to-service HTTP calls.

The target service always authenticates its caller. Human actions require a
second, independently verified Keycloak access token. Resource ownership is
resolved by the application, never from a forwarded header or query string.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import threading
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
try:
    from jose import JWTError, jwt
except ImportError:  # Legacy local environments may not have the S03 extra yet.
    jwt = None

    class JWTError(Exception):
        pass
from starlette.routing import Match

USER_TOKEN_HEADER = "x-assermetry-user-token"
MAX_TOKEN_BYTES = 16384


def _csv(value: str) -> frozenset[str]:
    return frozenset(item.strip() for item in value.split(",") if item.strip())


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


@dataclass(frozen=True)
class Policy:
    method: str
    path: str
    action: str
    callers: frozenset[str]
    user_required: bool
    roles: frozenset[str]
    scope: str

    @classmethod
    def parse(cls, row: Mapping[str, Any]) -> "Policy":
        required = {"method", "path", "action", "callers", "user_required", "roles", "scope"}
        if set(row) != required:
            raise ValueError(f"Invalid policy fields for {row.get('path', '<unknown>')}")
        method, path, action, scope = (_text(row[key]) for key in ("method", "path", "action", "scope"))
        callers, roles = row["callers"], row["roles"]
        if not method or not path.startswith("/") or not action or scope not in {"own", "any", "system"}:
            raise ValueError("Invalid policy method, path, action or scope")
        if not isinstance(callers, list) or not callers or not all(_text(x) for x in callers):
            raise ValueError("Policy callers must be nonempty")
        if not isinstance(roles, list) or not all(_text(x) for x in roles):
            raise ValueError("Policy roles must be a list")
        if not isinstance(row["user_required"], bool):
            raise ValueError("Policy user_required must be boolean")
        if scope == "own" and not row["user_required"]:
            raise ValueError("Owner-scoped policy requires a user")
        return cls(method.upper(), path, action, frozenset(callers), row["user_required"], frozenset(roles), scope)


@dataclass(frozen=True)
class AuthenticatedCall:
    service: str
    user_sub: str | None
    user_issuer: str | None
    user_roles: frozenset[str]
    action: str
    scope: str
    user_client_id: str | None = None


class KeycloakVerifier:
    def __init__(self, *, issuer: str, jwks_url: str, ca_file: str | None = None, ttl: int = 120):
        if jwt is None:
            raise RuntimeError("python-jose is required for S03")
        if urlsplit(jwks_url).scheme != "https":
            raise ValueError("JWKS must use HTTPS")
        self.issuer = issuer.rstrip("/")
        self.jwks_url = jwks_url
        self.ca_file = ca_file
        self.ttl = ttl
        self._keys: dict[str, dict] = {}
        self._expires = 0.0
        self._lock = asyncio.Lock()

    async def _key(self, kid: str) -> dict:
        async with self._lock:
            if time.monotonic() >= self._expires or kid not in self._keys:
                try:
                    async with httpx.AsyncClient(verify=self.ca_file or True, timeout=5) as client:
                        response = await client.get(self.jwks_url)
                        response.raise_for_status()
                        keys = response.json()["keys"]
                    if not isinstance(keys, list) or len(keys) > 32:
                        raise ValueError("Invalid JWKS")
                    self._keys = {key["kid"]: key for key in keys if key.get("kty") == "RSA" and key.get("use", "sig") == "sig"}
                    self._expires = time.monotonic() + self.ttl
                except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                    raise HTTPException(status_code=503, detail="Identity keys unavailable") from exc
            key = self._keys.get(kid)
            if not key:
                raise HTTPException(status_code=401, detail="Unknown token key")
            return key

    async def verify(self, token: str, *, audience: str, clients: frozenset[str]) -> dict[str, Any]:
        if not token or len(token.encode("utf-8")) > MAX_TOKEN_BYTES:
            raise HTTPException(status_code=401, detail="Invalid token")
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not _text(header.get("kid")):
                raise JWTError("Invalid token header")
            key = await self._key(header["kid"])
            claims = jwt.decode(
                token, key, algorithms=["RS256"], issuer=self.issuer, audience=audience,
                options={"require_exp": True, "require_iat": True, "require_sub": True, "require_aud": True},
            )
            if not _text(claims.get("sub")) or not _text(claims.get("azp")):
                raise JWTError("Missing identity")
            if claims["azp"] not in clients:
                raise JWTError("Presenting client denied")
            return claims
        except HTTPException:
            raise
        except (JWTError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=401, detail="Invalid token") from exc


OwnerCheck = Callable[[Request, AuthenticatedCall], Awaitable[bool]]


class InternalSecurity:
    """Route policy, token verification, and app-specific owner resolver."""

    def __init__(self, app, *, audience: str, issuer: str, jwks_url: str,
                 policy_file: str, user_clients: frozenset[str], ca_file: str | None = None,
                 owner_check: OwnerCheck | None = None):
        self.app = app
        self.audience = audience
        self.user_clients = user_clients
        self.owner_check = owner_check
        self.verifier = KeycloakVerifier(issuer=issuer, jwks_url=jwks_url, ca_file=ca_file)
        with open(policy_file, encoding="utf-8") as handle:
            rows = json.load(handle)
        if not isinstance(rows, list):
            raise ValueError("Policy must be a list")
        self.policies = {(p.method, p.path): p for p in (Policy.parse(row) for row in rows)}
        if len(self.policies) != len(rows):
            raise ValueError("Duplicate route policy")

    def check_coverage(self) -> None:
        for route in self.app.routes:
            if not hasattr(route, "methods") or not hasattr(route, "path"):
                continue
            for method in route.methods - {"HEAD", "OPTIONS"}:
                if (method, route.path) not in self.policies:
                    raise ValueError(f"Missing policy: {method} {route.path}")
        paths = {(method, route.path) for route in self.app.routes if hasattr(route, "methods") for method in route.methods}
        for key in self.policies:
            if key not in paths:
                raise ValueError(f"Policy does not match route: {key}")

    def _route(self, request: Request):
        for route in self.app.routes:
            match, child_scope = route.matches(request.scope)
            if match == Match.FULL:
                request.scope.update(child_scope)
                return route
        return None

    async def authenticate(self, request: Request) -> AuthenticatedCall:
        route = self._route(request)
        if route is None:
            raise HTTPException(status_code=404, detail="Not found")
        policy = self.policies.get((request.method, route.path))
        if policy is None:
            raise HTTPException(status_code=403, detail="Route denied")
        if policy.callers == frozenset({"public"}):
            return AuthenticatedCall("public", None, None, frozenset(), policy.action, policy.scope)
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Service token required")
        service_claims = await self.verifier.verify(auth[7:], audience=self.audience, clients=policy.callers)
        service = service_claims["azp"]
        if service not in policy.callers or _text(service_claims.get("preferred_username")) != f"service-account-{service}":
            raise HTTPException(status_code=401, detail="Service account required")
        user_token = request.headers.get(USER_TOKEN_HEADER)
        if policy.user_required and not user_token:
            raise HTTPException(status_code=401, detail="User token required")
        user = None
        if user_token:
            user = await self.verifier.verify(user_token, audience=self.audience, clients=self.user_clients)
            if _text(user.get("preferred_username", "")).startswith("service-account-"):
                raise HTTPException(status_code=401, detail="Human user required")
        realm_access = (user or {}).get("realm_access")
        role_list = realm_access.get("roles", []) if isinstance(realm_access, dict) else []
        if not isinstance(role_list, list) or not all(isinstance(role, str) for role in role_list):
            raise HTTPException(status_code=401, detail="Invalid user roles")
        roles = frozenset(role_list)
        if policy.roles and not policy.roles.intersection(roles):
            raise HTTPException(status_code=403, detail="Role denied")
        call = AuthenticatedCall(service, (user or {}).get("sub"), (user or {}).get("iss"), roles, policy.action, policy.scope,
                                 _text((user or {}).get("client_id")) or None)
        if policy.scope == "own":
            if self.owner_check is None or not await self.owner_check(request, call):
                raise HTTPException(status_code=403, detail="Resource denied")
        return call

    def install(self) -> None:
        self.check_coverage()
        engine = self

        @self.app.middleware("http")
        async def authenticate_internal_call(request: Request, call_next):
            try:
                request.state.s03_call = await engine.authenticate(request)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
            return await call_next(request)


class ServiceTokenClient:
    """Client-credentials token cache; one cache entry per destination scope."""

    def __init__(self, *, token_url: str, client_id: str, client_secret: str, ca_file: str | None = None):
        if urlsplit(token_url).scheme != "https":
            raise ValueError("Token endpoint must use HTTPS")
        if not client_id or not client_secret:
            raise ValueError("Service credentials are required")
        self.token_url, self.client_id, self.client_secret = token_url, client_id, client_secret
        self.ca_file = ca_file
        self._tokens: dict[str, tuple[str, float]] = {}
        self._lock = asyncio.Lock()

    async def token(self, scope: str) -> str:
        async with self._lock:
            token, expires = self._tokens.get(scope, ("", 0.0))
            if token and time.monotonic() < expires:
                return token
            # Audience mappers are default client scopes in Keycloak 24. The
            # destination still enforces its own aud claim; an arbitrary
            # OAuth scope parameter must not be mistaken for an audience.
            data = {"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.client_secret}
            async with httpx.AsyncClient(verify=self.ca_file or True, timeout=5) as client:
                response = await client.post(self.token_url, data=data)
                response.raise_for_status()
                result = response.json()
            token = result["access_token"]
            lifetime = max(1, int(result.get("expires_in", 30)) - 10)
            self._tokens[scope] = (token, time.monotonic() + lifetime)
            return token

    async def headers(self, *, scope: str, user_token: str | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {await self.token(scope)}"}
        if user_token:
            headers[USER_TOKEN_HEADER] = user_token
        return headers


def settings_from_env() -> dict[str, str]:
    names = ("S03_AUDIENCE", "KEYCLOAK_ISSUER_URL", "KEYCLOAK_JWKS_URL", "S03_POLICY_FILE", "S03_USER_CLIENTS")
    values = {name: os.getenv(name, "").strip() for name in names}
    if not all(values.values()):
        raise ValueError("S03 identity configuration is incomplete")
    values["S03_CA_FILE"] = os.getenv("S03_CA_FILE", "").strip()
    return values


_outbound_client: ServiceTokenClient | None = None


def outbound_client_from_env() -> ServiceTokenClient:
    global _outbound_client
    if _outbound_client is None:
        _outbound_client = ServiceTokenClient(
            token_url=os.environ["S03_TOKEN_URL"],
            client_id=os.environ["S03_CLIENT_ID"],
            client_secret=os.environ["S03_CLIENT_SECRET"],
            ca_file=os.getenv("S03_CA_FILE") or None,
        )
    return _outbound_client


async def internal_headers(scope: str, user_token: str | None = None) -> dict[str, str]:
    if os.getenv("S03_ENABLED", "false").lower() != "true":
        return {}
    return await outbound_client_from_env().headers(scope=scope, user_token=user_token)


def audience_for_url(url: str) -> str:
    """Resolve the exact HTTPS origin to a configured Keycloak audience."""
    target = urlsplit(url)
    if target.scheme != "https" or not target.netloc or target.username or target.password:
        raise ValueError("Protected target must use HTTPS")
    mapping = json.loads(os.getenv("S03_TARGET_AUDIENCES", "{}"))
    if not isinstance(mapping, dict):
        raise ValueError("Invalid target audience map")
    audience = mapping.get(f"{target.scheme}://{target.netloc}")
    if not _text(audience):
        raise ValueError("Target has no configured audience")
    return audience


def protected_url(url: str) -> str:
    """Map a discovered legacy origin to its explicitly approved TLS origin."""
    source = urlsplit(url)
    if source.username or source.password or not source.netloc:
        raise ValueError("Invalid target origin")
    mapping = json.loads(os.getenv("S03_TLS_ORIGINS", "{}"))
    if not isinstance(mapping, dict):
        raise ValueError("Invalid TLS origin map")
    origin = f"{source.scheme}://{source.netloc}"
    target = mapping.get(origin, origin)
    if not _text(target):
        raise ValueError("Unapproved target origin")
    parsed = urlsplit(target)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
        raise ValueError("Protected origin must be HTTPS")
    return f"{target}{source.path}" + (f"?{source.query}" if source.query else "")


async def require_internal_route(request: Request) -> None:
    """FastAPI dependency for selected sensitive routes in mixed APIs."""
    if os.getenv("S03_ENABLED", "false").lower() == "true":
        guard = getattr(request.app.state, "s03_guard", None)
        if guard is None:
            raise HTTPException(status_code=503, detail="Internal security unavailable")
        request.state.s03_call = await guard.authenticate(request)


def configure_route_guard(app, policy_file: str) -> None:
    config = settings_from_env()
    app.state.s03_guard = InternalSecurity(
        app, audience=config["S03_AUDIENCE"], issuer=config["KEYCLOAK_ISSUER_URL"],
        jwks_url=config["KEYCLOAK_JWKS_URL"], policy_file=policy_file,
        user_clients=_csv(config["S03_USER_CLIENTS"]), ca_file=config["S03_CA_FILE"] or None,
    )


_sync_tokens: dict[str, tuple[str, float]] = {}
_sync_lock = threading.Lock()


def sync_internal_headers(audience: str, user_token: str | None = None) -> dict[str, str]:
    """Synchronous variant for existing worker call sites."""
    if os.getenv("S03_ENABLED", "false").lower() != "true":
        return {}
    with _sync_lock:
        token, expires = _sync_tokens.get(audience, ("", 0.0))
        if not token or time.monotonic() >= expires:
            token_url = os.environ["S03_TOKEN_URL"]
            if urlsplit(token_url).scheme != "https":
                raise ValueError("Token endpoint must use HTTPS")
            data = {"grant_type": "client_credentials", "client_id": os.environ["S03_CLIENT_ID"],
                    "client_secret": os.environ["S03_CLIENT_SECRET"]}
            with httpx.Client(verify=os.getenv("S03_CA_FILE") or True, timeout=5) as client:
                response = client.post(token_url, data=data)
                response.raise_for_status()
                payload = response.json()
            token = payload["access_token"]
            _sync_tokens[audience] = (token, time.monotonic() + max(1, int(payload.get("expires_in", 30)) - 10))
    headers = {"Authorization": f"Bearer {token}"}
    if user_token:
        headers[USER_TOKEN_HEADER] = user_token
    return headers
