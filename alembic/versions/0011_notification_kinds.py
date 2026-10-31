"""notifications for new episodes and newly playable list titles: episode id and a wider dedupe key

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Two steps on purpose: SQLite rebuilds the table once per batch with the final schema, so adding a NOT NULL column and
    # dropping its default in the same batch would fail on any table that already has rows.
    with op.batch_alter_table('notifications') as b:
        b.add_column(sa.Column('episode_id', sa.Uuid(), nullable=True))
        b.add_column(sa.Column('episode_key', sa.String(length=36), nullable=False, server_default='-'))
        b.create_foreign_key('fk_notifications_episode', 'episodes', ['episode_id'], ['id'], ondelete='CASCADE')
    with op.batch_alter_table('notifications') as b:
        b.drop_constraint('uq_notification_dedupe', type_='unique')
        b.create_unique_constraint('uq_notification_dedupe', ['profile_id', 'kind', 'title_id', 'episode_key'])
        b.alter_column('episode_key', existing_type=sa.String(length=36), existing_nullable=False, server_default=None)


def downgrade() -> None:
    op.execute("delete from notifications where kind <> 'reminder_released'")
    with op.batch_alter_table('notifications') as b:
        b.drop_constraint('uq_notification_dedupe', type_='unique')
        b.create_unique_constraint('uq_notification_dedupe', ['profile_id', 'kind', 'title_id'])
    with op.batch_alter_table('notifications') as b:
        b.drop_constraint('fk_notifications_episode', type_='foreignkey')
        b.drop_column('episode_key')
        b.drop_column('episode_id')
