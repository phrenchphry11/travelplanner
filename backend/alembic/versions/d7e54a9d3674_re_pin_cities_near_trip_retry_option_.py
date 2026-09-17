"""re-pin cities near trip; retry option pins

Revision ID: d7e54a9d3674
Revises: ec17ce26a9a0
Create Date: 2026-09-16 17:03:29.321738

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'd7e54a9d3674'
down_revision: Union[str, Sequence[str], None] = 'ec17ce26a9a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Data only.

    City pins could fall back to a same-named place on another continent
    ('Central France' -> Goiânia, Brazil). Clear cached lookups and city pins
    so trips re-pin with the proximity check, and let unpinned option places
    (rejected by the 40 km guard against a wrong base pin) be tried again.
    """
    op.execute("DELETE FROM geocode_cache")
    op.execute(
        "UPDATE places SET lat = NULL, lng = NULL, precision = 'unknown', geocoded_at = NULL WHERE kind = 'city'"
    )
    op.execute("UPDATE places SET geocoded_at = NULL WHERE kind <> 'city' AND lat IS NULL")


def downgrade() -> None:
    """Nothing to undo: pins are recomputed on the next board load."""
