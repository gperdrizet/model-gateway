"""
FastAPI gateway app.

Validates per-user API keys, checks token balance, proxies requests to
llama-server, records usage (token counts only — no content).
"""

import json
import logging
import os
import secrets
import time
from ipaddress import ip_address, ip_network
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

from fastapi import FastAPI, Form, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .db import (
    User, UsageEvent, TrialTokens,
    engine, init_db,
    generate_api_key, verify_api_key, get_user_by_key_prefix,
    total_available_tokens, deduct_tokens,
)
from .btcpay import create_invoice, verify_webhook as btcpay_verify_webhook
from .checkout import PACK_CATALOG, create_checkout_session, verify_webhook
from .db import TokenPurchase
from .email import send_trial_key_email, TRIAL_TOKENS, TRIAL_EXPIRY_DAYS
from .proxy import proxy_request, proxy_stream

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Simple in-memory rate limit for registration: max 3 attempts per IP per hour
_reg_attempts: dict[str, list[float]] = defaultdict(list)
REG_LIMIT = 3
REG_WINDOW = 3600


def _check_reg_rate_limit(ip: str) -> bool:
    """Returns True if allowed, False if rate limited."""
    now = time.time()
    attempts = [t for t in _reg_attempts[ip] if now - t < REG_WINDOW]
    _reg_attempts[ip] = attempts
    if len(attempts) >= REG_LIMIT:
        return False
    _reg_attempts[ip].append(now)
    return True


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)

async_session = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

