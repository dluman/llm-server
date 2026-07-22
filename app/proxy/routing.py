import logging

logger = logging.getLogger(__name__)


def _normalize_model(model_id: str | None) -> str:
    """Strip provider prefixes (e.g., opencode/gpt-5.5 -> gpt-5.5)."""
    if not isinstance(model_id, str):
        return ""
    model_id = model_id.strip()
    if "/" in model_id:
        model_id = model_id.rsplit("/", 1)[-1]
    return model_id.strip()


def resolve_zen_endpoint(model_id: str | None) -> str:
    """Map a model identifier to the correct OpenCode Zen endpoint path.

    References the Zen routing rules:
    - GPT-family models (gpt-*, o1-*, o3-*, chatgpt-*) -> /v1/responses
    - Claude and Qwen models -> /v1/messages
    - Gemini models -> /v1/models/{model}
    - Everything else -> /v1/chat/completions
    """
    if not model_id:
        return "chat/completions"

    model = _normalize_model(model_id).lower()
    if not model:
        return "chat/completions"

    if (
        model.startswith("gpt-")
        or model.startswith("o1-")
        or model.startswith("o3-")
        or model.startswith("chatgpt-")
    ):
        return "responses"

    if model.startswith("claude-") or model.startswith("qwen"):
        return "messages"

    if model.startswith("gemini-"):
        return f"models/{model}"

    return "chat/completions"
