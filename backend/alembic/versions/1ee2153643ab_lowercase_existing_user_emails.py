"""lowercase existing user emails

Revision ID: 1ee2153643ab
Revises: 4061bdf2d054
Create Date: 2026-09-16 19:36:47.724540

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '1ee2153643ab'
down_revision: Union[str, Sequence[str], None] = '4061bdf2d054'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Data only.

    app.auth now normalizes a signed-in user's email to lowercase before
    storing it, so an invite (also lowercased) always matches. Backfill
    existing rows so an account created before this change isn't stranded.
    """
    op.execute("UPDATE users SET email = lower(email)")


def downgrade() -> None:
    """Nothing to undo: the original casing wasn't meaningful."""