async def authenticate(request: Request) -> tuple[User, AsyncSession] | tuple[None, None]:
    """
    Validate Bearer token. Returns (user, session) or (None, None).
    The session is left open for the caller to commit and close.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None, None

    raw_key = auth.removeprefix("Bearer ").strip()
    if not raw_key.startswith("sk-") or len(raw_key) < 12:
        return None, None

    prefix = raw_key[:12]
    session = async_session()
    user = await get_user_by_key_prefix(session, prefix)

    if user is None or not verify_api_key(raw_key, user.api_key_hash):
        await session.close()
        return None, None

    return user, session


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html", {
        "trial_tokens_fmt": _fmt_tokens(TRIAL_TOKENS),
        "trial_expiry_days": TRIAL_EXPIRY_DAYS,
        "error": None,
    })


@app.post("/register", response_class=HTMLResponse)
async def register_submit(request: Request, email: str = Form(...)):
    client_ip = request.client.host if request.client else "unknown"

    if not _check_reg_rate_limit(client_ip):
        return templates.TemplateResponse(request, "register.html", {
            "trial_tokens_fmt": _fmt_tokens(TRIAL_TOKENS),
            "trial_expiry_days": TRIAL_EXPIRY_DAYS,
            "error": "Too many attempts. Please try again later.",
        }, status_code=429)

    email = email.strip().lower()

    async with async_session() as session:
        # Check if already registered — respond identically to prevent enumeration
        existing = (await session.execute(
            select(User).where(User.email == email)
        )).scalar_one_or_none()

        if existing is None:
            raw_key, key_hash, prefix = generate_api_key()
            user = User(
                email=email,
                api_key_hash=key_hash,
                api_key_prefix=prefix,
                balance_tokens=0,
            )
            session.add(user)
            await session.flush()  # get user.id

            expires_at = datetime.now(timezone.utc) + timedelta(days=TRIAL_EXPIRY_DAYS)
            trial = TrialTokens(
                user_id=user.id,
                tokens_granted=TRIAL_TOKENS,
                remaining_tokens=TRIAL_TOKENS,
                expires_at=expires_at,
            )
            session.add(trial)
            await session.commit()

            # Send email outside the transaction — failure here is non-fatal
            try:
                await send_trial_key_email(email, raw_key)
            except Exception:
                # Log but don't surface SMTP errors to the user
                import logging
                logging.getLogger(__name__).exception("Failed to send trial key email to %s", email)

    # Same response regardless of whether email was new or already existed
    return templates.TemplateResponse(request, "registered.html", {
        "email": email,
        "trial_tokens_fmt": _fmt_tokens(TRIAL_TOKENS),
        "trial_expiry_days": TRIAL_EXPIRY_DAYS,
    })


# ---------------------------------------------------------------------------
# Dashboard — authenticated via ?key=sk-...
# ---------------------------------------------------------------------------

PACKS = [
    {"id": "5m",   "label": "5M",   "tokens": 5_000_000,   "price": "0.50", "cpp": "0.10"},
    {"id": "25m",  "label": "25M",  "tokens": 25_000_000,  "price": "2.00", "cpp": "0.08"},
    {"id": "100m", "label": "100M", "tokens": 100_000_000, "price": "6.00", "cpp": "0.06"},
]


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, key: str = Query(...)):
    if not key.startswith("sk-") or len(key) < 12:
        return RedirectResponse("/register")

    prefix = key[:12]
    async with async_session() as session:
        user = await get_user_by_key_prefix(session, prefix)
        if user is None or not verify_api_key(key, user.api_key_hash):
            return RedirectResponse("/register")

        now = datetime.now(timezone.utc)
        thirty_days_ago = now - timedelta(days=30)

        # Active trial info
        trial_result = await session.execute(
            text(
                "SELECT remaining_tokens, expires_at FROM trial_tokens "
                "WHERE user_id = :uid AND expires_at > :now AND remaining_tokens > 0 "
                "ORDER BY expires_at ASC LIMIT 1"
            ),
            {"uid": user.id, "now": now},
        )
        trial_row = trial_result.mappings().first()
        trial_remaining = trial_row["remaining_tokens"] if trial_row else 0
        trial_expires_raw = trial_row["expires_at"] if trial_row else None
        # SQLite returns datetimes as strings; PostgreSQL returns datetime objects
        if isinstance(trial_expires_raw, str):
            trial_expires_dt = datetime.fromisoformat(trial_expires_raw).replace(tzinfo=timezone.utc)
        else:
            trial_expires_dt = trial_expires_raw
        trial_days_left = (trial_expires_dt - now).days if trial_expires_dt else 0

        # Total available balance
        total_balance = user.balance_tokens + trial_remaining

        # 30-day usage summary
        summary = await session.execute(
            text(
                "SELECT COALESCE(SUM(input_tokens),0) AS inp, "
                "COALESCE(SUM(output_tokens),0) AS out, "
                "COUNT(*) AS reqs "
                "FROM usage_events "
                "WHERE user_id = :uid AND timestamp >= :since"
            ),
            {"uid": user.id, "since": thirty_days_ago},
        )
        s = summary.mappings().first()
        used_in, used_out, req_count = s["inp"], s["out"], s["reqs"]

        # Daily usage for bar chart
        # DATE() is portable across SQLite and PostgreSQL when timestamps are UTC
        from app.db import _is_sqlite as _sqlite
        _date_expr = "DATE(timestamp)" if _sqlite else "DATE(timestamp AT TIME ZONE 'UTC')"
        daily = await session.execute(
            text(
                f"SELECT {_date_expr} AS day, "
                "SUM(input_tokens) AS inp, SUM(output_tokens) AS out "
                "FROM usage_events "
                "WHERE user_id = :uid AND timestamp >= :since "
                "GROUP BY day ORDER BY day DESC LIMIT 30"
            ),
            {"uid": user.id, "since": thirty_days_ago},
        )
        daily_rows = daily.mappings().all()
        max_total = max((r["inp"] + r["out"] for r in daily_rows), default=1)
        daily_usage = [
            {
                "date": str(r["day"])[5:],  # MM-DD
                "input_pct": round(r["inp"] / max_total * 100),
                "output_pct": round(r["out"] / max_total * 100),
                "total_fmt": _fmt_tokens(r["inp"] + r["out"]),
            }
            for r in daily_rows
        ]

    return templates.TemplateResponse(request, "dashboard.html", {
        "email": user.email,
        "api_key": key,                    # full key — used in buy form hidden fields
        "api_key_prefix": user.api_key_prefix,
        "total_balance": total_balance,
        "total_balance_fmt": _fmt_tokens(total_balance),
        "trial_remaining": trial_remaining,
        "trial_remaining_fmt": _fmt_tokens(trial_remaining),
        "trial_expires": trial_expires_dt.strftime("%b %d") if trial_expires_dt else "",
        "trial_days_left": trial_days_left,
        "used_30d_fmt": _fmt_tokens(used_in + used_out),
        "used_30d_input_fmt": _fmt_tokens(used_in),
        "used_30d_output_fmt": _fmt_tokens(used_out),
        "request_count_30d": req_count,
        "daily_usage": daily_usage,
        "packs": PACKS,
        "payment_success": request.query_params.get("payment") == "success",
    })


# ---------------------------------------------------------------------------
# Stripe billing
# ---------------------------------------------------------------------------

@app.get("/checkout")
async def checkout_redirect(
    request: Request,
    pack: str,
    key: str = Query(...),
    method: str = Query(default="stripe"),   # "stripe" | "btcpay"
):
    """Validate the user's API key, create a payment session, redirect."""
    if not key.startswith("sk-") or len(key) < 12:
        return RedirectResponse("/register")

    prefix = key[:12]
    async with async_session() as session:
        user = await get_user_by_key_prefix(session, prefix)
        if user is None or not verify_api_key(key, user.api_key_hash):
            return RedirectResponse("/register")
        user_id = user.id
        user_email = user.email

    base_url = os.environ.get("BASE_URL", "http://localhost:8503")

    try:
        if method == "btcpay":
            invoice_id, checkout_url = await create_invoice(
                pack_id=pack,
                user_id=user_id,
                user_email=user_email,
                full_key=key,
                base_url=base_url,
            )
        else:
            checkout_url = await create_checkout_session(
                pack_id=pack,
                user_id=user_id,
                user_email=user_email,
                full_key=key,
                base_url=base_url,
            )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except RuntimeError as exc:
        log.error("Payment provider not configured (%s): %s", method, exc)
        return JSONResponse(status_code=503, content={"error": "Payment system not configured."})
    except Exception:
        log.exception("Checkout creation failed (method=%s)", method)
        return JSONResponse(status_code=502, content={"error": "Could not create checkout session."})

    return RedirectResponse(checkout_url, status_code=303)


