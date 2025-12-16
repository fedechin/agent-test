"""Add media fields to messages table

Revision ID: 5c3d8f9a2b1e
Revises: 4bf8c2a7d7c6
Create Date: 2025-12-16 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5c3d8f9a2b1e'
down_revision: Union[str, Sequence[str], None] = '4bf8c2a7d7c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add media support to messages table."""
    # Add media columns
    op.add_column('messages', sa.Column('num_media', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('messages', sa.Column('media_urls', sa.Text(), nullable=True))
    op.add_column('messages', sa.Column('media_content_types', sa.Text(), nullable=True))

    # Make message_text nullable (for media-only messages)
    op.alter_column('messages', 'message_text',
                    existing_type=sa.Text(),
                    nullable=True)


def downgrade() -> None:
    """Downgrade schema - remove media support."""
    # Restore message_text to non-nullable
    op.alter_column('messages', 'message_text',
                    existing_type=sa.Text(),
                    nullable=False)

    # Drop media columns
    op.drop_column('messages', 'media_content_types')
    op.drop_column('messages', 'media_urls')
    op.drop_column('messages', 'num_media')
