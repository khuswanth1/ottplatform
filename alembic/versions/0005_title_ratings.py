"""per-profile title ratings

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('title_ratings',
    sa.Column('profile_id', sa.Uuid(), nullable=False),
    sa.Column('title_id', sa.Uuid(), nullable=False),
    sa.Column('value', sa.Integer(), nullable=False),
    sa.Column('rated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('value in (-1, 1, 2)', name='ck_title_ratings_value'),
    sa.ForeignKeyConstraint(['profile_id'], ['profiles.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['title_id'], ['titles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('profile_id', 'title_id')
    )
    op.create_index('ix_title_ratings_title_id', 'title_ratings', ['title_id'])


def downgrade() -> None:
    op.drop_index('ix_title_ratings_title_id', table_name='title_ratings')
    op.drop_table('title_ratings')
