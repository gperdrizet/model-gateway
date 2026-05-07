# model-gateway

An authenticated, metered API gateway for llama-server. Sits in front of a running llama.cpp instance and adds user registration, token-based billing, and an admin panel.

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
- **nginx** — TLS termination and reverse proxy on gatekeeper

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

- **pyrite** — runs llama-server on `:8502`, hosts the git repo
- **gatekeeper** — VPS running nginx + Docker, WireGuard tailnet at `100.64.0.1`, pyrite at `100.64.0.2`

### Production stack on gatekeeper

```
/opt/model-gateway/          ← production git repo + .env
/opt/model-gateway-staging/  ← staging git repo + .env
```

nginx proxies `https://model.perdrizet.org` → `http://127.0.0.1:8503` (production gateway).

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

### On every push to `main`

1. GitHub Actions runs the test suite (`pytest tests/ -v`)
2. If tests pass, SSHs to gatekeeper and deploys to staging at port `8505`
3. Smoke tests `http://127.0.0.1:8505/health`

### Production deploy

Manual trigger only — go to **Actions → Deploy to Production → Run workflow**, type `deploy` to confirm.

The workflow SSHs to gatekeeper, pulls the latest commit into `/opt/model-gateway/`, and runs `docker compose up --build -d`.

### Required GitHub secrets

| Secret | Value |
|---|---|
| `GATEKEEPER_HOST` | gatekeeper's public IP |
| `GATEKEEPER_USER` | SSH username on gatekeeper |
| `GATEKEEPER_SSH_KEY` | Private key (matching public key in gatekeeper's `authorized_keys`) |

Generate a dedicated deploy key:
```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/github_deploy -N ""
# Add ~/.ssh/github_deploy.pub to gatekeeper's authorized_keys
# Add contents of ~/.ssh/github_deploy as the GATEKEEPER_SSH_KEY secret
```

---

## Admin panel

The admin panel is at `/admin?key=<ADMIN_KEY>`.

Access is restricted to two layers:
1. **`ADMIN_KEY`** — must match the `ADMIN_KEY` env var (compared in constant time)
2. **IP CIDR check** — request must come from the tailnet (`100.64.0.0/10`), localhost, or Docker bridge (`172.16.0.0/12`)

From outside the tailnet, `/admin` returns 403 regardless of key.

### Admin panel features

- View all users — email, key prefix, token balance, trial status, 30-day usage, join date
- **Adjust tokens** — add or subtract tokens from any user's paid balance (positive or negative delta)
- **Grant trial** — give a user a new trial allocation (tokens + days)
- **Delete user** — permanently removes the user and all associated records
- Email filter search box for finding users quickly

### Adminer (database GUI)

Adminer runs at port `8504` (production) or `8506` (staging), bound to the tailnet IP (`100.64.0.1`) on gatekeeper — not accessible from the public internet.

Access from a tailnet machine:
```
http://100.64.0.1:8504
Server: db
Username: gateway
Password: (POSTGRES_PASSWORD from .env)
Database: gateway
```

---

## Billing

### Stripe

Set `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` in `.env`. Register a webhook at `https://model.perdrizet.org/stripe/webhook` in the Stripe dashboard with the `checkout.session.completed` event.

### BTCPay Server (Bitcoin)

A separate compose stack (`docker-compose.btcpay.yml`) runs BTCPay Server on the tailnet at `100.64.0.1:23000`. Set `BTCPAY_URL`, `BTCPAY_API_KEY`, `BTCPAY_STORE_ID`, and `BTCPAY_WEBHOOK_SECRET` in `.env` after configuring the store.

---

## Token packs

| Pack | Tokens | Price |
|---|---|---|
| `starter` | 5M | $0.50 |
| `standard` | 25M | $2.00 |
| `pro` | 100M | $6.00 |
