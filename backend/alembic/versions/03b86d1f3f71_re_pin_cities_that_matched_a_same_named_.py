"""re-pin cities that matched a same-named county

Revision ID: 03b86d1f3f71
Revises: bfa2489e3f9c
Create Date: 2026-09-23 20:26:03.257436

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '03b86d1f3f71'
down_revision: Union[str, Sequence[str], None] = 'bfa2489e3f9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Data only.

    A city search could pin a city to its same-named county ("Monterey" ->
    Monterey County's centre, 63 km away), and then every option in that city
    failed the 40 km check and got no pin. City lookups now use new cache keys
    that prefer the town, so clearing city pins re-pins them on the next board
    load. Unpinned options retry too; their own lookups are still cached.
    """
    op.execute(
        "UPDATE places SET lat = NULL, lng = NULL, precision = 'unknown', geocoded_at = NULL WHERE kind = 'city'"
    )
    op.execute("UPDATE places SET geocoded_at = NULL WHERE kind <> 'city' AND lat IS NULL")


def downgrade() -> None:
    """Nothing to undo: pins are recomputed on demand."""
