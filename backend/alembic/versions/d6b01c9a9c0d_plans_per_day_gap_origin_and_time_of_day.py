"""plans per day: gap origin and time of day

Revision ID: d6b01c9a9c0d
Revises: d7e54a9d3674
Create Date: 2026-09-16 17:10:41.118339

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'd6b01c9a9c0d'
down_revision: Union[str, Sequence[str], None] = 'd7e54a9d3674'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add time of day to activities and requests, and mark each gap's origin.

    Every existing gap was made at confirm, so it's a starter. Chosen
    activities stored their best time ("morning", ...) in start_time; move it.
    """
    with op.batch_alter_table('activities', schema=None) as batch_op:
        batch_op.add_column(sa.Column('time_of_day', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''))

    with op.batch_alter_table('gaps', schema=None) as batch_op:
        batch_op.add_column(sa.Column('origin', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default='starter'))
        batch_op.add_column(sa.Column('time_of_day', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''))

    op.execute(
        "UPDATE activities SET time_of_day = start_time, start_time = '' "
        "WHERE start_time IN ('morning', 'afternoon', 'evening')"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE activities SET start_time = time_of_day "
        "WHERE start_time = '' AND time_of_day IN ('morning', 'afternoon', 'evening')"
    )
    with op.batch_alter_table('gaps', schema=None) as batch_op:
        batch_op.drop_column('time_of_day')
        batch_op.drop_column('origin')

    with op.batch_alter_table('activities', schema=None) as batch_op:
        batch_op.drop_column('time_of_day')
