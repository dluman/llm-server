import json
import logging
from typing import Any, Optional

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

_SENSITIVE_OAUTH_KEYS = {"device_code", "access_token", "refresh_token"}


def _redact_json(text: str, keys: set[str] | None = None) -> str:
    """Return a JSON string with sensitive OAuth values redacted."""
    keys = keys or _SENSITIVE_OAUTH_KEYS
    try:
        data = json.loads(text)
    except Exception:
        return text
    if not isinstance(data, dict):
        return text
    for key in keys:
        if key in data:
            data[key] = "<redacted>"
    return json.dumps(data)


class GitHubAuthError(Exception):
    """Raised when a GitHub auth request fails or returns an unexpected error."""


class GitHubPendingError(Exception):
    """Raised during device flow polling when the user has not yet authorized."""


_GRAPHQL_ENTERPRISES_QUERY = """
query($first: Int!, $after: String) {
  viewer {
    enterprises(first: $first, after: $after) {
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

_GRAPHQL_ENTERPRISE_ACCESS_QUERY = """
query($slug: String!) {
  enterprise(slug: $slug) {
    slug
  }
}
"""


async def request_device_code(settings: Settings) -> dict[str, Any]:
    """Request a device code from GitHub to start the device flow."""
    data = {"client_id": settings.github_client_id}
    scopes = settings.github_device_flow_scopes.strip()
    if scopes:
        data["scope"] = scopes

    logger.info(
        "GitHub device code request: client_id=%s scope=%s",
        settings.github_client_id,
        scopes or "<none>",
    )

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            settings.github_device_code_url,
            headers={"Accept": "application/json"},
            data=data,
        )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "GitHub device code request HTTP %s: %s",
            response.status_code,
            _redact_json(response.text),
        )
        raise GitHubAuthError(f"GitHub device code request failed: {exc}") from exc

    logger.info(
        "GitHub device code response HTTP %s: %s",
        response.status_code,
        _redact_json(response.text),
    )

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

    logger.info(
        "GitHub device token poll response HTTP %s: %s",
        response.status_code,
        _redact_json(response.text),
    )

    if "error" in payload:
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

    logger.info(
        "GitHub device token granted scopes: %s",
        payload.get("scope", "<none>"),
    )
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

    logger.info(
        "GitHub /user token scopes: %s; accepted permissions: %s",
        response.headers.get("X-OAuth-Scopes"),
        response.headers.get("X-Accepted-GitHub-Permissions"),
    )
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

        try:
            enterprises = viewer_data["viewer"]["enterprises"]
            if enterprises is None:
                raise KeyError("enterprises")
            nodes = enterprises["nodes"]
            page_info = enterprises["pageInfo"]
        except (KeyError, TypeError) as exc:
            logger.warning(
                "GitHub GraphQL response missing expected enterprise fields (%s): %s",
                exc,
                response.text,
            )
            raise GitHubAuthError(
                "GitHub GraphQL response missing enterprise information; "
                "the token may lack the required enterprise permission"
            ) from exc

        if not isinstance(nodes, list):
            logger.warning(
                "GitHub GraphQL enterprises.nodes is not a list: %s", response.text
            )
            raise GitHubAuthError(
                "GitHub GraphQL returned unexpected enterprise node data"
            )

        for node in nodes:
            if isinstance(node, dict) and "slug" in node:
                slugs.append(node["slug"])
            else:
                logger.warning(
                    "GitHub GraphQL enterprise node is malformed: %s", response.text
                )

        if not page_info.get("hasNextPage"):
            break
        after = page_info.get("endCursor")

    return slugs


async def has_enterprise_access(
    http_client: httpx.AsyncClient, token: str, enterprise_slug: str
) -> bool:
    """Fallback check: query the enterprise directly by slug.

    A non-null response means the token can access the enterprise, which for
    an enterprise's members indicates membership.
    """
    response = await http_client.post(
        "https://api.github.com/graphql",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "query": _GRAPHQL_ENTERPRISE_ACCESS_QUERY,
            "variables": {"slug": enterprise_slug},
        },
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "GitHub enterprise access query HTTP %s: %s",
            response.status_code,
            response.text,
        )
        raise GitHubAuthError(f"GitHub enterprise access query failed: {exc}") from exc

    data = response.json()
    if "errors" in data:
        messages = "; ".join(str(e.get("message", e)) for e in data["errors"])
        logger.warning(
            "GitHub enterprise access query errors: %s; response: %s",
            messages,
            response.text,
        )
        raise GitHubAuthError(f"GitHub GraphQL errors: {messages}")

    enterprise = data.get("data", {}).get("enterprise")
    if enterprise is not None:
        logger.info("GitHub enterprise access query succeeded for %s", enterprise_slug)
        return True

    logger.info(
        "GitHub enterprise access query returned null for %s; user is not a member",
        enterprise_slug,
    )
    return False


async def is_member_of_enterprise(
    http_client: httpx.AsyncClient, token: str, enterprise_slug: str
) -> bool:
    """Check whether the token's user is a member of the configured enterprise."""
    target = enterprise_slug.lower()

    try:
        slugs = await get_user_enterprise_slugs(http_client, token)
        if any(slug.lower() == target for slug in slugs):
            return True
    except GitHubAuthError as exc:
        logger.warning("Primary enterprise membership check failed: %s", exc)

    return await has_enterprise_access(http_client, token, enterprise_slug)
