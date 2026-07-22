import logging
from typing import Any, Optional

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class GitHubAuthError(Exception):
    """Raised when a GitHub auth request fails or returns an unexpected error."""


class GitHubPendingError(Exception):
    """Raised during device flow polling when the user has not yet authorized."""


_GRAPHQL_ENTERPRISES_QUERY = """
query($first: Int!, $after: String) {
  viewer {
    enterprises(first: $first, after: $after, membershipType: ORG_MEMBERSHIP) {
      nodes {
        slug
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""


async def request_device_code(settings: Settings) -> dict[str, Any]:
    """Request a device code from GitHub to start the device flow."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            settings.github_device_code_url,
            headers={"Accept": "application/json"},
            data={"client_id": settings.github_client_id},
        )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "GitHub device code request HTTP %s: %s",
            response.status_code,
            response.text,
        )
        raise GitHubAuthError(f"GitHub device code request failed: {exc}") from exc

    payload = response.json()
    if "error" in payload:
        raise GitHubAuthError(
            f"GitHub device code request failed: {payload.get('error_description', payload['error'])}"
        )
    return payload


async def poll_device_token(settings: Settings, device_code: str) -> dict[str, Any]:
    """Poll GitHub for a user access token using a device code.

    Raises GitHubPendingError if authorization is still pending, or
    GitHubAuthError for any other error.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            settings.github_access_token_url,
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )

    # GitHub returns 200 even for pending/errors in the OAuth flow.
    payload = response.json()
    if "error" in payload:
        logger.warning(
            "GitHub device token poll error response: %s",
            response.text,
        )
        error = payload["error"]
        if error == "authorization_pending":
            raise GitHubPendingError("Authorization pending")
        if error == "slow_down":
            raise GitHubPendingError("Slow down")
        if error == "expired_token":
            raise GitHubAuthError("Device code expired")
        raise GitHubAuthError(
            f"GitHub token request failed: {payload.get('error_description', error)}"
        )

    if "access_token" not in payload:
        raise GitHubAuthError("GitHub token response missing access_token")

    return payload


async def get_authenticated_user(
    http_client: httpx.AsyncClient, token: str
) -> dict[str, Any]:
    """Fetch the authenticated GitHub user's profile."""
    response = await http_client.get(
        "https://api.github.com/user",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "GitHub /user request HTTP %s: %s",
            response.status_code,
            response.text,
        )
        raise GitHubAuthError(f"Failed to fetch GitHub user: {exc}") from exc
    return response.json()


async def get_user_enterprise_slugs(
    http_client: httpx.AsyncClient, token: str
) -> list[str]:
    """Return all enterprise slugs where the token's user is a member via an org."""
    slugs: list[str] = []
    after: Optional[str] = None
    max_pages = 10

    for _ in range(max_pages):
        response = await http_client.post(
            "https://api.github.com/graphql",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "query": _GRAPHQL_ENTERPRISES_QUERY,
                "variables": {"first": 100, "after": after},
            },
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "GitHub GraphQL request HTTP %s: %s",
                response.status_code,
                response.text,
            )
            raise GitHubAuthError(f"GitHub GraphQL request failed: {exc}") from exc

        data = response.json()
        if not isinstance(data, dict):
            logger.warning("GitHub GraphQL returned non-JSON/dict response: %s", response.text)
            raise GitHubAuthError("GitHub GraphQL returned an unexpected response")

        if "errors" in data:
            messages = "; ".join(
                str(e.get("message", e)) for e in data["errors"]
            )
            logger.warning("GitHub GraphQL errors: %s; response: %s", messages, response.text)
            raise GitHubAuthError(f"GitHub GraphQL errors: {messages}")

        viewer_data = data.get("data")
        if viewer_data is None:
            logger.warning("GitHub GraphQL returned null data: %s", response.text)
            raise GitHubAuthError(
                "GitHub GraphQL returned no data; the token may lack the required enterprise permission"
            )
        enterprises = viewer_data.get("viewer", {}).get("enterprises")
        if enterprises is None:
            logger.warning("GitHub GraphQL missing enterprises field: %s", response.text)
            raise GitHubAuthError(
                "GitHub GraphQL response missing enterprise information"
            )
        slugs.extend(node["slug"] for node in enterprises["nodes"])

        page_info = enterprises["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        after = page_info["endCursor"]

    return slugs


async def is_member_of_enterprise(
    http_client: httpx.AsyncClient, token: str, enterprise_slug: str
) -> bool:
    """Check whether the token's user is a member of the configured enterprise."""
    slugs = await get_user_enterprise_slugs(http_client, token)
    target = enterprise_slug.lower()
    return any(slug.lower() == target for slug in slugs)
