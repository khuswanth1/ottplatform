"""skip intro / recap / credits markers

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('title_markers',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('title_id', sa.Uuid(), nullable=False),
    sa.Column('episode_id', sa.Uuid(), nullable=True),
    sa.Column('episode_key', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=8), nullable=False),
    sa.Column('start_s', sa.Integer(), nullable=False),
    sa.Column('end_s', sa.Integer(), nullable=False),
    sa.CheckConstraint("kind in ('intro','recap','credits')", name='ck_markers_kind'),
    sa.CheckConstraint('start_s >= 0 and end_s > start_s', name='ck_markers_order'),
    sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['title_id'], ['titles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('title_id', 'episode_key', 'kind', name='uq_marker')
    )
    op.create_index('ix_title_markers_title_id', 'title_markers', ['title_id'])


def downgrade() -> None:
    op.drop_index('ix_title_markers_title_id', table_name='title_markers')
    op.drop_table('title_markers')
