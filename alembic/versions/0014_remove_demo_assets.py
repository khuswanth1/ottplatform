"""remove the sample-video assets and platform rights that the development shortcut attached to opened titles

Revision ID: 0014
Revises: 0013
"""
from alembic import op


revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM media_assets WHERE url LIKE 'https://vjs.zencdn.net/v/oceans.mp4%'")
    op.execute("DELETE FROM title_rights WHERE source = 'platform' AND license_type = 'licensed' AND evidence_url IS NULL")


def downgrade() -> None:
    pass  # the removed rows were placeholders; nothing to restore
