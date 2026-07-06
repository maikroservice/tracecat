"""merge fork and upstream heads

Revision ID: 9f2c4b7d81aa
Revises: 1c268fa6eff5, 11d479597e08
Create Date: 2026-07-06 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9f2c4b7d81aa"
down_revision: str | Sequence[str] | None = ("1c268fa6eff5", "11d479597e08")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Align fork's GitLab secret type with upstream's snake_case convention
    # (mirrors 3431033d29fd which renamed upstream's own kebab-case types).
    for table in ("secret", "organization_secret", "platform_secret"):
        op.execute(
            f"UPDATE {table} SET type = 'gitlab_token' WHERE type = 'gitlab-token'"  # noqa: S608
        )


def downgrade() -> None:
    for table in ("secret", "organization_secret", "platform_secret"):
        op.execute(
            f"UPDATE {table} SET type = 'gitlab-token' WHERE type = 'gitlab_token'"  # noqa: S608
        )
