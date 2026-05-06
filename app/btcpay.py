"""
BTCPay Server Greenfield API client.

create_invoice  — creates a hosted BTCPay invoice and returns the checkout URL
verify_webhook  — validates the BTCPay-Sig header on incoming webhooks

BTCPay Server setup (run once on gatekeeper):
  1. docker compose -f docker-compose.btcpay.yml up -d
  2. Open http://100.64.0.1:23000, create account + store
  3. Store Settings → Webhooks → Add:
       URL: https://model.perdrizet.org/btcpay/webhook
       Events: InvoiceSettled
       Copy the secret → BTCPAY_WEBHOOK_SECRET in .env
  4. Store Settings → Access Tokens → Create:
       Copy token → BTCPAY_API_KEY in .env
  5. Store Settings → General → copy Store ID → BTCPAY_STORE_ID in .env
"""

import asyncio
import hashlib
import hmac
import json
import os

import httpx

_CLIENT: httpx.AsyncClient | None = None


def _client() -> httpx.AsyncClient:
    global _CLIENT
    if _CLIENT is None:
        base = os.environ.get("BTCPAY_URL", "").rstrip("/")
        key = os.environ.get("BTCPAY_API_KEY", "")
        if not base or not key or base == "http://placeholder":
            raise RuntimeError("BTCPay not configured")
        _CLIENT = httpx.AsyncClient(
            base_url=base,
            headers={"Authorization": f"token {key}", "Content-Type": "application/json"},
            timeout=httpx.Timeout(30.0),
        )
    return _CLIENT


PACK_CATALOG: dict[str, dict] = {
    "5m":   {"tokens": 5_000_000,   "price_usd": "0.50", "label": "5M tokens"},
    "25m":  {"tokens": 25_000_000,  "price_usd": "2.00", "label": "25M tokens"},
    "100m": {"tokens": 100_000_000, "price_usd": "6.00", "label": "100M tokens"},
}


async def create_invoice(
    pack_id: str,
    user_id: int,
    user_email: str,
    full_key: str,
    base_url: str,
) -> tuple[str, str]:
    """
    Create a BTCPay invoice for the given pack.
    Returns (invoice_id, checkout_url).
    """
    pack = PACK_CATALOG.get(pack_id)
    if pack is None:
        raise ValueError(f"Unknown pack id: {pack_id!r}")

    store_id = os.environ.get("BTCPAY_STORE_ID", "")
    if not store_id:
        raise RuntimeError("BTCPAY_STORE_ID not configured")

    payload = {
        "amount": pack["price_usd"],
        "currency": "USD",
        "metadata": {
            "user_id": str(user_id),
            "pack_id": pack_id,
            "tokens": str(pack["tokens"]),
            "buyerEmail": user_email,
        },
        "checkout": {
            "redirectURL": f"{base_url}/dashboard?key={full_key}&payment=success",
            "redirectAutomatically": True,
        },
    }

    client = _client()
    resp = await client.post(f"/api/v1/stores/{store_id}/invoices", content=json.dumps(payload))
    resp.raise_for_status()
    data = resp.json()
    return data["id"], data["checkoutLink"]


def verify_webhook(payload: bytes, sig_header: str) -> dict:
    """
    Validate BTCPay-Sig header (HMAC-SHA256) and return the parsed event dict.
    Raises ValueError on invalid signature.

    BTCPay sends:  BTCPay-Sig: sha256=<hex>
    """
    secret = os.environ.get("BTCPAY_WEBHOOK_SECRET", "")
    if not secret or secret == "placeholder":
        raise RuntimeError("BTCPAY_WEBHOOK_SECRET not configured")

    try:
        algo, received_hex = sig_header.split("=", 1)
    except ValueError:
        raise ValueError("Malformed BTCPay-Sig header")

    if algo != "sha256":
        raise ValueError(f"Unexpected sig algorithm: {algo!r}")

    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hex):
        raise ValueError("BTCPay webhook signature mismatch")

    return json.loads(payload)
