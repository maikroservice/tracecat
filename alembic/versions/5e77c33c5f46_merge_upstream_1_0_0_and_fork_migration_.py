"""merge upstream 1.0.0 and fork migration heads

Revision ID: 5e77c33c5f46
Revises: 9f2c4b7d81aa, a7c3e9f1b2d4
Create Date: 2026-09-17 11:31:53.924500

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "5e77c33c5f46"
down_revision: str | Sequence[str] | None = ("9f2c4b7d81aa", "a7c3e9f1b2d4")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
