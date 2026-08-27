DEFAULT_REGISTRY_ORIGIN = "tracecat_registry"
DEFAULT_REMOTE_REGISTRY_ORIGIN = "remote"
DEFAULT_LOCAL_REGISTRY_ORIGIN = "local"
REGISTRY_GIT_SSH_KEY_SECRET_NAME = "github-ssh-key"
"""Name of the SSH key secret for the registry."""

REGISTRY_GIT_TOKEN_SECRET_NAME = "git-access-token"
"""Name of the org secret holding an HTTPS access token for git+https registries.

Expected keys: `token` (required) and optionally `username` (defaults to
"oauth2", which GitLab accepts for project/group access tokens).
"""


REGISTRY_REPOS_PATH: str = "/registry/repos"
"""Base path for repository-related endpoints"""

REGISTRY_ACTIONS_PATH: str = "/registry/actions"
"""Base path for action-related endpoints"""

PLATFORM_REGISTRY_NAMESPACE: str = "platform"
"""Storage namespace for platform-scoped registry artifacts (S3 prefix segment)."""
