"""Admin bootstrap:  python -m app.cli create-admin you@example.com   (prompts for the password)
Pricing:          python -m app.cli set-plan-price standard US USD 1299 price_xxx   (cents; Stripe price id optional)
                  python -m app.cli list-plans
Billing setup:    python -m app.cli billing-check   (reads your Stripe test setup; changes nothing)"""
import getpass
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from .db import SessionLocal
from .models import Profile, User
from .security import hash_password, validate_password_strength


def create_admin(email: str, password: str) -> None:
    if err := validate_password_strength(password):
        sys.exit(err)
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == email.lower()))
        if u:
            u.role, u.email_verified_at = "admin", u.email_verified_at or datetime.now(timezone.utc)
        else:
            u = User(email=email.lower(), password_hash=hash_password(password), role="admin",
                     email_verified_at=datetime.now(timezone.utc))
            db.add(u)
            db.flush()
            db.add(Profile(user_id=u.id, name="Admin"))
        db.commit()
    print(f"Admin ready: {email}")


def import_archive(query: str, limit: int = 20) -> None:
    """Bulk-import openly-licensed Internet Archive films as DRAFTS with UNVERIFIED rights (admin must verify)."""
    from .models import TitleRight
    from .providers.archive import ArchiveProvider, classify_license
    from .services.catalog import upsert_titles

    arch = ArchiveProvider()
    items = arch.search_candidates(query, 1, open_only=True)[:limit]
    with SessionLocal() as db:
        for nt in items:
            (t, _), = upsert_titles(db, [nt])
            if db.scalar(select(TitleRight.id).where(TitleRight.title_id == t.id)):
                continue
            lic = nt.extra_ids.get("license_url") or ""
            t.source, t.status = "admin", "draft"
            db.add(TitleRight(title_id=t.id, license_type=classify_license(lic) or "unknown", status="unverified",
                              territories=["*"], evidence_url=lic or None, source="archive",
                              notes="Declared on archive.org by the uploader; verify the real rights holder."))
            print("draft:", nt.name, nt.external_id)
        db.commit()


def set_plan_price(plan: str, country: str, currency: str, cents: int, stripe_price_id: str | None) -> None:
    from .models import Plan, PlanPrice
    country = country.upper() if country != "*" else "*"
    with SessionLocal() as db:
        p = db.scalar(select(Plan).where(Plan.code == plan))
        if not p or p.code == "free":
            sys.exit("plan must be one of: ads, standard, premium")
        row = db.get(PlanPrice, (p.id, country)) or PlanPrice(plan_id=p.id, country=country, currency="", amount_cents=0)
        row.currency, row.amount_cents = currency.upper(), cents
        if stripe_price_id:
            row.stripe_price_id = stripe_price_id
        db.add(row)
        db.commit()
    print(f"{plan} {country}: {currency.upper()} {cents / 100:.2f}" + (f" -> {stripe_price_id}" if stripe_price_id else ""))


def list_plans() -> None:
    from .models import Plan, PlanPrice
    with SessionLocal() as db:
        for p in db.scalars(select(Plan).order_by(Plan.sort)):
            prices = db.scalars(select(PlanPrice).where(PlanPrice.plan_id == p.id)).all()
            shown = ", ".join(f"{x.country} {x.currency} {x.amount_cents / 100:.2f} {x.stripe_price_id or '(no stripe price)'}" for x in prices)
            print(p.code, "|", p.name, "|", shown or "no prices")


def razorpay_sync_plans() -> int:
    """Creates a monthly Razorpay plan for every INR price that has none yet and stores its id. Run after set-plan-price."""
    from . import razorpay_client as rz
    from .models import Plan, PlanPrice
    if not rz.enabled():
        sys.exit("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are empty.")
    made = 0
    with SessionLocal() as db:
        rows = db.execute(select(Plan, PlanPrice).join(PlanPrice, PlanPrice.plan_id == Plan.id)
                          .where(Plan.code != "free", PlanPrice.currency == "INR", PlanPrice.razorpay_plan_id.is_(None))).all()
        if not rows:
            print("No INR prices without a Razorpay plan. Add one first: python -m app.cli set-plan-price standard IN INR 19900")
        for plan, pp in rows:
            created = rz.create_plan(name=f"CineVerse {plan.name}", amount_paise=pp.amount_cents)
            pp.razorpay_plan_id = created["id"]
            db.commit()
            made += 1
            print(f"{plan.code} {pp.country} INR {pp.amount_cents / 100:.2f} -> {created['id']}")
    return made


