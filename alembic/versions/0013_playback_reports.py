"""add playback_reports table

Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa


revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'playback_reports',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('title_id', sa.Uuid(), nullable=False),
        sa.Column('episode_id', sa.Uuid(), nullable=True),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('position_seconds', sa.Integer(), nullable=True),
        sa.Column('user_agent', sa.String(length=200), nullable=True),
        sa.Column('status', sa.String(length=10), nullable=False, server_default='open'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status in ('open', 'resolved')", name='ck_playback_reports_status'),
        sa.CheckConstraint("kind in ('no_video', 'no_sound', 'buffering', 'out_of_sync', 'subtitles', 'other')",
                           name='ck_playback_reports_kind'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['title_id'], ['titles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('playback_reports', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_playback_reports_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_playback_reports_title_id'), ['title_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_playback_reports_status'), ['status'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('playback_reports', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_playback_reports_status'))
        batch_op.drop_index(batch_op.f('ix_playback_reports_title_id'))
        batch_op.drop_index(batch_op.f('ix_playback_reports_user_id'))
    op.drop_table('playback_reports')
