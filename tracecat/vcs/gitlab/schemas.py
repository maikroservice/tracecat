"""GitLab data models for workflow store."""

from __future__ import annotations

from pydantic import BaseModel, Field, SecretStr


class GitLabCredentials(BaseModel):
    """GitLab credentials for organization-level storage.

    Uses Group Access Token for group-scoped authentication.
    Required token scopes: api or (read_api + read_repository + write_repository)
    """

    access_token: SecretStr = Field(
        ..., description="GitLab Group Access Token or Personal Access Token"
    )
    gitlab_url: str = Field(
        default="https://gitlab.com",
        description="GitLab instance URL (for self-hosted instances)",
    )


class GitLabConfig(BaseModel):
    """GitLab configuration status."""

    gitlab_url: str = Field(
        default="https://gitlab.com",
        description="GitLab instance URL",
    )
    has_access_token: bool = Field(
        default=False,
        description="Whether access token is configured",
    )
