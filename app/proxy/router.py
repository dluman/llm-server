import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.dependencies import require_valid_key

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

# Methods that typically have no body.
_NO_BODY_METHODS = {"GET", "HEAD", "DELETE", "OPTIONS"}


@router.api_route(
    "/v1/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def proxy_v1(
    request: Request,
    path: str,
    key: str = Depends(require_valid_key),
):
    """Transparently proxy authenticated requests to the Opencode Zen upstream."""
    settings = get_settings()
    base_url = settings.canonical_zen_base_url.rstrip("/")
    upstream_url = f"{base_url}/v1/{path}"

    query_params: dict[str, Any] = dict(request.query_params)

    forward_headers: dict[str, str] = {}
    for name, value in request.headers.items():
        if name.lower() in _HOP_BY_HOP_HEADERS:
            continue
        forward_headers[name] = value

    # Always attach the validated key to the upstream request.
    forward_headers[settings.zen_api_header] = key

    client: httpx.AsyncClient = request.app.state.http_client
    method = request.method

    body: bytes = b""
    if method not in _NO_BODY_METHODS:
        body = await request.body()

    try:
        upstream_request = client.build_request(
            method=method,
            url=upstream_url,
            params=query_params,
            headers=forward_headers,
            content=body,
        )
        upstream_response = await client.send(upstream_request, stream=True)
    except httpx.TimeoutException:
        logger.warning("Upstream timeout: %s %s", method, upstream_url)
        raise HTTPException(status_code=504, detail="Gateway timeout")
    except httpx.RequestError as exc:
        logger.warning("Upstream request error: %s", exc)
        raise HTTPException(status_code=502, detail="Bad gateway")

    response_headers: dict[str, str] = {}
    for name, value in upstream_response.headers.items():
        if name.lower() in _HOP_BY_HOP_HEADERS:
            continue
        response_headers[name] = value

    async def response_stream():
        try:
            async for chunk in upstream_response.aiter_raw():
                yield chunk
        finally:
            await upstream_response.aclose()

    return StreamingResponse(
        content=response_stream(),
        status_code=upstream_response.status_code,
        headers=response_headers,
    )
