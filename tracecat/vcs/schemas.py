"""API models for VCS integrations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, SecretStr

from tracecat.vcs.github.manifest import GitHubAppManifest


class GitHubAppInstallRequest(BaseModel):
    """Request to set GitHub App installation ID for workspace."""

    installation_id: int


class GitHubAppCredentialsRequest(BaseModel):
    """Request to register or update GitHub App credentials."""

    app_id: str = Field(..., description="GitHub App ID")
    private_key: SecretStr = Field(
        ..., description="GitHub App private key in PEM format"
    )
    webhook_secret: SecretStr | None = Field(
        None, description="GitHub App webhook secret"
    )
    client_id: str | None = Field(None, description="GitHub App client ID")


class GitHubAppCredentialsStatus(BaseModel):
    """Status of GitHub App credentials."""

    exists: bool
    is_corrupted: bool = False
    app_id: str | None = None
    has_webhook_secret: bool = False
    webhook_secret_preview: str | None = None
    client_id: str | None = None
    created_at: str | None = None


class GitHubAppManifestResponse(BaseModel):
    """GitHub App manifest response."""

    manifest: GitHubAppManifest
    instructions: list[str]


class GitHubAppCredentialsSaveResponse(BaseModel):
    """Response after creating or updating GitHub App credentials."""

    message: str
    action: Literal["created", "updated"]
    app_id: str


class GitLabTokenCredentialsRequest(BaseModel):
    """Request to register or update GitLab token credentials."""

    base_url: str = Field(
        default="https://gitlab.com",
        description="Base URL for GitLab.com or a self-managed GitLab instance.",
    )
    token: SecretStr = Field(
        ...,
        description="GitLab personal/project/group access token with api scope.",
    )


class GitLabTokenCredentialsStatus(BaseModel):
    """Status of GitLab token credentials."""

    exists: bool
    is_corrupted: bool = False
    base_url: str | None = None
    created_at: str | None = None


class GitLabTokenCredentialsSaveResponse(BaseModel):
    """Response after creating or updating GitLab token credentials."""

    message: str
    action: Literal["created", "updated"]
    base_url: str


# Custom (non-EE) GitLab workflow sync schemas


class GitLabCredentialsRequest(BaseModel):
    """Request to register or update GitLab credentials."""

    access_token: SecretStr = Field(
        ..., description="GitLab Group Access Token or Personal Access Token"
    )
    gitlab_url: str = Field(
        default="https://gitlab.com",
        description="GitLab instance URL (for self-hosted instances)",
    )


class GitLabCredentialsStatus(BaseModel):
    """Status of GitLab credentials."""

    exists: bool
    gitlab_url: str | None = None
    created_at: str | None = None


class GitLabTestConnectionRequest(BaseModel):
    """Request to test GitLab repository connection."""

    git_repo_url: str = Field(..., description="GitLab repository URL to test")


class GitLabTestConnectionResponse(BaseModel):
    """Response from GitLab connection test."""

    success: bool
    project_name: str | None = None
    default_branch: str | None = None
    branches: list[str] = Field(default_factory=list)
    branch_count: int = 0
    error: str | None = None


class GitLabWorkspaceConfig(BaseModel):
    """Minimal workspace info with git configuration for GitLab integration.

    Used by GitLab VCS integration to show workspace git settings
    without exposing other workspace configuration.
    """

    id: str = Field(..., description="Workspace ID")
    name: str = Field(..., description="Workspace name")
    git_repo_url: str | None = Field(None, description="Git repository URL")
    git_branch: str | None = Field(None, description="Git branch for workflow sync")
