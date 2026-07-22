import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock

import app.auth.router as auth_router
import app.dependencies as dependencies
from app.auth.github import GitHubPendingError
from app.auth.session import create_session_token
from app.auth.zen import ValidationResult
from app.config import Settings
from app.main import app as fastapi_app


@pytest.fixture
def client():
    with TestClient(fastapi_app) as test_client:
        yield test_client


@pytest.fixture
def auth_settings() -> Settings:
    return Settings(
        github_auth_enabled=True,
        github_client_id="test_client_id",
        github_client_secret="test_client_secret",
        github_enterprise_slug="test-enterprise",
        session_secret_key="a-very-long-secret-key-for-hs256-signing-32b",
        github_device_flow_enabled=True,
        github_direct_token_enabled=True,
        github_session_ttl_seconds=28800,
    )


@pytest.fixture
def member_mocks(auth_settings, monkeypatch):
    """Patch GitHub user/profile and enterprise membership checks to succeed."""
    monkeypatch.setattr(auth_router, "get_settings", lambda: auth_settings)
    monkeypatch.setattr(
        auth_router, "get_authenticated_user", AsyncMock(return_value={"login": "octocat"})
    )
    monkeypatch.setattr(
        auth_router, "is_member_of_enterprise", AsyncMock(return_value=True)
    )


def test_device_code_success(client, auth_settings, monkeypatch):
    monkeypatch.setattr(auth_router, "get_settings", lambda: auth_settings)
    monkeypatch.setattr(
        auth_router,
        "request_device_code",
        AsyncMock(
            return_value={
                "device_code": "dc123",
                "user_code": "WDJB-MJHT",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 5,
            }
        ),
    )

    response = client.post("/auth/device/code")

    assert response.status_code == 200
    data = response.json()
    assert data["user_code"] == "WDJB-MJHT"
    assert data["device_code"] == "dc123"


def test_device_poll_success(client, member_mocks, monkeypatch):
    monkeypatch.setattr(
        auth_router,
        "poll_device_token",
        AsyncMock(return_value={"access_token": "ghu_test"}),
    )

    response = client.post("/auth/device/poll", json={"device_code": "dc123"})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "complete"
    assert data["github_login"] == "octocat"
    assert data["enterprise_slug"] == "test-enterprise"
    assert "session_token" in data


def test_device_poll_pending(client, auth_settings, monkeypatch):
    monkeypatch.setattr(auth_router, "get_settings", lambda: auth_settings)

    async def _pending(*args, **kwargs):
        raise GitHubPendingError("Authorization pending")

    monkeypatch.setattr(auth_router, "poll_device_token", _pending)

    response = client.post("/auth/device/poll", json={"device_code": "dc123"})

    assert response.status_code == 202
    assert response.json()["status"] == "pending"


def test_token_exchange_success(client, member_mocks):
    response = client.post(
        "/auth/token", headers={"Authorization": "Bearer ghu_test"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["github_login"] == "octocat"
    assert data["enterprise_slug"] == "test-enterprise"
    assert "session_token" in data


def test_token_exchange_not_member(client, auth_settings, monkeypatch):
    monkeypatch.setattr(auth_router, "get_settings", lambda: auth_settings)
    monkeypatch.setattr(
        auth_router, "get_authenticated_user", AsyncMock(return_value={"login": "octocat"})
    )
    monkeypatch.setattr(
        auth_router, "is_member_of_enterprise", AsyncMock(return_value=False)
    )

    response = client.post(
        "/auth/token", headers={"Authorization": "Bearer ghu_test"}
    )

    assert response.status_code == 403


def test_token_exchange_invalid_header(client, auth_settings, monkeypatch):
    monkeypatch.setattr(auth_router, "get_settings", lambda: auth_settings)

    response = client.post(
        "/auth/token", headers={"Authorization": "Basic ghu_test"}
    )

    assert response.status_code == 401


def test_device_flow_disabled(client, auth_settings, monkeypatch):
    disabled = auth_settings.model_copy(update={"github_device_flow_enabled": False})
    monkeypatch.setattr(auth_router, "get_settings", lambda: disabled)

    response = client.post("/auth/device/code")

    assert response.status_code == 404


def test_session_token_round_trip(auth_settings):
    token = create_session_token(auth_settings, "octocat", "test-enterprise")
    from app.auth.session import verify_session_token

    payload = verify_session_token(auth_settings, token)
    assert payload["sub"] == "octocat"
    assert payload["ent"] == "test-enterprise"


def test_proxy_requires_session_and_zen_key(client, auth_settings, monkeypatch):
    """A valid session token + valid Zen key should pass the auth gates and reach the proxy."""
    monkeypatch.setattr(dependencies, "get_settings", lambda: auth_settings)
    monkeypatch.setattr(
        dependencies,
        "validate_key",
        AsyncMock(return_value=ValidationResult(valid=True)),
    )

    session_token = create_session_token(auth_settings, "octocat", "test-enterprise")
    response = client.get(
        "/v1/models",
        headers={
            "Authorization": f"Bearer {session_token}",
            "X-Zen-Api-Key": "zen-key",
        },
    )

    # We do not mock the upstream Zen API, so expect a gateway error rather than 401.
    assert response.status_code != 401


def test_proxy_rejects_missing_session(client, auth_settings, monkeypatch):
    monkeypatch.setattr(dependencies, "get_settings", lambda: auth_settings)

    response = client.get(
        "/v1/models",
        headers={"X-Zen-Api-Key": "zen-key"},
    )

    assert response.status_code == 401
    assert "session token" in response.json()["detail"].lower()
