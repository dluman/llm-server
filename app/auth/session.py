import logging
from datetime import datetime, timezone

import jwt

from app.config import Settings

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"


def create_session_token(
    settings: Settings,
    github_login: str,
    enterprise_slug: str,
) -> str:
    """Issue a signed session JWT for a successfully authorized user."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": github_login,
        "ent": enterprise_slug,
        "iat": now,
        "exp": now.timestamp() + settings.github_session_ttl_seconds,
    }
    return jwt.encode(payload, settings.session_secret_key, algorithm=ALGORITHM)


def verify_session_token(settings: Settings, token: str) -> dict:
    """Verify a session JWT and return its payload."""
    return jwt.decode(
        token,
        settings.session_secret_key,
        algorithms=[ALGORITHM],
        options={"require": ["exp", "iat", "sub", "ent"]},
    )
