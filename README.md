# OpenCode API Proxy

A FastAPI service that authenticates users via a GitHub Enterprise membership and an `X-Zen-Api-Key` header, validates the key against the Opencode Zen API (`llm.chompe.rs`), and proxies all `/v1/*` requests to the upstream.

## Features

- GitHub Enterprise membership gate: only members of any org in a configured enterprise can access the proxy
- GitHub OAuth device flow for non-interactive clients
- Optional direct GitHub token exchange for service accounts
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
| `GITHUB_AUTH_ENABLED` | `true` | Enable GitHub Enterprise auth |
| `GITHUB_CLIENT_ID` | `""` | GitHub App client ID |
| `GITHUB_CLIENT_SECRET` | `""` | GitHub App client secret |
| `GITHUB_ENTERPRISE_SLUG` | `""` | Enterprise slug to restrict access to |
| `GITHUB_SESSION_TTL_SECONDS` | `28800` | Session token lifetime |
| `GITHUB_DEVICE_FLOW_ENABLED` | `true` | Enable `/auth/device/*` endpoints |
| `GITHUB_DIRECT_TOKEN_ENABLED` | `true` | Enable `/auth/token` exchange |
| `GITHUB_DEVICE_FLOW_SCOPES` | `""` | OAuth scopes to request (e.g. `read:org read:enterprise`) |
| `SESSION_SECRET_KEY` | `""` | Secret for signing session JWTs (min 32 bytes) |

> **Note:** The enterprise-membership GraphQL query requires the `read:enterprise` OAuth scope. GitHub Apps cannot grant this scope, so the device flow must be backed by a **GitHub OAuth App** (not a GitHub App) with `GITHUB_DEVICE_FLOW_SCOPES=read:org read:enterprise`. Direct token exchange works with any token that has those scopes.

## Authentication

The proxy requires two gates for every `/v1/*` request:

1. A valid session token proving the caller is a member of the configured GitHub Enterprise.
2. A valid Zen API key.

### Device flow (recommended for CLI/automated clients)

1. Start the flow:
   ```bash
   curl -X POST https://your-app.ondigitalocean.app/auth/device/code
   ```
2. Open the returned `verification_uri` and enter the `user_code`.
3. Poll until complete:
   ```bash
   curl -X POST https://your-app.ondigitalocean.app/auth/device/poll \
        -H "Content-Type: application/json" \
        -d '{"device_code": "<device_code>"}'
   ```
4. Use the returned `session_token` on subsequent requests.

### Direct token exchange (limited/service-account use)

```bash
curl -X POST https://your-app.ondigitalocean.app/auth/token \
     -H "Authorization: Bearer <github-token>"
```

## Example request

```bash
curl -H "Authorization: Bearer $SESSION_TOKEN" \
     -H "X-Zen-Api-Key: $YOUR_ZEN_KEY" \
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
