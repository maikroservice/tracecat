from dataclasses import dataclass
from enum import StrEnum


class GitScheme(StrEnum):
    """Git URL scheme types."""

    SSH = "ssh"
    HTTPS = "https"


@dataclass(frozen=True)
class GitUrl:
    """Immutable Git URL representation."""

    host: str
    org: str
    repo: str
    ref: str | None = None
    scheme: GitScheme = GitScheme.SSH

    def to_url(self) -> str:
        """Convert GitUrl to string representation."""
        if self.scheme == GitScheme.HTTPS:
            base = f"https://{self.host}/{self.org}/{self.repo}.git"
        else:
            base = f"git+ssh://git@{self.host}/{self.org}/{self.repo}.git"
        return f"{base}@{self.ref}" if self.ref else base
