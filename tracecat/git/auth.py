"""HTTPS token authentication for git operations.

Counterpart to the ssh-agent context in `tracecat.ssh` for `git+https://`
registry origins. Credentials are injected via a GIT_ASKPASS helper script so
tokens never appear in URLs (which are logged and persisted) or in process
argv. The env-var based approach also covers `uv pip install git+https://...`,
which shells out to the git CLI and inherits the environment.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from tracecat.auth.types import Role
from tracecat.git.types import GitUrl
from tracecat.logger import logger
from tracecat.secrets.service import SecretsService

_ASKPASS_SCRIPT = """#!/bin/sh
case "$1" in
  [Uu]sername*) printf '%s\\n' "$GIT_ASKPASS_USERNAME" ;;
  *) printf '%s\\n' "$GIT_ASKPASS_TOKEN" ;;
esac
"""


@dataclass(frozen=True)
class HttpsTokenEnv:
    """Git environment for HTTPS remotes, optionally carrying token credentials."""

    askpass_path: str | None = None
    username: str | None = None
    token: str | None = None

    def to_dict(self) -> dict[str, str]:
        # Never fall back to interactive prompts; fail fast instead of hanging.
        env = {"GIT_TERMINAL_PROMPT": "0"}
        if self.askpass_path and self.token is not None:
            env |= {
                "GIT_ASKPASS": self.askpass_path,
                "GIT_ASKPASS_USERNAME": self.username or "oauth2",
                "GIT_ASKPASS_TOKEN": self.token,
            }
        return env


@asynccontextmanager
async def https_token_context(
    *,
    git_url: GitUrl,
    session: AsyncSession,
    role: Role | None = None,
) -> AsyncIterator[HttpsTokenEnv]:
    """Yield a git environment for an HTTPS remote.

    If the org has a `git-access-token` secret, credentials are served through
    a temporary GIT_ASKPASS script; otherwise the environment only disables
    terminal prompts, which is sufficient for public repositories.
    """
    sec_svc = SecretsService(session, role=role)
    git_token = await sec_svc.get_registry_git_token()
    if git_token is None:
        logger.debug(
            "No git access token configured; using anonymous HTTPS",
            host=git_url.host,
        )
        yield HttpsTokenEnv()
        return

    with tempfile.TemporaryDirectory(prefix="tracecat_git_askpass_") as askpass_dir:
        askpass_path = os.path.join(askpass_dir, "askpass.sh")
        with open(askpass_path, "w", encoding="utf-8") as f:
            f.write(_ASKPASS_SCRIPT)
        os.chmod(askpass_path, 0o700)
        logger.debug("Using git access token for HTTPS remote", host=git_url.host)
        yield HttpsTokenEnv(
            askpass_path=askpass_path,
            username=git_token.username,
            token=git_token.token.get_secret_value(),
        )
