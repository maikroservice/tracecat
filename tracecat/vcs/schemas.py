"""API models for VCS integrations."""

from __future__ import annotations

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
    app_id: str | None = None
    has_webhook_secret: bool = False
    has_client_id: bool = False
    created_at: str | None = None


class GitHubAppManifestResponse(BaseModel):
    """GitHub App manifest response."""

    manifest: GitHubAppManifest
    instructions: list[str]


# GitLab schemas


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
