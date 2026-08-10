from dataclasses import dataclass
from typing import Literal, Protocol

GitUrlScheme = Literal["ssh", "https"]


class GitAuthEnv(Protocol):
    """Environment variables that authenticate git subprocess operations.

    Satisfied by `tracecat.ssh.SshEnv` (ssh-agent based) and
    `tracecat.git.auth.HttpsTokenEnv` (GIT_ASKPASS token based).
    """

    def to_dict(self) -> dict[str, str]: ...


@dataclass(frozen=True)
class GitUrl:
    """Immutable Git URL representation."""

    host: str
    org: str
    repo: str
    user: str = "git"
    ref: str | None = None
    scheme: GitUrlScheme = "ssh"

    def to_url(self) -> str:
        """Convert GitUrl to its pip/uv installable string representation."""
        if self.scheme == "https":
            base = f"git+https://{self.host}/{self.org}/{self.repo}.git"
        else:
            base = f"git+ssh://{self.user}@{self.host}/{self.org}/{self.repo}.git"
        return f"{base}@{self.ref}" if self.ref else base

    @property
    def transport_url(self) -> str:
        """URL understood by the git CLI (git knows git+ssh but not git+https)."""
        if self.scheme == "https":
            return f"https://{self.host}/{self.org}/{self.repo}.git"
        return f"ssh://{self.user}@{self.host}/{self.org}/{self.repo}.git"
