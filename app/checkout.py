"""
Stripe checkout helpers.

create_checkout_session  — create a hosted Stripe Checkout Session
verify_webhook           — validate Stripe-Signature header and parse event
"""

import asyncio
import os
from typing import Any

import stripe

# Stripe keys are read lazily so the module can be imported even when keys are
# not yet set (e.g. during testing).  The routes guard against placeholder values.
def _stripe_client() -> stripe.StripeClient:
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key or key == "sk_test_placeholder":
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")
    return stripe.StripeClient(key)


PACK_CATALOG: dict[str, dict[str, Any]] = {
    "5m":   {"tokens": 5_000_000,   "price_cents": 50,   "label": "5M tokens"},
    "25m":  {"tokens": 25_000_000,  "price_cents": 200,  "label": "25M tokens"},
    "100m": {"tokens": 100_000_000, "price_cents": 600,  "label": "100M tokens"},
}


async def create_checkout_session(
    pack_id: str,
    user_id: int,
    user_email: str,
    full_key: str,
    base_url: str,
) -> str:
    """
    Create a Stripe Checkout Session for the given pack.
    Returns the hosted checkout URL to redirect the user to.
    """
    pack = PACK_CATALOG.get(pack_id)
    if pack is None:
        raise ValueError(f"Unknown pack id: {pack_id!r}")

    client = _stripe_client()

    def _create() -> str:
        session = client.checkout.sessions.create(
            params={
                "mode": "payment",
                "customer_email": user_email,
                "line_items": [
                    {
                        "price_data": {
                            "currency": "usd",
                            "product_data": {
                                "name": f"{pack['label']} — API tokens",
                            },
                            "unit_amount": pack["price_cents"],
                        },
                        "quantity": 1,
                    }
                ],
                "metadata": {
                    "user_id": str(user_id),
                    "pack_id": pack_id,
                    "tokens": str(pack["tokens"]),
                },
                "success_url": f"{base_url}/dashboard?key={full_key}&payment=success",
                "cancel_url": f"{base_url}/dashboard?key={full_key}",
            }
        )
        return session.url

    return await asyncio.to_thread(_create)


def verify_webhook(payload: bytes, sig_header: str) -> stripe.Event:
    """
    Validate the Stripe-Signature header and return the parsed Event.
    Raises stripe.SignatureVerificationError on failure.
    """
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not secret or secret == "whsec_placeholder":
        raise RuntimeError("STRIPE_WEBHOOK_SECRET is not configured")
    return stripe.Webhook.construct_event(payload, sig_header, secret)
