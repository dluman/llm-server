import pytest

from app.proxy.routing import resolve_zen_endpoint


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