def billing_check(allow_live: bool = False) -> int:
    """Read-only checklist for a Stripe setup. Returns the number of problems found."""
    from . import stripe_client as stripe
    from .config import get_settings
    from .models import Plan, PlanPrice
    s = get_settings()
    problems = 0

    def say(ok: bool, msg: str) -> None:
        nonlocal problems
        problems += 0 if ok else 1
        print(("ok      " if ok else "PROBLEM ") + msg)

    if not stripe.enabled():
        print("STRIPE_SECRET_KEY is empty: paid plans are switched off. Set a test key (sk_test_...) in backend/.env first.")
        return 1
    live = s.stripe_secret_key.startswith(("sk_live", "rk_live"))
    say(not live or allow_live, "key mode: " + ("LIVE (refusing without --allow-live)" if live else "test"))
    say(s.stripe_webhook_secret.startswith("whsec_"), "STRIPE_WEBHOOK_SECRET " + ("looks right" if s.stripe_webhook_secret.startswith("whsec_")
        else "is empty or does not start with whsec_ (`stripe listen` prints the one to use)"))
    say(s.frontend_url.startswith("http"), f"FRONTEND_URL = {s.frontend_url} (checkout returns here)")
    with SessionLocal() as db:
        rows = db.execute(select(Plan, PlanPrice).join(PlanPrice, PlanPrice.plan_id == Plan.id).where(Plan.code != "free")
                          .order_by(Plan.sort, PlanPrice.country)).all()
        if not rows:
            say(False, "no plan prices yet: python -m app.cli set-plan-price standard '*' USD 1299 price_xxx")
        for plan, pp in rows:
            label = f"{plan.code} {pp.country} {pp.currency} {pp.amount_cents / 100:.2f}"
            if not pp.stripe_price_id:
                say(False, f"{label}: no Stripe price id attached, so it cannot be bought")
                continue
            try:
                sp = stripe.retrieve_price(pp.stripe_price_id)
            except stripe.StripeError as e:
                say(False, f"{label}: Stripe could not read {pp.stripe_price_id}: {e}")
                continue
            issues = []
            if not sp.get("active"):
                issues.append("price is archived in Stripe")
            if not sp.get("recurring") or (sp["recurring"] or {}).get("interval") != "month":
                issues.append("not a monthly recurring price (the app says '/ month')")
            if sp.get("unit_amount") != pp.amount_cents:
                issues.append(f"Stripe amount is {sp.get('unit_amount')} cents, the app shows {pp.amount_cents}")
            if (sp.get("currency") or "").upper() != pp.currency.upper():
                issues.append(f"Stripe currency is {(sp.get('currency') or '?').upper()}, the app shows {pp.currency}")
            say(not issues, f"{label} -> {pp.stripe_price_id}" + ("" if not issues else ": " + "; ".join(issues)))
    print(f"{problems} problem(s)." if problems else "Everything this check can see looks fine.")
    return problems


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "create-admin":
        create_admin(sys.argv[2], getpass.getpass("Password: "))
    elif len(sys.argv) >= 3 and sys.argv[1] == "import-archive":
        import_archive(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 20)
    elif len(sys.argv) in (6, 7) and sys.argv[1] == "set-plan-price":
        set_plan_price(sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]), sys.argv[6] if len(sys.argv) > 6 else None)
    elif sys.argv[1:] == ["razorpay-sync-plans"]:
        razorpay_sync_plans()
    elif sys.argv[1:] == ["list-plans"]:
        list_plans()
    elif sys.argv[1:2] == ["billing-check"]:
        sys.exit(1 if billing_check("--allow-live" in sys.argv[2:]) else 0)
    else:
        sys.exit("usage: python -m app.cli create-admin EMAIL | import-archive QUERY [LIMIT] | "
                 "set-plan-price PLAN COUNTRY CURRENCY CENTS [STRIPE_PRICE_ID] | razorpay-sync-plans | list-plans | billing-check")
