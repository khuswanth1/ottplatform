"""profile maturity level

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('profiles') as b:
        b.add_column(sa.Column('maturity_level', sa.String(length=8), nullable=False, server_default='all'))
        b.create_check_constraint('ck_profiles_maturity', "maturity_level in ('kids','7+','13+','all')")
    op.execute("update profiles set maturity_level = 'kids' where is_kids")
    with op.batch_alter_table('profiles') as b:
        b.alter_column('maturity_level', server_default=None)


def downgrade() -> None:
    with op.batch_alter_table('profiles') as b:
        b.drop_constraint('ck_profiles_maturity', type_='check')
        b.drop_column('maturity_level')