@app.post("/btcpay/webhook")
async def btcpay_webhook(request: Request):
    """Receive and verify BTCPay webhooks; credit balance on InvoiceSettled."""
    payload = await request.body()
    sig = request.headers.get("BTCPay-Sig", "")

    try:
        event = btcpay_verify_webhook(payload, sig)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "invalid signature"})
    except RuntimeError as exc:
        log.error("BTCPay webhook: %s", exc)
        return JSONResponse(status_code=503, content={"error": "not configured"})

    if event.get("type") == "InvoiceSettled":
        await _fulfill_btcpay(event)

    return {"ok": True}


async def _fulfill_btcpay(event: dict) -> None:
    """Credit user balance for a settled BTCPay invoice. Idempotent via payment_ref unique constraint."""
    try:
        metadata = event["metadata"]
        invoice_id = event["invoiceId"]
        user_id = int(metadata["user_id"])
        tokens = int(metadata["tokens"])
        pack_id = metadata.get("pack_id", "")
        # Derive amount_cents from pack catalog
        from .btcpay import PACK_CATALOG as _BTC_PACKS
        amount_cents = int(float(_BTC_PACKS.get(pack_id, {}).get("price_usd", "0")) * 100)
    except (KeyError, ValueError):
        log.error("BTCPay webhook: malformed event: %s", event.get("invoiceId"))
        return

    async with async_session() as db:
        user = await db.get(User, user_id)
        if user is None:
            log.error("BTCPay webhook: user_id %s not found", user_id)
            return

        existing = (await db.execute(
            select(TokenPurchase).where(TokenPurchase.payment_ref == invoice_id)
        )).scalar_one_or_none()
        if existing is not None:
            return

        user.balance_tokens += tokens
        db.add(TokenPurchase(
            user_id=user_id,
            payment_method="btcpay",
            payment_ref=invoice_id,
            tokens_added=tokens,
            amount_cents=amount_cents,
        ))
        await db.commit()
        log.info("BTCPay: credited %s tokens to user %s (invoice %s)", tokens, user_id, invoice_id)



