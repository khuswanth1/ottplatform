"""add title_crew table

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa


revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'title_crew',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('title_id', sa.Uuid(), nullable=False),
        sa.Column('person_name', sa.String(length=200), nullable=False),
        sa.Column('job', sa.String(length=200), nullable=True),
        sa.Column('department', sa.String(length=100), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('external_person_id', sa.String(length=32), nullable=True),
        sa.Column('profile_path', sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(['title_id'], ['titles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('title_crew', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_title_crew_person_name'), ['person_name'], unique=False)
        batch_op.create_index(batch_op.f('ix_title_crew_title_id'), ['title_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('title_crew', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_title_crew_title_id'))
        batch_op.drop_index(batch_op.f('ix_title_crew_person_name'))
    op.drop_table('title_crew')
