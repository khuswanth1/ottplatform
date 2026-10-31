"""Minimal Razorpay REST client (httpx, no SDK): plans, recurring subscriptions (AutoPay), cancellation and signatures.
Only the owner's own keys are used. The transport is injectable so tests never touch the network."""
from __future__ import annotations

import hashlib
import hmac

import httpx

from .config import get_settings

_transport: httpx.BaseTransport | None = None  # tests set this


class RazorpayError(Exception):
    pass


def enabled() -> bool:
    s = get_settings()
    return bool(s.razorpay_key_id and s.razorpay_key_secret)


def _request(method: str, path: str, json: dict | None = None) -> dict:
    s = get_settings()
    try:
        with httpx.Client(base_url=s.razorpay_api_base, auth=(s.razorpay_key_id, s.razorpay_key_secret), timeout=10.0,
                          transport=_transport) as c:
            r = c.request(method, path, json=json)
    except httpx.HTTPError as e:
        raise RazorpayError(f"Payment provider unreachable: {e.__class__.__name__}") from e
    if r.status_code >= 400:
        try:
            msg = (r.json().get("error") or {}).get("description")
        except ValueError:
            msg = None
        raise RazorpayError(msg or f"Payment provider error ({r.status_code})")
    return r.json()


def create_plan(*, name: str, amount_paise: int, currency: str = "INR") -> dict:
    return _request("POST", "/plans", {"period": "monthly", "interval": 1, "item": {
        "name": name, "amount": amount_paise, "currency": currency.upper()}})


def create_subscription(*, plan_id: str, user_id: str, plan_code: str, total_count: int | None = None) -> dict:
    """A recurring mandate: the customer authorises once in Checkout and Razorpay debits every month."""
    return _request("POST", "/subscriptions", {
        "plan_id": plan_id, "total_count": total_count or get_settings().razorpay_total_count, "customer_notify": 1,
        "notes": {"user_id": user_id, "plan_code": plan_code}})


def create_order(*, amount_paise: int, currency: str, receipt: str, user_id: str, plan_code: str) -> dict:
    """A one-time payment: the Checkout shows every method the account has enabled (UPI, cards, net banking, wallets)."""
    return _request("POST", "/orders", {"amount": amount_paise, "currency": currency.upper(), "receipt": receipt[:40],
                                        "payment_capture": 1, "notes": {"user_id": user_id, "plan_code": plan_code}})


def retrieve_order(order_id: str) -> dict:
    return _request("GET", f"/orders/{order_id}")


def retrieve_subscription(subscription_id: str) -> dict:
    return _request("GET", f"/subscriptions/{subscription_id}")


def cancel_subscription(subscription_id: str, *, at_cycle_end: bool) -> dict:
    return _request("POST", f"/subscriptions/{subscription_id}/cancel", {"cancel_at_cycle_end": 1 if at_cycle_end else 0})


def keep_subscription(subscription_id: str) -> dict:
    """Undo a cancellation that was scheduled for the end of the cycle."""
    return _request("POST", f"/subscriptions/{subscription_id}/cancel_scheduled_changes")


def _hmac(secret: str, msg: bytes) -> str:
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def sign_checkout(payment_id: str, subscription_id: str, secret: str) -> str:
    """What Razorpay Checkout returns as razorpay_signature for a subscription payment (also used by tests)."""
    return _hmac(secret, f"{payment_id}|{subscription_id}".encode())


def verify_checkout_signature(payment_id: str, subscription_id: str, signature: str) -> bool:
    secret = get_settings().razorpay_key_secret
    return bool(secret and signature) and hmac.compare_digest(sign_checkout(payment_id, subscription_id, secret), signature)


def sign_order(order_id: str, payment_id: str, secret: str) -> str:
    """razorpay_signature for a one-time Order payment: HMAC of "order_id|payment_id" (also used by tests)."""
    return _hmac(secret, f"{order_id}|{payment_id}".encode())


def verify_order_signature(order_id: str, payment_id: str, signature: str) -> bool:
    secret = get_settings().razorpay_key_secret
    return bool(secret and signature) and hmac.compare_digest(sign_order(order_id, payment_id, secret), signature)


def sign_webhook(payload: bytes, secret: str) -> str:
    return _hmac(secret, payload)


def verify_webhook_signature(payload: bytes, signature: str | None, secret: str) -> bool:
    return bool(secret and signature) and hmac.compare_digest(sign_webhook(payload, secret), signature)
