# model-gateway

[![CI](https://github.com/gperdrizet/model-gateway/actions/workflows/ci.yml/badge.svg)](https://github.com/gperdrizet/model-gateway/actions/workflows/ci.yml)
[![Deploy to Production](https://github.com/gperdrizet/model-gateway/actions/workflows/deploy-prod.yml/badge.svg)](https://github.com/gperdrizet/model-gateway/actions/workflows/deploy-prod.yml)
[![Python](https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-compose-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

An authenticated, metered API gateway for llama-server.

> **Model backend**: [gperdrizet/llama.cpp](https://github.com/gperdrizet/llama.cpp) — llama-server running on a dedicated model server with a Tesla P100 GPU

Sits in front of a running llama.cpp instance and adds user registration, token-based billing, and an admin panel.

## How it works

- Users register at `/register` and receive a trial allocation (500k tokens, 14 days)
- API calls are made to `/v1/...` with a Bearer token — compatible with the OpenAI client SDK
- Each request deducts tokens from the user's balance; requests are rejected with 402 when exhausted
- Users can top up via Stripe (card) or BTCPay Server (Bitcoin)
- All usage is recorded for metering and display on the dashboard

## Stack

- **FastAPI** + uvicorn — API server
- **PostgreSQL** — user accounts, token balances, usage events, purchases
- **Docker Compose** — gateway + db + adminer
- **nginx** — TLS termination and reverse proxy on the gateway server

---

## Development

### Requirements

- Python 3.12
- Docker + Docker Compose

### Setup

```bash
git clone git@github.com:gperdrizet/model-gateway.git
cd model-gateway
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.template .env
# Edit .env — set DATABASE_URL, LLAMA_BASE_URL, etc.
```

### Run locally

```bash
docker compose up -d db          # start postgres only
uvicorn app.app:app --reload --port 8503
```

Or run the full stack:

```bash
docker compose up --build
```

### Run tests

```bash
pytest tests/ -v
```

Tests use an in-memory SQLite database — no Docker required. All 17 tests should pass.

---

## Deployment

### Infrastructure

- **Model server** — runs llama-server on `:8502`, accessible over a private WireGuard tunnel
- **Gateway server** — VPS running nginx + Docker; model-gateway runs here behind nginx

### Production stack on the gateway server

```
/opt/model-gateway/          ← production git repo + .env
/opt/model-gateway-staging/  ← staging git repo + .env
```

nginx proxies `https://<your-domain>` → `http://127.0.0.1:8503` (production gateway).

### Environment files

Copy `.env.template` and fill in values. Key production overrides vs. defaults:

| Variable | Production value |
|---|---|
| `BASE_URL` | `https://model.perdrizet.org` |
| `LLAMA_BASE_URL` | `http://100.64.0.2:8502` |
| `ADMINER_BIND_HOST` | `100.64.0.1` (tailnet only) |
| `GATEWAY_BIND` | `127.0.0.1` (behind nginx) |
| `GATEWAY_PORT` | `8503` |

Staging `.env` is the same but with `GATEWAY_PORT=8505`, `ADMINER_PORT=8506`, and `BASE_URL=http://127.0.0.1:8505`.

---

## CI/CD

### Branches

- **`dev`** — active development branch. All work happens here.
- **`main`** — production-ready code only. Protected — direct pushes are blocked.

### Workflow

1. Work on `dev`, commit and push changes
2. Open a pull request `dev → main`
3. GitHub Actions runs the test suite automatically on the PR
4. Branch protection blocks merge until all tests pass
5. Merge the PR — staging deploy triggers automatically
6. Verify staging at port `8505`, then trigger production deploy manually

### On every push to `main` (after PR merge)

1. GitHub Actions runs the test suite (`pytest tests/ -v`)
2. If tests pass, SSHs to the gateway server and deploys to staging at port `8505`
3. Smoke tests `http://127.0.0.1:8505/health`

### Production deploy

Manual trigger only — go to **Actions → Deploy to Production → Run workflow**, enter a version number (e.g. `1.0.0`) and type `deploy` to confirm.

The workflow:
1. SSHs to the gateway server, pulls the latest commit into `/opt/model-gateway/`
2. Runs `docker compose up --build -d`
3. Smoke tests the health endpoint
4. Tags the commit as `v<version>` and creates a GitHub release with auto-generated notes

### Required GitHub secrets

| Secret | Value |
|---|---|
| `GATEKEEPER_HOST` | Gateway server public IP |
| `GATEKEEPER_USER` | SSH username on the gateway server |
| `GATEKEEPER_SSH_KEY` | Private key (matching public key in gateway server's `authorized_keys`) |

Generate a dedicated deploy key:
```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/github_deploy -N ""
# Add ~/.ssh/github_deploy.pub to the gateway server's authorized_keys
# Add contents of ~/.ssh/github_deploy as the GATEKEEPER_SSH_KEY secret
```

---

## Admin panel

The admin panel is at `/admin?key=<ADMIN_KEY>`.

Access is restricted to two layers:
1. **`ADMIN_KEY`** — must match the `ADMIN_KEY` env var (compared in constant time)
2. **IP CIDR check** — request must come from the private WireGuard/tailnet range, localhost, or Docker bridge. Configured via `ADMIN_ALLOWED_CIDRS` in `.env`.

From outside the private network, `/admin` returns 403 regardless of key.

### Admin panel features

- View all users — email, key prefix, token balance, trial status, 30-day usage, join date
- **Adjust tokens** — add or subtract tokens from any user's paid balance (positive or negative delta)
- **Grant trial** — give a user a new trial allocation (tokens + days)
- **Delete user** — permanently removes the user and all associated records
- Email filter search box for finding users quickly

### Adminer (database GUI)

Adminer runs at port `8504` (production) or `8506` (staging), bound to the private WireGuard/tailnet IP on the gateway server — not accessible from the public internet.

Access from a machine on the private network:
```
http://<tailnet-ip>:8504
Server: db
Username: gateway
Password: (POSTGRES_PASSWORD from .env)
Database: gateway
```

---

## Billing

### Stripe

Set `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` in `.env`. Register a webhook at `https://<your-domain>/stripe/webhook` in the Stripe dashboard with the `checkout.session.completed` event.

### BTCPay Server (Bitcoin)

A separate compose stack (`docker-compose.btcpay.yml`) runs BTCPay Server bound to your private network IP. Set `BTCPAY_URL`, `BTCPAY_API_KEY`, `BTCPAY_STORE_ID`, and `BTCPAY_WEBHOOK_SECRET` in `.env` after configuring the store.

---

## Token packs

| Pack | Tokens | Price |
|---|---|---|
| `starter` | 5M | $0.50 |
| `standard` | 25M | $2.00 |
| `pro` | 100M | $6.00 |
