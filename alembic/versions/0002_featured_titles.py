"""featured titles (home billboard)

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('featured_titles',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('title_id', sa.Uuid(), nullable=False),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['title_id'], ['titles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('title_id', 'country', name='uq_featured_title_country')
    )
    op.create_index('ix_featured_country_position', 'featured_titles', ['country', 'position'])


def downgrade() -> None:
    op.drop_index('ix_featured_country_position', table_name='featured_titles')
    op.drop_table('featured_titles')
