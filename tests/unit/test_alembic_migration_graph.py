"""Guard the alembic migration graph against unmerged heads."""

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_migration_graph_has_single_head() -> None:
    """A split graph breaks `alembic upgrade head` on deployed instances.

    The fork carries its own migrations, so upstream syncs that add
    migrations re-split the graph. When this fails, generate a merge
    revision with `uv run alembic merge heads -m "..."`.
    """
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = script.get_heads()
    assert len(heads) == 1, (
        f"Multiple alembic heads {heads}. "
        "Run `uv run alembic merge heads -m '<message>'` and commit the "
        "generated merge revision."
    )
