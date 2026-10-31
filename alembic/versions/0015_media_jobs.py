"""add media_jobs (background video processing queue)

Revision ID: 0015
Revises: 0014
"""
from alembic import op
import sqlalchemy as sa

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None

ACTIVE = "status in ('queued','processing')"


def upgrade() -> None:
    op.create_table(
        'media_jobs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('title_id', sa.Uuid(), nullable=False),
        sa.Column('episode_id', sa.Uuid(), nullable=True),
        sa.Column('episode_key', sa.String(length=36), nullable=False, server_default='-'),
        sa.Column('source', sa.String(length=300), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False, server_default='queued'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('locked_by', sa.String(length=64), nullable=True),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('asset_id', sa.Uuid(), nullable=True),
        sa.Column('renditions', sa.JSON(), nullable=True),
        sa.Column('duration_s', sa.Integer(), nullable=True),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status in ('queued','processing','ready','failed')", name='ck_media_jobs_status'),
        sa.ForeignKeyConstraint(['title_id'], ['titles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['asset_id'], ['media_assets.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_media_jobs_title_id', 'media_jobs', ['title_id'])
    op.create_index('ix_media_jobs_queue', 'media_jobs', ['status', 'created_at'])
    op.create_index('uq_media_jobs_one_active', 'media_jobs', ['title_id', 'episode_key'], unique=True,
                    postgresql_where=sa.text(ACTIVE), sqlite_where=sa.text(ACTIVE))


def downgrade() -> None:
    op.drop_index('uq_media_jobs_one_active', table_name='media_jobs')
    op.drop_index('ix_media_jobs_queue', table_name='media_jobs')
    op.drop_index('ix_media_jobs_title_id', table_name='media_jobs')
    op.drop_table('media_jobs')
