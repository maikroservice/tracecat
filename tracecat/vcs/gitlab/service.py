"""GitLab service for workflow store integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import gitlab
from gitlab.exceptions import GitlabAuthenticationError, GitlabError
from pydantic import SecretStr

from tracecat.auth.types import AccessLevel
from tracecat.authz.controls import require_access_level
from tracecat.exceptions import TracecatException
from tracecat.secrets.enums import SecretType
from tracecat.secrets.schemas import SecretCreate, SecretKeyValue, SecretUpdate
from tracecat.secrets.service import SecretsService
from tracecat.service import BaseService
from tracecat.vcs.gitlab.schemas import GitLabConfig, GitLabCredentials

if TYPE_CHECKING:
    from tracecat.git.types import GitUrl


class GitLabError(TracecatException):
    """GitLab operation error."""


class GitLabService(BaseService):
    """GitLab service for workflow store integration (organization-level)."""

    service_name = "gitlab"

    CREDENTIAL_SECRET_NAME = "gitlab-credentials"

    @require_access_level(AccessLevel.ADMIN)
    async def register_credentials(
        self,
        access_token: SecretStr,
        gitlab_url: str = "https://gitlab.com",
    ) -> GitLabConfig:
        """Register GitLab credentials for the organization.

        Args:
            access_token: GitLab Group Access Token or Personal Access Token
            gitlab_url: GitLab instance URL (default: https://gitlab.com)

        Returns:
            GitLab configuration

        Raises:
            GitLabError: If credentials already exist or validation fails
        """
        # Validate credentials using the Pydantic model
        credentials = GitLabCredentials(
            access_token=access_token,
            gitlab_url=gitlab_url,
        )

        # Prepare secret keys for storage
        secret_keys = [
            SecretKeyValue(key="access_token", value=credentials.access_token),
            SecretKeyValue(key="gitlab_url", value=SecretStr(credentials.gitlab_url)),
        ]

        # Store credentials as organization secret
        secrets_service = SecretsService(session=self.session, role=self.role)
        secret_create = SecretCreate(
            name=self.CREDENTIAL_SECRET_NAME,
            type=SecretType.GITLAB_TOKEN,
            description="GitLab credentials for workflow synchronization",
            keys=secret_keys,
            tags={"purpose": "gitlab-vcs", "provider": "gitlab"},
        )

        await secrets_service.create_org_secret(secret_create)

        config = GitLabConfig(
            gitlab_url=gitlab_url,
            has_access_token=True,
        )

        self.logger.info(
            "Registered GitLab credentials as organization secret",
            gitlab_url=gitlab_url,
        )

        return config

    @require_access_level(AccessLevel.ADMIN)
    async def update_gitlab_credentials(
        self,
        access_token: SecretStr | None = None,
        gitlab_url: str | None = None,
    ) -> GitLabConfig:
        """Update existing GitLab credentials.

        Args:
            access_token: New GitLab access token (optional)
            gitlab_url: New GitLab instance URL (optional)

        Returns:
            Updated GitLab configuration

        Raises:
            GitLabError: If no credentials exist or update fails
        """
        # Get existing credentials
        try:
            existing_credentials = await self.get_gitlab_credentials()
        except GitLabError as e:
            raise GitLabError(
                "No existing GitLab credentials found. Use register_credentials() first."
            ) from e

        # Use existing values if new ones aren't provided
        updated_credentials = GitLabCredentials(
            access_token=access_token
            if access_token is not None
            else existing_credentials.access_token,
            gitlab_url=gitlab_url
            if gitlab_url is not None
            else existing_credentials.gitlab_url,
        )

        # Prepare secret keys for storage
        secret_keys = [
            SecretKeyValue(key="access_token", value=updated_credentials.access_token),
            SecretKeyValue(
                key="gitlab_url", value=SecretStr(updated_credentials.gitlab_url)
            ),
        ]

        # Update the organization secret
        secrets_service = SecretsService(session=self.session, role=self.role)
        secret = await secrets_service.get_org_secret_by_name(
            self.CREDENTIAL_SECRET_NAME
        )

        secret_update = SecretUpdate(keys=secret_keys)
        await secrets_service.update_org_secret(secret, secret_update)

        config = GitLabConfig(
            gitlab_url=updated_credentials.gitlab_url,
            has_access_token=True,
        )

        self.logger.info(
            "Updated GitLab credentials",
            gitlab_url=updated_credentials.gitlab_url,
        )

        return config

    @require_access_level(AccessLevel.ADMIN)
    async def save_gitlab_credentials(
        self,
        access_token: SecretStr,
        gitlab_url: str = "https://gitlab.com",
    ) -> tuple[GitLabConfig, bool]:
        """Save GitLab credentials (create if new, update if exists).

        Args:
            access_token: GitLab Group Access Token or Personal Access Token
            gitlab_url: GitLab instance URL (default: https://gitlab.com)

        Returns:
            Tuple of (GitLabConfig, was_created: bool)
            was_created is True if credentials were newly created, False if updated

        Raises:
            GitLabError: If operation fails
        """
        try:
            # Try to get existing credentials to determine if this is an update
            await self.get_gitlab_credentials()

            # Update existing credentials
            config = await self.update_gitlab_credentials(
                access_token=access_token,
                gitlab_url=gitlab_url,
            )

            self.logger.info(
                "Updated existing GitLab credentials",
                gitlab_url=gitlab_url,
            )

            return config, False  # was_created = False (updated)

        except GitLabError as e:
            if "Failed to retrieve GitLab credentials" in str(e):
                # No existing credentials, create new ones
                config = await self.register_credentials(
                    access_token=access_token,
                    gitlab_url=gitlab_url,
                )

                self.logger.info(
                    "Created new GitLab credentials",
                    gitlab_url=gitlab_url,
                )

                return config, True  # was_created = True (new)
            else:
                # Re-raise other GitLabErrors
                raise

    @require_access_level(AccessLevel.ADMIN)
    async def delete_gitlab_credentials(self) -> None:
        """Delete GitLab credentials from the organization.

        Raises:
            GitLabError: If credentials don't exist or deletion fails
        """
        try:
            secrets_service = SecretsService(session=self.session, role=self.role)
            secret = await secrets_service.get_org_secret_by_name(
                self.CREDENTIAL_SECRET_NAME
            )
            await secrets_service.delete_org_secret(secret)

            self.logger.info("Deleted GitLab credentials")

        except Exception as e:
            self.logger.error("Failed to delete GitLab credentials", error=str(e))
            raise GitLabError(f"Failed to delete GitLab credentials: {e}") from e

    async def get_gitlab_credentials_status(self) -> dict[str, Any]:
        """Get the status of GitLab credentials.

        Returns:
            Dictionary with credentials status information
        """
        try:
            credentials = await self.get_gitlab_credentials()

            # Get the secret to find when it was created
            secrets_service = SecretsService(session=self.session, role=self.role)
            secret = await secrets_service.get_org_secret_by_name(
                self.CREDENTIAL_SECRET_NAME
            )

            return {
                "exists": True,
                "gitlab_url": credentials.gitlab_url,
                "created_at": secret.created_at.isoformat()
                if secret.created_at
                else None,
            }
        except GitLabError:
            return {
                "exists": False,
                "gitlab_url": None,
                "created_at": None,
            }

    async def get_gitlab_credentials(self) -> GitLabCredentials:
        """Retrieve GitLab credentials from organization secret.

        Returns:
            GitLab credentials

        Raises:
            GitLabError: If credentials are not found or invalid
        """
        try:
            secrets_service = SecretsService(session=self.session, role=self.role)
            secret = await secrets_service.get_org_secret_by_name(
                self.CREDENTIAL_SECRET_NAME
            )

            # Decrypt the secret keys
            decrypted_keys = secrets_service.decrypt_keys(secret.encrypted_keys)

            # Convert to dictionary for easier access
            key_dict = {kv.key: kv.value.get_secret_value() for kv in decrypted_keys}

            # Validate and construct the credentials model
            credentials = GitLabCredentials.model_validate(key_dict)

            self.logger.debug(
                "Retrieved GitLab credentials from organization secret",
                gitlab_url=credentials.gitlab_url,
            )
            return credentials

        except Exception as e:
            self.logger.debug("Failed to retrieve GitLab credentials", error=str(e))
            raise GitLabError(f"Failed to retrieve GitLab credentials: {e}") from e

    async def get_gitlab_client_for_repo(self, repo_url: GitUrl) -> gitlab.Gitlab:
        """Get authenticated python-gitlab client for a specific repository.

        Args:
            repo_url: Git repository URL

        Returns:
            Authenticated python-gitlab client

        Raises:
            GitLabError: If authentication fails
        """
        credentials = await self.get_gitlab_credentials()

        try:
            # Create GitLab client
            gl = gitlab.Gitlab(
                url=credentials.gitlab_url,
                private_token=credentials.access_token.get_secret_value(),
            )

            # Authenticate to validate credentials
            gl.auth()

            self.logger.debug(
                "Created authenticated GitLab client",
                gitlab_url=credentials.gitlab_url,
                project=f"{repo_url.org}/{repo_url.repo}",
            )

            return gl

        except GitlabAuthenticationError as e:
            raise GitLabError(f"GitLab authentication failed: {e}") from e
        except GitlabError as e:
            self.logger.error(
                "GitLab API error getting client",
                error=str(e),
                gitlab_url=credentials.gitlab_url,
            )
            raise GitLabError(f"GitLab API error: {e}") from e

    async def list_branches(self, repo_url: GitUrl) -> list[str]:
        """List branches from a GitLab repository.

        Args:
            repo_url: Git repository URL

        Returns:
            List of branch names

        Raises:
            GitLabError: If operation fails
        """
        import asyncio

        gl = await self.get_gitlab_client_for_repo(repo_url)

        try:
            project_path = f"{repo_url.org}/{repo_url.repo}"
            project = await asyncio.to_thread(gl.projects.get, project_path)

            # Get branches
            branches = await asyncio.to_thread(
                project.branches.list, per_page=100, iterator=False
            )

            branch_names = [branch.name for branch in branches]

            self.logger.debug(
                "Listed branches from GitLab repository",
                project=project_path,
                branch_count=len(branch_names),
            )

            return branch_names

        except GitlabError as e:
            self.logger.error(
                "Failed to list branches from GitLab repository",
                error=str(e),
                project=f"{repo_url.org}/{repo_url.repo}",
            )
            raise GitLabError(f"Failed to list branches: {e}") from e

    async def test_connection(self, repo_url: GitUrl) -> dict[str, Any]:
        """Test connection to a GitLab repository.

        Args:
            repo_url: Git repository URL

        Returns:
            Dictionary with connection test results

        Raises:
            GitLabError: If connection fails
        """
        import asyncio

        gl = await self.get_gitlab_client_for_repo(repo_url)

        try:
            project_path = f"{repo_url.org}/{repo_url.repo}"
            project = await asyncio.to_thread(gl.projects.get, project_path)

            # Get default branch and branch count
            branches = await asyncio.to_thread(
                project.branches.list, per_page=100, iterator=False
            )

            return {
                "success": True,
                "project_name": project.name,
                "default_branch": project.default_branch,
                "branches": [branch.name for branch in branches],
                "branch_count": len(branches),
            }

        except GitlabError as e:
            self.logger.error(
                "Connection test failed",
                error=str(e),
                project=f"{repo_url.org}/{repo_url.repo}",
            )
            raise GitLabError(f"Connection test failed: {e}") from e
