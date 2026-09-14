"""Machine authentication for the API.

One shared secret, compared in constant time. The dashboard's server actions
and the GitHub Actions cron both carry it; the browser never sees it.
"""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from .config import get_settings


async def require_agent_key(x_agent_key: str = Header(default="")) -> None:
    settings = get_settings()
    if not settings.agent_key:
        # Refusing is the safe default: an unset key must not mean "open".
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "AGENT_KEY is not configured on the server; refusing to serve machine routes",
        )
    if not hmac.compare_digest(x_agent_key or "", settings.agent_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing X-Agent-Key")
