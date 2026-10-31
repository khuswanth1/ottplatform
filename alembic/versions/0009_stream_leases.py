"""stream limits: heartbeat time on playback sessions

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('playback_sessions') as b:
        b.add_column(sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True))
    op.execute("update playback_sessions set last_seen_at = issued_at")
    with op.batch_alter_table('playback_sessions') as b:
        b.alter_column('last_seen_at', existing_type=sa.DateTime(timezone=True), nullable=False)
    op.create_index('ix_playback_sessions_live', 'playback_sessions', ['user_id', 'last_seen_at'])


def downgrade() -> None:
    op.drop_index('ix_playback_sessions_live', table_name='playback_sessions')
    with op.batch_alter_table('playback_sessions') as b:
        b.drop_column('last_seen_at')
