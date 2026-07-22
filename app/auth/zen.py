import hashlib
import logging
from dataclasses import dataclass
from typing import Optional

import httpx
from cachetools import TTLCache

from app.config import get_settings

logger = logging.getLogger(__name__)

_cache: Optional[TTLCache] = None


def _get_cache() -> TTLCache:
    global _cache
    if _cache is None:
        settings = get_settings()
        _cache = TTLCache(
            maxsize=settings.auth_cache_max_size,
            ttl=settings.auth_cache_ttl_seconds,
        )
    return _cache


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    cached: bool = False
    metadata: Optional[dict] = None


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


async def validate_key(client: httpx.AsyncClient, key: str) -> ValidationResult:
    """Validate a Zen API key against the configured Opencode Zen verify endpoint.

    Successful validations are cached in memory for AUTH_CACHE_TTL_SECONDS.
    Failures are not cached.
    """
    cache = _get_cache()
    kh = _key_hash(key)
    cached_metadata = cache.get(kh)
    if cached_metadata is not None:
        return ValidationResult(valid=True, cached=True, metadata=cached_metadata)

    settings = get_settings()
    logger.info(
        "Zen auth verify request: url=%s header_present=%s",
        settings.zen_auth_verify_url,
        bool(key),
    )
    try:
        response = await client.get(
            settings.zen_auth_verify_url,
            headers={
                settings.zen_api_header: key,
                "user-agent": "opencode-api-proxy/1.0",
            },
            timeout=10.0,
        )
    except httpx.TimeoutException:
        logger.warning("Zen auth verify timed out")
        return ValidationResult(valid=False)
    except httpx.RequestError as exc:
        logger.warning("Zen auth verify request failed: %s", exc)
        return ValidationResult(valid=False)
    except Exception as exc:
        logger.exception("Unexpected error during Zen auth verify: %s", exc)
        return ValidationResult(valid=False)

    logger.info("Zen auth verify response: status=%s", response.status_code)

    if 200 <= response.status_code < 300:
        try:
            metadata = response.json()
        except Exception:
            metadata = None
        cache[kh] = metadata
        return ValidationResult(valid=True, cached=False, metadata=metadata)

    if response.status_code in (401, 403):
        return ValidationResult(valid=False)

    logger.warning("Unexpected Zen auth verify status: %s", response.status_code)
    return ValidationResult(valid=False)
