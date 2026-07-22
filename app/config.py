from functools import lru_cache
from urllib.parse import urlparse

from pydantic import ConfigDict, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "opencode-api"
    log_level: str = "info"

    zen_base_url: str = "https://opencode.ai/zen"
    zen_auth_verify_url: str = "https://opencode.ai/zen/v1/models"
    zen_api_header: str = "X-Zen-Api-Key"

    # Optional Cloudflare Worker relay. If set, /v1/* requests are routed through
    # the worker with X-Relay-Token authentication. Useful when the upstream
    # blocks the app's hosting IPs.
    zen_worker_url: str = ""
    zen_worker_token: str = ""

    auth_cache_ttl_seconds: int = 300
    auth_cache_max_size: int = 10000

    upstream_timeout_seconds: float = 60.0
    proxy_prefix: str = "/v1"

    cors_origins: str = ""

    # GitHub Enterprise auth
    github_auth_enabled: bool = True
    github_client_id: str = ""
    github_client_secret: str = ""
    github_enterprise_slug: str = ""
    github_session_ttl_seconds: int = 28800
    github_device_flow_enabled: bool = True
    github_direct_token_enabled: bool = True
    github_device_flow_scopes: str = ""
    session_secret_key: str = ""

    github_graphql_url: str = "https://api.github.com/graphql"
    github_access_token_url: str = "https://github.com/login/oauth/access_token"
    github_device_code_url: str = "https://github.com/login/device/code"

    @field_validator("session_secret_key")
    @classmethod
    def _validate_session_secret_key(cls, v: str, info) -> str:
        if info.data.get("github_auth_enabled") and v and len(v) < 32:
            raise ValueError(
                "SESSION_SECRET_KEY must be at least 32 bytes when GitHub auth is enabled"
            )
        return v

    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def github_auth_configured(self) -> bool:
        return bool(
            self.github_client_id
            and self.github_client_secret
            and self.github_enterprise_slug
            and self.session_secret_key
        )

    @property
    def canonical_zen_base_url(self) -> str:
        url = self.zen_base_url.strip()
        parsed = urlparse(url)
        if not parsed.scheme:
            return f"https://{url}"
        return url

    @property
    def cors_origins_list(self) -> list[str]:
        origins = self.cors_origins.strip()
        if not origins:
            return []
        return [o.strip() for o in origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
