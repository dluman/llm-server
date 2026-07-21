import pytest
from unittest.mock import AsyncMock, MagicMock

from app.auth.zen import ValidationResult, _get_cache, validate_key


@pytest.fixture(autouse=True)
def clear_key_cache():
    _get_cache().clear()
    yield


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.mark.asyncio
async def test_validate_key_success_and_cache(mock_client):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"user": "alice"}
    mock_client.get = AsyncMock(return_value=response)

    result = await validate_key(mock_client, "valid-key")
    assert result == ValidationResult(valid=True, cached=False, metadata={"user": "alice"})

    cached = await validate_key(mock_client, "valid-key")
    assert cached == ValidationResult(valid=True, cached=True, metadata={"user": "alice"})

    mock_client.get.assert_called_once()


@pytest.mark.asyncio
async def test_validate_key_unauthorized(mock_client):
    response = MagicMock()
    response.status_code = 401
    mock_client.get = AsyncMock(return_value=response)

    result = await validate_key(mock_client, "invalid-key")
    assert result.valid is False


@pytest.mark.asyncio
async def test_validate_key_upstream_error(mock_client):
    mock_client.get = AsyncMock(side_effect=Exception("boom"))

    result = await validate_key(mock_client, "any-key")
    assert result.valid is False
