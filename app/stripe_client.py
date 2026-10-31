"""Minimal Stripe REST client (httpx, no SDK): Checkout sessions, billing-portal sessions and webhook signatures.
Only the owner's own keys are used. The transport is injectable so tests never touch the network."""
from __future__ import annotations

import hashlib
import hmac
import time

import httpx

from .config import get_settings

_transport: httpx.BaseTransport | None = None  # tests set this


class StripeError(Exception):
    pass


def enabled() -> bool:
    return bool(get_settings().stripe_secret_key)


def _request(method: str, path: str, data: dict | None = None, params: dict | None = None) -> dict:
    s = get_settings()
    try:
        with httpx.Client(base_url=s.stripe_api_base, auth=(s.stripe_secret_key, ""), timeout=10.0,
                          transport=_transport) as c:
            r = c.request(method, path, data=data, params=params)
    except httpx.HTTPError as e:
        raise StripeError(f"Payment provider unreachable: {e.__class__.__name__}") from e
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", {}).get("message")
        except ValueError:
            msg = None
        raise StripeError(msg or f"Payment provider error ({r.status_code})")
    return r.json()


def _post(path: str, data: dict) -> dict:
    return _request("POST", path, data=data)


def create_checkout_session(*, price_id: str, user_id: str, email: str, plan_code: str, success_url: str,
                            cancel_url: str, customer_id: str | None = None) -> dict:
    data = {
        "mode": "subscription", "line_items[0][price]": price_id, "line_items[0][quantity]": "1",
        "success_url": success_url, "cancel_url": cancel_url, "client_reference_id": user_id,
        "metadata[user_id]": user_id, "metadata[plan_code]": plan_code,
        "subscription_data[metadata][user_id]": user_id, "subscription_data[metadata][plan_code]": plan_code,
    }
    data["customer" if customer_id else "customer_email"] = customer_id or email
    return _post("/checkout/sessions", data)


def create_portal_session(*, customer_id: str, return_url: str) -> dict:
    return _post("/billing_portal/sessions", {"customer": customer_id, "return_url": return_url})


def retrieve_price(price_id: str) -> dict:
    return _request("GET", f"/prices/{price_id}")


def retrieve_subscription(subscription_id: str) -> dict:
    return _request("GET", f"/subscriptions/{subscription_id}")


def switch_subscription_price(*, subscription_id: str, price_id: str, plan_code: str) -> dict:
    """Moves the subscription to another price now; Stripe prorates (credits the unused time, charges the new price).
    The local plan changes only when the resulting customer.subscription.updated webhook arrives."""
    item = ((retrieve_subscription(subscription_id).get("items") or {}).get("data") or [{}])[0].get("id")
    if not item:
        raise StripeError("The subscription has no items to change.")
    return _post(f"/subscriptions/{subscription_id}", {
        "items[0][id]": item, "items[0][price]": price_id, "proration_behavior": "create_prorations",
        "cancel_at_period_end": "false", "metadata[plan_code]": plan_code})


def set_cancel_at_period_end(*, subscription_id: str, cancel: bool) -> dict:
    return _post(f"/subscriptions/{subscription_id}", {"cancel_at_period_end": "true" if cancel else "false"})


def cancel_subscription_now(subscription_id: str) -> dict:
    """Ends the subscription immediately (no further charges). Used when an account is deleted."""
    return _request("DELETE", f"/subscriptions/{subscription_id}")


def list_invoices(*, customer_id: str, limit: int = 12) -> list[dict]:
    return _request("GET", "/invoices", params={"customer": customer_id, "limit": limit}).get("data", [])


def sign(payload: bytes, secret: str, ts: int | None = None) -> str:
    """Stripe-Signature header value (also used by tests)."""
    ts = int(ts if ts is not None else time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def verify_signature(payload: bytes, header: str | None, secret: str, tolerance_s: int, now: float | None = None) -> bool:
    if not secret or not header:
        return False
    parts = [p.split("=", 1) for p in header.split(",") if "=" in p]
    ts = next((v for k, v in parts if k == "t"), "")
    sigs = [v for k, v in parts if k == "v1"]
    if not ts.isdigit() or not sigs:
        return False
    if abs((now if now is not None else time.time()) - int(ts)) > tolerance_s:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in sigs)
