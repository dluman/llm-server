from fastapi import Header, HTTPException, Request

from app.auth.zen import ValidationResult, validate_key


async def require_valid_key(
    request: Request,
    x_zen_api_key: str = Header(..., alias="X-Zen-Api-Key"),
) -> str:
    """FastAPI dependency that validates the X-Zen-Api-Key header.

    Returns the key on success; raises HTTPException(401) on failure.
    """
    client = request.app.state.http_client
    result: ValidationResult = await validate_key(client, x_zen_api_key)
    if not result.valid:
        raise HTTPException(status_code=401, detail="Invalid or expired Zen API key")

    request.state.zen_key = x_zen_api_key
    request.state.zen_validation = result
    return x_zen_api_key
