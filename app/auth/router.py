import logging

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth.github import (
    GitHubAuthError,
    GitHubPendingError,
    get_authenticated_user,
    is_member_of_enterprise,
    poll_device_token,
    request_device_code,
)
from app.auth.session import create_session_token
from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class DevicePollRequest(BaseModel):
    device_code: str


class DeviceCodeResponse(BaseModel):
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


class SessionResponse(BaseModel):
    status: str = "complete"
    github_login: str
    enterprise_slug: str
    session_token: str
    expires_in: int


class PendingResponse(BaseModel):
    status: str = "pending"


def _ensure_auth_enabled(settings) -> None:
    if not settings.github_auth_enabled:
        raise HTTPException(status_code=404, detail="GitHub authentication is disabled")
    if not settings.github_auth_configured:
        raise HTTPException(
            status_code=500,
            detail="GitHub authentication is not fully configured",
        )


async def _create_session_for_token(
    settings,
    http_client,
    github_token: str,
) -> SessionResponse:
    """Validate a GitHub token and enterprise membership, then issue a session."""
    try:
        user = await get_authenticated_user(http_client, github_token)
        is_member = await is_member_of_enterprise(
            http_client,
            github_token,
            settings.github_enterprise_slug,
        )
    except GitHubAuthError as exc:
        logger.warning("GitHub auth failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid GitHub token")

    login = user.get("login")
    if not login:
        raise HTTPException(status_code=502, detail="GitHub user profile missing login")

    if not is_member:
        logger.warning(
            "User %s is not a member of enterprise %s",
            login,
            settings.github_enterprise_slug,
        )
        raise HTTPException(
            status_code=403,
            detail=f"User is not a member of the {settings.github_enterprise_slug} enterprise",
        )

    session_token = create_session_token(
        settings,
        github_login=login,
        enterprise_slug=settings.github_enterprise_slug,
    )

    return SessionResponse(
        github_login=login,
        enterprise_slug=settings.github_enterprise_slug,
        session_token=session_token,
        expires_in=settings.github_session_ttl_seconds,
    )


@router.post("/device/code", response_model=DeviceCodeResponse)
async def device_code(request: Request):
    settings = get_settings()
    _ensure_auth_enabled(settings)
    if not settings.github_device_flow_enabled:
        raise HTTPException(status_code=404, detail="Device flow is disabled")

    try:
        payload = await request_device_code(settings)
    except GitHubAuthError as exc:
        logger.warning("Device code request failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to start GitHub device flow")

    return DeviceCodeResponse(
        device_code=payload["device_code"],
        user_code=payload["user_code"],
        verification_uri=payload["verification_uri"],
        expires_in=payload["expires_in"],
        interval=payload["interval"],
    )


@router.post("/device/poll", response_model=SessionResponse | PendingResponse)
async def device_poll(
    request: Request,
    body: DevicePollRequest,
):
    settings = get_settings()
    _ensure_auth_enabled(settings)
    if not settings.github_device_flow_enabled:
        raise HTTPException(status_code=404, detail="Device flow is disabled")

    try:
        token_payload = await poll_device_token(settings, body.device_code)
    except GitHubPendingError:
        return JSONResponse(status_code=202, content={"status": "pending"})
    except GitHubAuthError as exc:
        logger.warning("Device poll failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))

    github_token = token_payload["access_token"]
    http_client = request.app.state.http_client
    return await _create_session_for_token(settings, http_client, github_token)


@router.post("/token", response_model=SessionResponse)
async def token_exchange(
    request: Request,
    authorization: str = Header(..., alias="Authorization"),
):
    settings = get_settings()
    _ensure_auth_enabled(settings)
    if not settings.github_direct_token_enabled:
        raise HTTPException(status_code=404, detail="Direct token exchange is disabled")

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Authorization header must be 'Bearer <github-token>'",
        )

    github_token = authorization[7:].strip()
    if not github_token:
        raise HTTPException(status_code=401, detail="Missing GitHub token")

    http_client = request.app.state.http_client
    return await _create_session_for_token(settings, http_client, github_token)
