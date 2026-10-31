"""profile PIN lock

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('profiles') as b:
        b.add_column(sa.Column('pin_hash', sa.String(length=255), nullable=True))
        b.add_column(sa.Column('pin_failed', sa.Integer(), nullable=False, server_default='0'))
        b.add_column(sa.Column('pin_locked_until', sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table('sessions') as b:
        b.add_column(sa.Column('unlocked_profile_id', sa.Uuid(), nullable=True))
    with op.batch_alter_table('profiles') as b:
        b.alter_column('pin_failed', server_default=None)


def downgrade() -> None:
    with op.batch_alter_table('sessions') as b:
        b.drop_column('unlocked_profile_id')
    with op.batch_alter_table('profiles') as b:
        b.drop_column('pin_locked_until')
        b.drop_column('pin_failed')
        b.drop_column('pin_hash')
