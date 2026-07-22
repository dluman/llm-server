import logging
from contextlib import asynccontextmanager

import httpx
from curl_cffi import requests as curl_requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.config import get_settings
from app.health import router as health_router
from app.proxy.router import router as proxy_router

settings = get_settings()

logging.basicConfig(
    level=logging.getLevelName(settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting %s; upstream base URL=%s",
        settings.app_name,
        settings.canonical_zen_base_url,
    )
    app.state.http_client = httpx.AsyncClient(
        timeout=settings.upstream_timeout_seconds,
        follow_redirects=True,
    )
    # Browser-impersonating client used for upstream Zen requests. Cloudflare's
    # Browser Integrity Check rejects plain httpx/python requests to the paid
    # inference endpoints, so we use curl_cffi to look like a real browser.
    app.state.curl_client = curl_requests.AsyncSession(
        impersonate="chrome120",
        timeout=settings.upstream_timeout_seconds,
    )
    yield
    logger.info("Shutting down")
    await app.state.http_client.aclose()
    await app.state.curl_client.close()


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)

if settings.cors_origins_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(proxy_router)
