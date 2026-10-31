"""plans, prices, subscriptions, stripe events

Revision ID: 0004
Revises: 0003
"""
import uuid

from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None

LIVE = "status in ('trialing','active','past_due')"


def upgrade() -> None:
    plans = op.create_table('plans',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=40), nullable=False),
    sa.Column('has_ads', sa.Boolean(), nullable=False),
    sa.Column('max_streams', sa.Integer(), nullable=False),
    sa.Column('max_height', sa.Integer(), nullable=False),
    sa.Column('entitlement', sa.String(length=16), nullable=False),
    sa.Column('sort', sa.Integer(), nullable=False),
    sa.CheckConstraint("code in ('free','ads','standard','premium')", name='ck_plans_code'),
    sa.CheckConstraint("entitlement in ('registered','premium')", name='ck_plans_entitlement'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code'))
    op.bulk_insert(plans, [
        {"id": uuid.uuid4(), "code": c, "name": n, "has_ads": a, "max_streams": st, "max_height": h, "entitlement": e, "sort": i}
        for i, (c, n, a, st, h, e) in enumerate([
            ("free", "Free", False, 1, 720, "registered"),
            ("ads", "With ads", True, 1, 1080, "registered"),
            ("standard", "Standard", False, 2, 1080, "premium"),
            ("premium", "Premium", False, 4, 2160, "premium")])])
    op.create_table('plan_prices',
    sa.Column('plan_id', sa.Uuid(), nullable=False),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('stripe_price_id', sa.String(length=64), nullable=True),
    sa.CheckConstraint('amount_cents >= 0', name='ck_plan_prices_amount'),
    sa.ForeignKeyConstraint(['plan_id'], ['plans.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('plan_id', 'country'))
    op.create_index('ix_plan_prices_stripe_price_id', 'plan_prices', ['stripe_price_id'])
    op.create_table('subscriptions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('plan_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('stripe_customer_id', sa.String(length=64), nullable=False),
    sa.Column('stripe_subscription_id', sa.String(length=64), nullable=True),
    sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False),
    sa.Column('event_ts', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status in ('trialing','active','past_due','cancelled','expired')", name='ck_subscriptions_status'),
    sa.ForeignKeyConstraint(['plan_id'], ['plans.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('stripe_subscription_id'))
    op.create_index('ix_subscriptions_user_id', 'subscriptions', ['user_id'])
    op.create_index('ix_subscriptions_plan_id', 'subscriptions', ['plan_id'])
    op.create_index('uq_subscriptions_one_live', 'subscriptions', ['user_id'], unique=True,
                    postgresql_where=sa.text(LIVE), sqlite_where=sa.text(LIVE))
    op.create_table('stripe_events',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('type', sa.String(length=64), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'))


def downgrade() -> None:
    op.drop_table('stripe_events')
    op.drop_index('uq_subscriptions_one_live', table_name='subscriptions')
    op.drop_index('ix_subscriptions_plan_id', table_name='subscriptions')
    op.drop_index('ix_subscriptions_user_id', table_name='subscriptions')
    op.drop_table('subscriptions')
    op.drop_index('ix_plan_prices_stripe_price_id', table_name='plan_prices')
    op.drop_table('plan_prices')
    op.drop_table('plans')
