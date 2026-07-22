import pytest
from fastapi.testclient import TestClient

from app.dependencies import require_github_session, require_valid_key
from app.main import app
from app.proxy.routing import resolve_zen_endpoint


class _FakeRequestsResponse:
    status_code = 200
    headers = {"content-type": "application/json"}
    content = b'{"ok": true}'

    def iter_content(self, chunk_size=8192):
        yield b'{"ok": true}'

    def close(self):
        pass


class _FakeRequestsSession:
    last_call: dict | None = None

    def request(self, **kwargs):
        self.last_call = kwargs
        return _FakeRequestsResponse()

    def close(self):
        pass


def _fake_session():
    return "test-user"


def _fake_key():
    return "test-key"


@pytest.mark.parametrize(
    "model_id,expected_endpoint",
    [
        ("gpt-5.5", "responses"),
        ("opencode/gpt-5.5", "responses"),
        ("o1-pro", "responses"),
        ("o3-mini", "responses"),
        ("chatgpt-4o", "responses"),
        ("claude-sonnet-5", "messages"),
        ("qwen2.5", "messages"),
        ("qwen-max", "messages"),
        ("gemini-3.6-flash", "models/gemini-3.6-flash"),
        ("opencode/gemini-3.6-flash", "models/gemini-3.6-flash"),
        ("deepseek-v4-pro", "chat/completions"),
        ("grok-4", "chat/completions"),
        ("minimax-text-01", "chat/completions"),
        ("glm-5", "chat/completions"),
        ("kimi-k2", "chat/completions"),
        ("big-pickle-4", "chat/completions"),
        ("mimo-7b", "chat/completions"),
        ("laguna-1", "chat/completions"),
        ("north-1", "chat/completions"),
        ("nemotron-1", "chat/completions"),
        ("", "chat/completions"),
        (None, "chat/completions"),
    ],
)
def test_resolve_zen_endpoint(model_id, expected_endpoint):
    assert resolve_zen_endpoint(model_id) == expected_endpoint


def test_proxy_v1_routes_to_chat_completions():
    fake_session = _FakeRequestsSession()
    app.dependency_overrides[require_github_session] = _fake_session
    app.dependency_overrides[require_valid_key] = _fake_key

    try:
        with TestClient(app) as client:
            client.app.state.requests_session = fake_session
            response = client.post(
                "/v1/chat/completions",
                json={"model": "deepseek-v4-flash", "messages": [{"role": "user", "content": "hi"}]},
                headers={"X-Zen-Api-Key": "test-key"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert fake_session.last_call is not None
    assert fake_session.last_call["url"] == "https://opencode.ai/zen/v1/chat/completions"
    assert fake_session.last_call["method"] == "POST"
    assert fake_session.last_call["headers"]["Authorization"] == "Bearer test-key"


def test_proxy_v1_gemini_routes_to_models():
    fake_session = _FakeRequestsSession()
    app.dependency_overrides[require_github_session] = _fake_session
    app.dependency_overrides[require_valid_key] = _fake_key

    try:
        with TestClient(app) as client:
            client.app.state.requests_session = fake_session
            response = client.post(
                "/v1/chat/completions",
                json={"model": "gemini-3.6-flash", "messages": [{"role": "user", "content": "hi"}]},
                headers={"X-Zen-Api-Key": "test-key"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert fake_session.last_call["url"] == "https://opencode.ai/zen/v1/models/gemini-3.6-flash"


def test_proxy_accepts_openai_client_headers():
    """Verify the proxy accepts the exact headers the openai library sends."""
    fake_session = _FakeRequestsSession()
    app.dependency_overrides[require_github_session] = _fake_session
    app.dependency_overrides[require_valid_key] = _fake_key

    try:
        with TestClient(app) as client:
            client.app.state.requests_session = fake_session
            # The openai library sends Authorization: Bearer <session>
            # and X-Zen-Api-Key as a default header.
            response = client.post(
                "/v1/chat/completions",
                json={"model": "deepseek-v4-flash", "messages": [{"role": "user", "content": "hi"}]},
                headers={
                    "Authorization": "Bearer test-github-session-token",
                    "X-Zen-Api-Key": "test-key",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert fake_session.last_call is not None
    assert fake_session.last_call["url"] == "https://opencode.ai/zen/v1/chat/completions"
    assert fake_session.last_call["method"] == "POST"
    # The proxy strips both client auth headers and injects the Zen key
    assert fake_session.last_call["headers"]["Authorization"] == "Bearer test-key"
    # The proxy should not forward the client's Authorization header
    assert fake_session.last_call["headers"].get("X-Zen-Api-Key") is None

