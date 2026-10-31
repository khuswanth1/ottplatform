"""razorpay AutoPay: plan ids on prices, provider + razorpay id on subscriptions

Revision ID: 0016
Revises: 0015
"""
from alembic import op
import sqlalchemy as sa

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('plan_prices') as b:
        b.add_column(sa.Column('razorpay_plan_id', sa.String(length=64), nullable=True))
        b.create_index('ix_plan_prices_razorpay_plan_id', ['razorpay_plan_id'])
    with op.batch_alter_table('subscriptions') as b:
        b.add_column(sa.Column('provider', sa.String(length=10), nullable=False, server_default='stripe'))
        b.add_column(sa.Column('razorpay_subscription_id', sa.String(length=64), nullable=True))
        b.alter_column('stripe_customer_id', existing_type=sa.String(length=64), nullable=True)
        b.create_unique_constraint('uq_subscriptions_razorpay_subscription_id', ['razorpay_subscription_id'])
        b.create_check_constraint('ck_subscriptions_provider', "provider in ('stripe','razorpay')")


def downgrade() -> None:
    # Razorpay rows have no Stripe customer, so the column cannot return to NOT NULL while they exist. Their subscription
    # rows are removed (accounts, profiles and history are untouched; Razorpay keeps its own payment records).
    op.execute("DELETE FROM subscriptions WHERE provider = 'razorpay'")
    with op.batch_alter_table('subscriptions') as b:
        b.drop_constraint('ck_subscriptions_provider', type_='check')
        b.drop_constraint('uq_subscriptions_razorpay_subscription_id', type_='unique')
        b.alter_column('stripe_customer_id', existing_type=sa.String(length=64), nullable=False)
        b.drop_column('razorpay_subscription_id')
        b.drop_column('provider')
    with op.batch_alter_table('plan_prices') as b:
        b.drop_index('ix_plan_prices_razorpay_plan_id')
        b.drop_column('razorpay_plan_id')
