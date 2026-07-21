# OpenCode API Proxy

A FastAPI service that authenticates users via an `X-Zen-Api-Key` header, validates the key against the Opencode Zen API (`llm.chompe.rs`), and proxies all `/v1/*` requests to the upstream.

## Features

- Custom header API-key auth: `X-Zen-Api-Key`
- Validation forwarded to Opencode Zen at `https://llm.chompe.rs/v1/auth/verify`
- In-memory TTL cache for successful validations (saves bandwidth)
- Transparent streaming proxy for all `/v1/{path:path}` endpoints
- `/health` endpoint for DigitalOcean App Platform health checks

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Environment variables

Copy `.env.example` to `.env` and adjust:

| Variable | Default | Description |
|----------|---------|-------------|
| `ZEN_BASE_URL` | `https://llm.chompe.rs` | Upstream base URL |
| `ZEN_AUTH_VERIFY_URL` | `https://llm.chompe.rs/v1/auth/verify` | Key validation endpoint |
| `ZEN_API_HEADER` | `X-Zen-Api-Key` | Header clients must send |
| `AUTH_CACHE_TTL_SECONDS` | `300` | How long to cache successful validations |
| `AUTH_CACHE_MAX_SIZE` | `10000` | Max cached keys |
| `UPSTREAM_TIMEOUT_SECONDS` | `60` | Timeout for upstream requests |
| `CORS_ORIGINS` | `""` | Optional comma-separated allowed origins |
| `LOG_LEVEL` | `info` | Logging level |

## Example request

```bash
curl -H "X-Zen-Api-Key: $YOUR_ZEN_KEY" \
     https://your-app.ondigitalocean.app/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{"model": "...", "messages": [{"role": "user", "content": "hi"}]}'
```

## Deploy to DigitalOcean App Platform

1. Push this repo to GitHub.
2. In DigitalOcean App Platform, create a new app from the GitHub repo.
3. Use the `.do/app.yaml` spec or configure manually:
   - **Build command:** `pip install -r requirements.txt`
   - **Run command:** `uvicorn app.main:app --host 0.0.0.0 --port 8080`
   - **Health check path:** `/health`
4. Set the environment variables in the App Platform console.
5. Deploy.

## Testing

```bash
pytest
```