@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    """Receive and verify Stripe events; credit token balance on successful payment."""
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        import stripe as _stripe
        event = verify_webhook(payload, sig)
    except _stripe.SignatureVerificationError:
        return JSONResponse(status_code=400, content={"error": "invalid signature"})
    except RuntimeError as exc:
        log.error("Stripe webhook: %s", exc)
        return JSONResponse(status_code=503, content={"error": "not configured"})

    if event["type"] == "checkout.session.completed":
        obj = event["data"]["object"]
        if obj.get("payment_status") == "paid":
            await _fulfill_checkout(obj)

    return {"ok": True}


async def _fulfill_checkout(session_obj: dict) -> None:
    """Credit the user's balance. Idempotent via unique constraint on session id."""
    try:
        user_id = int(session_obj["metadata"]["user_id"])
        tokens = int(session_obj["metadata"]["tokens"])
        amount_cents = int(session_obj.get("amount_total") or 0)
        session_id = session_obj["id"]  # cs_xxx — used as idempotency key
    except (KeyError, ValueError):
        log.error("Stripe webhook: malformed session object: %s", session_obj.get("id"))
        return

    async with async_session() as db:
        user = await db.get(User, user_id)
        if user is None:
            log.error("Stripe webhook: user_id %s not found", user_id)
            return

        # Idempotency — skip if this session was already fulfilled
        existing = (await db.execute(
            select(TokenPurchase).where(TokenPurchase.payment_ref == session_id)
        )).scalar_one_or_none()
        if existing is not None:
            return

        user.balance_tokens += tokens
        db.add(TokenPurchase(
            user_id=user_id,
            payment_method="stripe",
            payment_ref=session_id,
            tokens_added=tokens,
            amount_cents=amount_cents,
        ))
        await db.commit()
        log.info("Credited %s tokens to user %s (session %s)", tokens, user_id, session_id)


# ---------------------------------------------------------------------------
# Inference proxy — all /v1/* routes
# ---------------------------------------------------------------------------

@app.api_route("/v1/{path:path}", methods=["GET", "POST", "DELETE", "OPTIONS"])
async def proxy(request: Request, path: str):
    user, session = await authenticate(request)
    if user is None:
        return JSONResponse(
            status_code=401,
            content={"error": {"message": "Invalid or missing API key.", "type": "auth_error"}},
        )

    async with session:
        available = await total_available_tokens(session, user)
        if available <= 0:
            return JSONResponse(
                status_code=402,
                content={
                    "error": {
                        "message": "Insufficient token balance. Purchase more tokens at "
                                   f"{os.environ.get('BASE_URL', '')}/buy",
                        "type": "insufficient_quota",
                    }
                },
            )

        body: dict | None = None
        if request.method == "POST":
            try:
                body = await request.json()
            except Exception:
                return JSONResponse(status_code=400, content={"error": {"message": "Invalid JSON body."}})

        is_stream = isinstance(body, dict) and body.get("stream", False)
        forward_path = f"/{path}"
        method = request.method
        headers = dict(request.headers)

        if is_stream:
            return await _handle_stream(session, user, method, forward_path, headers, body)
        else:
            return await _handle_standard(session, user, method, forward_path, headers, body)


async def _handle_standard(
    session: AsyncSession,
    user: User,
    method: str,
    path: str,
    headers: dict,
    body: dict | None,
) -> Response:
    response, input_tokens, output_tokens = await proxy_request(method, path, headers, body)

    await _record_usage(session, user, input_tokens, output_tokens, body)

    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.headers.get("content-type"),
    )


