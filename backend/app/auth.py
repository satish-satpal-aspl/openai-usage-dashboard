"""Optional HTTP basic auth for the whole app.

The dashboard exposes organization spend, project names and per-client billing.
That is fine on localhost and not fine on a public URL, so any deployment that
sets DASHBOARD_PASSWORD gets gated. With no password set the app is open, which
keeps `./start.sh` on a laptop friction-free.
"""
from __future__ import annotations

import base64
import hmac
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

DASHBOARD_USER = os.getenv("DASHBOARD_USER", "admin").strip() or "admin"
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "").strip()

# Render sets RENDER=true in every service. Hosted with no password would mean a
# public URL serving org spend, so refuse to serve rather than fail open - an
# obviously broken deploy is recoverable, a silently open one is not.
HOSTED = bool(os.getenv("RENDER") or os.getenv("DASHBOARD_REQUIRE_AUTH"))

# Render and most platforms health-check an unauthenticated path.
OPEN_PATHS = {"/api/health"}


def auth_enabled() -> bool:
    return bool(DASHBOARD_PASSWORD)


def misconfigured() -> bool:
    """Hosted, but nobody set a password."""
    return HOSTED and not DASHBOARD_PASSWORD


def _ok(header: str | None) -> bool:
    if not header or not header.lower().startswith("basic "):
        return False
    try:
        raw = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
    except Exception:
        return False
    user, _, password = raw.partition(":")
    # compare_digest on both halves - a short-circuit on the username would leak
    # whether the name was right
    return (hmac.compare_digest(user, DASHBOARD_USER)
            and hmac.compare_digest(password, DASHBOARD_PASSWORD))


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if misconfigured() and request.url.path not in OPEN_PATHS:
            return JSONResponse(
                status_code=503,
                content={"detail": "DASHBOARD_PASSWORD is not set. Refusing to serve "
                                   "organization data from a hosted deployment without "
                                   "authentication. Set it in the service environment."},
            )
        if not auth_enabled() or request.url.path in OPEN_PATHS:
            return await call_next(request)
        if _ok(request.headers.get("authorization")):
            return await call_next(request)
        # The browser prompt is the whole login UI.
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="OpenAI Usage Dashboard"'},
            content='{"detail":"Authentication required."}',
            media_type="application/json",
        )
