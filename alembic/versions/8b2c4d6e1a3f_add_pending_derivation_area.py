"""Add pending_derivation_area to conversations table

Guarda el área de una derivación que se le ofreció al socio y que todavía no
confirmó. Permite preguntar "¿quiere que lo comunique con un agente?" en vez de
transferir de una, que era lo que cortaba la conversación en cada dato faltante.

Revision ID: 8b2c4d6e1a3f
Revises: 7a1b3c5d9e2f
Create Date: 2026-08-31

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '8b2c4d6e1a3f'
down_revision: Union[str, None] = '7a1b3c5d9e2f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable y sin default: NULL significa "no hay derivación pendiente", que es
    # lo correcto para todas las filas existentes.
    op.add_column('conversations', sa.Column(
        'pending_derivation_area',
        sa.String(length=30),
        nullable=True
    ))


def downgrade() -> None:
    op.drop_column('conversations', 'pending_derivation_area')
