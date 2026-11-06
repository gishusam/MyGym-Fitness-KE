"""Issue independent, revocable links for assigned workouts.

Revision ID: 0007_member_workout_links
Revises: 0006_member_onboarding
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0007_member_workout_links'
down_revision: str | None = '0006_member_onboarding'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('member_workout_links',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('assignment_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workout_assignments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_member_workout_links_assignment', 'member_workout_links', ['assignment_id'])


def downgrade() -> None:
    op.drop_index('ix_member_workout_links_assignment', table_name='member_workout_links')
    op.drop_table('member_workout_links')
