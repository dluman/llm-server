import logging

from fastapi import Header, HTTPException, Request

from app.auth.session import verify_session_token
from app.auth.zen import ValidationResult, validate_key
from app.config import get_settings

logger = logging.getLogger(__name__)


async def require_github_session(
    request: Request,
    authorization: str | None = Header(None, alias="Authorization"),
) -> str:
    """FastAPI dependency that validates the session JWT in the Authorization header.

    Returns the GitHub login on success; raises HTTPException(401) on failure.
    If GitHub auth is disabled, this dependency is a no-op.
    """
    settings = get_settings()
    if not settings.github_auth_enabled:
        return ""

    if not authorization or not authorization.startswith("Bearer "):
        logger.warning("Session auth rejected: missing or non-Bearer Authorization header")
        raise HTTPException(
            status_code=401,
            detail="Missing session token. Authenticate via /auth/device/* or /auth/token.",
        )

    session_token = authorization[7:].strip()
    if not session_token:
        logger.warning("Session auth rejected: empty bearer token")
        raise HTTPException(status_code=401, detail="Missing session token")

    try:
        payload = verify_session_token(settings, session_token)
    except Exception as exc:
        logger.warning("Session auth rejected: invalid or expired token (%s)", exc)
        raise HTTPException(
            status_code=401, detail="Invalid or expired session token"
        ) from exc

    request.state.github_login = payload["sub"]
    request.state.github_enterprise = payload["ent"]
    logger.info("Session auth accepted for user=%s", payload["sub"])
    return payload["sub"]


async def require_valid_key(
    request: Request,
    x_zen_api_key: str = Header(..., alias="X-Zen-Api-Key"),
) -> str:
    """FastAPI dependency that validates the X-Zen-Api-Key header.

    Returns the key on success; raises HTTPException(401) on failure.
    """
    if not x_zen_api_key:
        logger.warning("Zen key validation rejected: missing X-Zen-Api-Key header")
        raise HTTPException(status_code=401, detail="Missing X-Zen-Api-Key header")

    client = request.app.state.http_client
    result: ValidationResult = await validate_key(client, x_zen_api_key)
    if not result.valid:
        logger.warning("Zen key validation rejected: invalid or expired key")
        raise HTTPException(status_code=401, detail="Invalid or expired Zen API key")

    logger.info("Zen key validation accepted for user=%s", getattr(request.state, "github_login", None))
    request.state.zen_key = x_zen_api_key
    request.state.zen_validation = result
    return x_zen_api_key
