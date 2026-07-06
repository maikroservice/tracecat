"""merge fork and upstream heads

Revision ID: 9f2c4b7d81aa
Revises: 1c268fa6eff5, 11d479597e08
Create Date: 2026-07-06 12:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "9f2c4b7d81aa"
down_revision: str | Sequence[str] | None = ("1c268fa6eff5", "11d479597e08")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
