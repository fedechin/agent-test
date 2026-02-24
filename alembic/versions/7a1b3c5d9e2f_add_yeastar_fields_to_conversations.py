"""Add source and yeastar_session_id to conversations table

Revision ID: 7a1b3c5d9e2f
Revises: 5c3d8f9a2b1e
Create Date: 2026-02-24

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '7a1b3c5d9e2f'
down_revision: Union[str, None] = '5c3d8f9a2b1e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the enum type first (PostgreSQL needs this)
    conversation_source = sa.Enum('twilio', 'yeastar', name='conversationsource')
    conversation_source.create(op.get_bind(), checkfirst=True)

    op.add_column('conversations', sa.Column(
        'source',
        conversation_source,
        nullable=True,
        server_default='twilio'
    ))
    op.add_column('conversations', sa.Column(
        'yeastar_session_id',
        sa.Integer(),
        nullable=True
    ))

    # Set default value for existing rows
    op.execute("UPDATE conversations SET source = 'twilio' WHERE source IS NULL")

    # Make column non-nullable after setting defaults
    op.alter_column('conversations', 'source', nullable=False)


def downgrade() -> None:
    op.drop_column('conversations', 'yeastar_session_id')
    op.drop_column('conversations', 'source')

    # Drop the enum type
    sa.Enum(name='conversationsource').drop(op.get_bind(), checkfirst=True)