async def _handle_stream(
    session: AsyncSession,
    user: User,
    method: str,
    path: str,
    headers: dict,
    body: dict,
) -> StreamingResponse:
    final_input = 0
    final_output = 0

    async def generate():
        nonlocal final_input, final_output
        async for chunk, in_tok, out_tok in proxy_stream(method, path, headers, body):
            if in_tok or out_tok:
                final_input, final_output = in_tok, out_tok
            if chunk:
                yield chunk

        # After stream ends, record usage
        await _record_usage(session, user, final_input, final_output, body)
        await session.close()

    return StreamingResponse(generate(), media_type="text/event-stream")


async def _record_usage(
    session: AsyncSession,
    user: User,
    input_tokens: int,
    output_tokens: int,
    body: dict | None,
) -> None:
    """Write usage event and deduct tokens. No content is stored."""
    total = input_tokens + output_tokens
    if total <= 0:
        return

    model = (body or {}).get("model", "")

    event = UsageEvent(
        user_id=user.id,
        timestamp=datetime.now(timezone.utc),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
    )
    session.add(event)
    await deduct_tokens(session, user, total)
    await session.commit()


# ---------------------------------------------------------------------------
# Admin panel — protected by ADMIN_KEY env var, localhost-only in production
# ---------------------------------------------------------------------------

def _admin_key() -> str:
    return os.environ.get("ADMIN_KEY", "")


# CIDRs allowed to reach /admin — tailnet + localhost + Docker bridge.
# Override via ADMIN_ALLOWED_CIDRS env var (comma-separated) if needed.
_DEFAULT_ADMIN_CIDRS = ["100.64.0.0/10", "127.0.0.1/32", "::1/128", "172.16.0.0/12"]

def _admin_allowed_cidrs() -> list:
    raw = os.environ.get("ADMIN_ALLOWED_CIDRS", "")
    if raw:
        return [c.strip() for c in raw.split(",") if c.strip()]
    return _DEFAULT_ADMIN_CIDRS


def _check_admin_ip(request: Request) -> bool:
    """Return True if the request IP is within an allowed CIDR."""
    client_ip = request.client.host if request.client else ""
    try:
        addr = ip_address(client_ip)
    except ValueError:
        return False
    return any(addr in ip_network(cidr, strict=False) for cidr in _admin_allowed_cidrs())


def _check_admin(key: str) -> bool:
    expected = _admin_key()
    if not expected:
        return False
    return secrets.compare_digest(key.encode(), expected.encode())


@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request, key: str = Query(...)):
    if not _check_admin_ip(request) or not _check_admin(key):
        return JSONResponse(status_code=403, content={"error": "forbidden"})

    flash = request.query_params.get("flash")
    flash_type = request.query_params.get("ft", "ok")
    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)

    async with async_session() as session:
        # All users
        users_rows = (await session.execute(select(User).order_by(User.created_at.desc()))).scalars().all()

        # Active trial counts per user
        trial_result = await session.execute(
            text(
                "SELECT user_id, SUM(remaining_tokens) AS rem, MIN(expires_at) AS exp "
                "FROM trial_tokens WHERE expires_at > :now AND remaining_tokens > 0 "
                "GROUP BY user_id"
            ),
            {"now": now},
        )
        trial_map = {r["user_id"]: r for r in trial_result.mappings().all()}

        # 30-day usage per user
        usage_result = await session.execute(
            text(
                "SELECT user_id, "
                "COALESCE(SUM(input_tokens+output_tokens),0) AS total "
                "FROM usage_events WHERE timestamp >= :since GROUP BY user_id"
            ),
            {"since": thirty_days_ago},
        )
        usage_map = {r["user_id"]: r["total"] for r in usage_result.mappings().all()}

        # Global stats
        active_trials = len(trial_map)
        total_paid = sum(u.balance_tokens for u in users_rows)
        requests_30d_r = await session.execute(
            text("SELECT COUNT(*) FROM usage_events WHERE timestamp >= :since"),
            {"since": thirty_days_ago},
        )
        requests_30d = requests_30d_r.scalar()
        tokens_30d_r = await session.execute(
            text("SELECT COALESCE(SUM(input_tokens+output_tokens),0) FROM usage_events WHERE timestamp >= :since"),
            {"since": thirty_days_ago},
        )
        tokens_30d = tokens_30d_r.scalar()

        user_list = []
        for u in users_rows:
            tr = trial_map.get(u.id)
            user_list.append({
                "id": u.id,
                "email": u.email,
                "prefix": u.api_key_prefix,
                "balance": u.balance_tokens,
                "balance_fmt": _fmt_tokens(u.balance_tokens),
                "trial_remaining": tr["rem"] if tr else 0,
                "trial_remaining_fmt": _fmt_tokens(tr["rem"]) if tr else "0",
                "trial_expires": tr["exp"].strftime("%b %d") if tr else "",
                "used_30d_fmt": _fmt_tokens(usage_map.get(u.id, 0)),
                "joined": u.created_at.strftime("%Y-%m-%d"),
            })

    return templates.TemplateResponse(request, "admin.html", {
        "admin_key": key,
        "user_count": len(users_rows),
        "active_trials": active_trials,
        "total_paid_fmt": _fmt_tokens(total_paid),
        "requests_30d": requests_30d,
        "tokens_30d_fmt": _fmt_tokens(tokens_30d),
        "users": user_list,
        "flash": flash,
        "flash_type": flash_type,
    })


