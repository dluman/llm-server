from functools import lru_cache
from urllib.parse import urlparse

from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "opencode-api"
    log_level: str = "info"

    zen_base_url: str = "https://llm.chompe.rs"
    zen_auth_verify_url: str = "https://llm.chompe.rs/v1/auth/verify"
    zen_api_header: str = "X-Zen-Api-Key"

    auth_cache_ttl_seconds: int = 300
    auth_cache_max_size: int = 10000

    upstream_timeout_seconds: float = 60.0
    proxy_prefix: str = "/v1"

    cors_origins: str = ""

    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")

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
