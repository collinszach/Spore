"""Shared token-auth dependency for capture-surface endpoints (Story 1.3).

Accepts either `Authorization: Bearer <token>` or `X-Spore-Token: <token>`
and compares against `settings.spore_capture_token`. Raises 401 on
mismatch/missing — FastAPI's default 401 JSON body is fine for the AC.
"""

from fastapi import Header, HTTPException, status

from app.config import settings


async def require_token(
    authorization: str | None = Header(default=None),
    x_spore_token: str | None = Header(default=None, alias="X-Spore-Token"),
) -> None:
    token: str | None = None

    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value:
            token = value
    if token is None and x_spore_token:
        token = x_spore_token

    if token is None or token != settings.spore_capture_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing token")
