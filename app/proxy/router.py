import json
import logging
from typing import Any

from curl_cffi.requests import errors as curl_errors
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.dependencies import require_github_session, require_valid_key
from app.proxy.routing import resolve_zen_endpoint

logger = logging.getLogger(__name__)

router = APIRouter()

_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
}

# Headers curl_cffi manages as part of browser impersonation. Forwarding a
# non-browser User-Agent or Accept-* value from the client can break BIC bypass.
_CURL_MANAGED_HEADERS = {
    "user-agent",
    "accept",
    "accept-encoding",
    "accept-language",
}

# Methods that typically have no body.
_NO_BODY_METHODS = {"GET", "HEAD", "DELETE", "OPTIONS"}


@router.api_route(
    "/v1/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def proxy_v1(
    request: Request,
    path: str,
    github_login: str = Depends(require_github_session),
    key: str = Depends(require_valid_key),
):
    """Transparently proxy authenticated requests to the Opencode Zen upstream."""
    settings = get_settings()
    query_params: dict[str, Any] = dict(request.query_params)

    forward_headers: dict[str, str] = {}
    for name, value in request.headers.items():
        lower = name.lower()
        if lower in _HOP_BY_HOP_HEADERS or lower in _CURL_MANAGED_HEADERS:
            continue
        forward_headers[name] = value

    # The client sends Authorization: Bearer <github_session> for GitHub auth
    # and X-Zen-Api-Key: <key> for Zen.  We strip both before forwarding, then
    # attach the validated Zen key as Authorization: Bearer for the upstream.
    forward_headers = {
        k: v
        for k, v in forward_headers.items()
        if k.lower() not in {"authorization", settings.zen_api_header.lower()}
    }
    forward_headers["Authorization"] = f"Bearer {key}"

    base_url = settings.canonical_zen_base_url.rstrip("/")
    upstream_url = f"{base_url}/v1/{path}"

    method = request.method
    body: bytes = b""
    if method not in _NO_BODY_METHODS:
        body = await request.body()

    # Route chat completion requests to the correct Zen endpoint based on the
    # requested model.
    if method == "POST" and path.strip("/") == "chat/completions":
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning(
                "Model-aware routing skipped: could not parse chat completion body"
            )
            payload = None

        if isinstance(payload, dict):
            model_id = payload.get("model")
            endpoint = resolve_zen_endpoint(model_id)
            upstream_url = f"{base_url}/v1/{endpoint}"
            logger.info(
                "Model-aware routing: model=%s resolved_endpoint=%s upstream=%s",
                model_id,
                endpoint,
                upstream_url,
            )

    logger.info(
        "Proxy request: method=%s path=%s upstream=%s user=%s key_present=%s",
        request.method,
        path,
        upstream_url,
        getattr(request.state, "github_login", None),
        bool(key),
    )

    curl_client = request.app.state.curl_client
    try:
        upstream_response = await curl_client.request(
            method=method,
            url=upstream_url,
            params=query_params,
            headers=forward_headers,
            data=body,
            stream=True,
        )
    except curl_errors.RequestsError as exc:
        if exc.code == 28:  # CURLE_OPERATION_TIMEDOUT
            logger.warning("Upstream timeout: %s %s", method, upstream_url)
            raise HTTPException(status_code=504, detail="Gateway timeout") from exc
        logger.warning("Upstream request error: %s", exc)
        raise HTTPException(status_code=502, detail="Bad gateway") from exc
    except Exception as exc:
        logger.warning("Upstream request error: %s", exc)
        raise HTTPException(status_code=502, detail="Bad gateway") from exc

    response_headers: dict[str, str] = {}
    for name, value in upstream_response.headers.items():
        lower = name.lower()
        # curl_cffi decompresses encoded responses; don't forward the encoding.
        if lower in _HOP_BY_HOP_HEADERS or lower == "content-encoding":
            continue
        response_headers[name] = value

    async def response_stream():
        try:
            async for chunk in upstream_response.aiter_content():
                yield chunk
        finally:
            await upstream_response.aclose()

    logger.info(
        "Proxy response: method=%s path=%s upstream=%s upstream_status=%s",
        request.method,
        path,
        upstream_url,
        upstream_response.status_code,
    )
    return StreamingResponse(
        content=response_stream(),
        status_code=upstream_response.status_code,
        headers=response_headers,
    )
