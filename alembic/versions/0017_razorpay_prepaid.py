"""razorpay one-time (prepaid) purchases: payment id on subscriptions

Revision ID: 0017
Revises: 0016
"""
from alembic import op
import sqlalchemy as sa

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('subscriptions') as b:
        b.add_column(sa.Column('razorpay_payment_id', sa.String(length=64), nullable=True))
        b.create_unique_constraint('uq_subscriptions_razorpay_payment_id', ['razorpay_payment_id'])


def downgrade() -> None:
    with op.batch_alter_table('subscriptions') as b:
        b.drop_constraint('uq_subscriptions_razorpay_payment_id', type_='unique')
        b.drop_column('razorpay_payment_id')
