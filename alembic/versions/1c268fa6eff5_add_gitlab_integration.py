"""add gitlab integration

Revision ID: 1c268fa6eff5
Revises: de71cf55f6c9
Create Date: 2026-02-05 22:04:30.231280

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "1c268fa6eff5"
down_revision: str | None = "de71cf55f6c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