@app.post("/admin/adjust")
async def admin_adjust(
    request: Request,
    key: str = Form(...),
    user_id: int = Form(...),
    delta: int = Form(...),
):
    if not _check_admin_ip(request) or not _check_admin(key):
        return JSONResponse(status_code=403, content={"error": "forbidden"})

    async with async_session() as session:
        user = await session.get(User, user_id)
        if user is None:
            return RedirectResponse(f"/admin?key={key}&flash=User+not+found&ft=err", status_code=303)
        user.balance_tokens = max(0, user.balance_tokens + delta)
        await session.commit()
        action = f"+{delta:,}" if delta >= 0 else f"{delta:,}"

    return RedirectResponse(
        f"/admin?key={key}&flash={action}+tokens+applied+to+{user.email}&ft=ok",
        status_code=303,
    )


@app.post("/admin/delete")
async def admin_delete(
    request: Request,
    key: str = Form(...),
    user_id: int = Form(...),
):
    if not _check_admin_ip(request) or not _check_admin(key):
        return JSONResponse(status_code=403, content={"error": "forbidden"})

    async with async_session() as session:
        user = await session.get(User, user_id)
        if user is None:
            return RedirectResponse(f"/admin?key={key}&flash=User+not+found&ft=err", status_code=303)
        email = user.email
        await session.execute(text("DELETE FROM trial_tokens WHERE user_id = :uid"), {"uid": user_id})
        await session.execute(text("DELETE FROM usage_events WHERE user_id = :uid"), {"uid": user_id})
        await session.execute(text("DELETE FROM token_purchases WHERE user_id = :uid"), {"uid": user_id})
        await session.delete(user)
        await session.commit()

    return RedirectResponse(
        f"/admin?key={key}&flash=Deleted+{email}&ft=ok",
        status_code=303,
    )


@app.post("/admin/grant")
async def admin_grant(
    request: Request,
    key: str = Form(...),
    email: str = Form(...),
    tokens: int = Form(...),
    days: int = Form(...),
):
    if not _check_admin_ip(request) or not _check_admin(key):
        return JSONResponse(status_code=403, content={"error": "forbidden"})

    email = email.strip().lower()
    async with async_session() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            return RedirectResponse(
                f"/admin?key={key}&flash=No+user+found+with+email+{email}&ft=err",
                status_code=303,
            )
        expires_at = datetime.now(timezone.utc) + timedelta(days=days)
        session.add(TrialTokens(
            user_id=user.id,
            tokens_granted=tokens,
            remaining_tokens=tokens,
            expires_at=expires_at,
        ))
        await session.commit()

    return RedirectResponse(
        f"/admin?key={key}&flash=Granted+{tokens:,}+tokens+to+{email}&ft=ok",
        status_code=303,
    )
