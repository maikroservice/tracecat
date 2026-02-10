"""Workflow synchronization functionality for Tracecat."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Sequence
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import yaml
from github.GithubException import GithubException
from gitlab.exceptions import GitlabError

if TYPE_CHECKING:
    from github.ContentFile import ContentFile
from pydantic import ValidationError

from tracecat.db.models import User
from tracecat.exceptions import TracecatNotFoundError
from tracecat.git.utils import GitUrl
from tracecat.logger import logger
from tracecat.registry.repositories.schemas import GitCommitInfo
from tracecat.service import BaseWorkspaceService
from tracecat.sync import (
    CommitInfo,
    PullDiagnostic,
    PullOptions,
    PullResult,
    PushObject,
    PushOptions,
)
from tracecat.vcs.github.app import GitHubAppError, GitHubAppService
from tracecat.vcs.gitlab.service import GitLabError, GitLabService
from tracecat.workflow.store.import_service import WorkflowImportService
from tracecat.workflow.store.schemas import RemoteWorkflowDefinition
from tracecat.workspaces.service import WorkspaceService


class VCSProvider(StrEnum):
    """Supported VCS providers."""

    GITHUB = "github"
    GITLAB = "gitlab"


# NOTE: Internal service called by higher level services, shouldn't use directly
class WorkflowSyncService(BaseWorkspaceService):
    """Git synchronization service for workflow definitions.

    Implements the SyncService protocol for DSLInput workflow models,
    providing pull/push operations with Git repositories.
    """

    service_name = "workflow_sync"

    def _detect_provider(self, url: GitUrl) -> VCSProvider:
        """Detect the VCS provider from the Git URL.

        Args:
            url: Git repository URL

        Returns:
            VCSProvider enum value
        """
        host_lower = url.host.lower()
        if "github" in host_lower:
            return VCSProvider.GITHUB
        elif "gitlab" in host_lower:
            return VCSProvider.GITLAB
        else:
            # Default to GitLab for unknown hosts (self-hosted instances)
            # as GitHub Enterprise is less common
            logger.warning(
                "Unknown VCS host, defaulting to GitLab",
                host=url.host,
            )
            return VCSProvider.GITLAB

    async def pull(
        self,
        *,
        url: GitUrl,
        options: PullOptions | None = None,
    ) -> PullResult:
        """Pull workflow definitions from a Git repository at specific commit SHA.

        This implementation provides atomic guarantees - either all workflows
        are imported successfully or none are.

        Args:
            url: Git repository URL
            options: Pull options including commit SHA and conflict strategy

        Returns:
            PullResult with success status and diagnostics

        Raises:
            GitHubAppError: If GitHub authentication or API errors occur
        """
        if not options or not options.commit_sha:
            return PullResult(
                success=False,
                commit_sha="",
                workflows_found=0,
                workflows_imported=0,
                diagnostics=[
                    PullDiagnostic(
                        workflow_path="",
                        workflow_title=None,
                        error_type="validation",
                        message="commit_sha is required in pull options",
                        details={},
                    )
                ],
                message="commit_sha is required",
            )

        try:
            # 1. Fetch repository content at specific commit SHA
            repo_content = await self._fetch_repository_content(url, options.commit_sha)

            # 2. Parse workflow definitions
            (
                remote_workflows,
                parse_diagnostics,
            ) = await self._parse_workflow_definitions(repo_content)

            if parse_diagnostics:
                return PullResult(
                    success=False,
                    commit_sha=options.commit_sha,
                    workflows_found=len(repo_content),
                    workflows_imported=0,
                    diagnostics=parse_diagnostics,
                    message=f"Failed to parse {len(parse_diagnostics)} workflow definitions",
                )

            # 3. Import workflows atomically
            if options.dry_run:
                # For dry run, skip import and return validation-only result
                return PullResult(
                    success=True,
                    commit_sha=options.commit_sha,
                    workflows_found=len(remote_workflows),
                    workflows_imported=0,
                    diagnostics=[],
                    message="Dry run completed - workflows validated but not imported",
                )

            import_service = WorkflowImportService(session=self.session, role=self.role)

            return await import_service.import_workflows_atomic(
                remote_workflows=remote_workflows,
                commit_sha=options.commit_sha,
            )

        except GitHubAppError as e:
            logger.error(f"GitHub API error during pull: {e}")
            return PullResult(
                success=False,
                commit_sha=options.commit_sha or "",
                workflows_found=0,
                workflows_imported=0,
                diagnostics=[
                    PullDiagnostic(
                        workflow_path="",
                        workflow_title=None,
                        error_type="github",
                        message=f"GitHub API error: {str(e)}",
                        details={"error": str(e)},
                    )
                ],
                message="GitHub API error",
            )
        except GitLabError as e:
            logger.error(f"GitLab API error during pull: {e}")
            return PullResult(
                success=False,
                commit_sha=options.commit_sha or "",
                workflows_found=0,
                workflows_imported=0,
                diagnostics=[
                    PullDiagnostic(
                        workflow_path="",
                        workflow_title=None,
                        error_type="gitlab",
                        message=f"GitLab API error: {str(e)}",
                        details={"error": str(e)},
                    )
                ],
                message="GitLab API error",
            )
        except Exception as e:
            logger.error(f"Unexpected error during pull: {e}", exc_info=True)
            return PullResult(
                success=False,
                commit_sha=options.commit_sha or "",
                workflows_found=0,
                workflows_imported=0,
                diagnostics=[
                    PullDiagnostic(
                        workflow_path="",
                        workflow_title=None,
                        error_type="system",
                        message=f"Unexpected error: {str(e)}",
                        details={"error": str(e)},
                    )
                ],
                message="System error",
            )

    async def _fetch_repository_content(
        self, url: GitUrl, commit_sha: str
    ) -> dict[str, str]:
        """Fetch workflow definitions from repository at specific commit SHA.

        Args:
            url: Git repository URL
            commit_sha: Specific commit SHA to fetch from

        Returns:
            Dictionary mapping file paths to file content

        Raises:
            GitHubAppError: If GitHub API errors occur
            GitLabError: If GitLab API errors occur
        """
        provider = self._detect_provider(url)

        if provider == VCSProvider.GITLAB:
            return await self._fetch_repository_content_gitlab(url, commit_sha)

        return await self._fetch_repository_content_github(url, commit_sha)

    async def _fetch_repository_content_github(
        self, url: GitUrl, commit_sha: str
    ) -> dict[str, str]:
        """Fetch workflow definitions from GitHub repository."""
        gh_svc = GitHubAppService(session=self.session, role=self.role)
        gh = await gh_svc.get_github_client_for_repo(url)

        try:
            repo = await asyncio.to_thread(gh.get_repo, f"{url.org}/{url.repo}")

            # Get the workflows directory at the specific commit
            try:
                workflows_contents = await asyncio.to_thread(
                    repo.get_contents, "workflows", ref=commit_sha
                )

                if not isinstance(workflows_contents, list):
                    # workflows is a file, not a directory
                    return {}

                content_map = {}

                for item in workflows_contents:
                    item: ContentFile = item  # type hint for GitHub API object
                    # Look for workflow directories
                    if item.type == "dir":
                        # Get definition.yml from each workflow directory
                        definition_path = f"{item.path}/definition.yml"
                        try:
                            definition_file = await asyncio.to_thread(
                                repo.get_contents, definition_path, ref=commit_sha
                            )

                            if not isinstance(definition_file, list) and hasattr(
                                definition_file, "content"
                            ):
                                # Decode base64 content
                                content = base64.b64decode(
                                    definition_file.content
                                ).decode("utf-8")
                                content_map[definition_path] = content
                        except GithubException as e:
                            if e.status != 404:  # Ignore missing definition.yml files
                                logger.warning(f"Failed to get {definition_path}: {e}")

                return content_map

            except GithubException as e:
                if e.status == 404:
                    # No workflows directory found
                    return {}
                raise

        except GithubException as e:
            raise GitHubAppError(f"GitHub API error: {e.status} - {e.data}") from e
        finally:
            gh.close()

    async def _fetch_repository_content_gitlab(
        self, url: GitUrl, commit_sha: str
    ) -> dict[str, str]:
        """Fetch workflow definitions from GitLab repository."""
        gl_svc = GitLabService(session=self.session, role=self.role)
        gl = await gl_svc.get_gitlab_client_for_repo(url)

        try:
            # Get project by path (org/repo)
            project_path = f"{url.org}/{url.repo}"
            project = await asyncio.to_thread(gl.projects.get, project_path)

            # Get the workflows directory at the specific commit
            try:
                # List items in workflows directory
                workflows_items = await asyncio.to_thread(
                    project.repository_tree,
                    path="workflows",
                    ref=commit_sha,
                    iterator=False,
                )

                content_map = {}

                for item in workflows_items:
                    # Look for workflow directories
                    if item["type"] == "tree":  # "tree" is GitLab's term for directory
                        # Get definition.yml from each workflow directory
                        definition_path = f"{item['path']}/definition.yml"
                        try:
                            # Get file content using repository_blob_raw
                            file_content = await asyncio.to_thread(
                                project.files.get,
                                file_path=definition_path,
                                ref=commit_sha,
                            )
                            # Decode content (GitLab returns base64-encoded content)
                            content = base64.b64decode(file_content.content).decode(
                                "utf-8"
                            )
                            content_map[definition_path] = content
                        except GitlabError as e:
                            if "404" not in str(e):  # Ignore missing definition.yml
                                logger.warning(f"Failed to get {definition_path}: {e}")

                return content_map

            except GitlabError as e:
                if "404" in str(e):
                    # No workflows directory found
                    return {}
                raise

        except GitlabError as e:
            raise GitLabError(f"GitLab API error: {e}") from e

    async def _parse_workflow_definitions(
        self, content_map: dict[str, str]
    ) -> tuple[list[RemoteWorkflowDefinition], list[PullDiagnostic]]:
        """Parse workflow definitions from file contents.

        Args:
            content_map: Dictionary mapping file paths to content

        Returns:
            Tuple of (remote_workflows, diagnostics)
        """
        remote_workflows: list[RemoteWorkflowDefinition] = []
        diagnostics: list[PullDiagnostic] = []

        for file_path, content in content_map.items():
            yaml_data: dict[str, Any] | None = None
            try:
                # Parse YAML content
                yaml_data = yaml.safe_load(content)
                if not yaml_data:
                    diagnostics.append(
                        PullDiagnostic(
                            workflow_path=file_path,
                            workflow_title=None,
                            error_type="parse",
                            message="Empty or invalid YAML file",
                            details={},
                        )
                    )
                    continue

                # Convert to RemoteWorkflowDefinition
                remote_workflow = RemoteWorkflowDefinition.model_validate(yaml_data)
                remote_workflows.append(remote_workflow)

            except yaml.YAMLError as e:
                diagnostics.append(
                    PullDiagnostic(
                        workflow_path=file_path,
                        workflow_title=None,
                        error_type="parse",
                        message=f"YAML parsing error: {str(e)}",
                        details={"yaml_error": str(e)},
                    )
                )
            except ValidationError as e:
                diagnostics.append(
                    PullDiagnostic(
                        workflow_path=file_path,
                        workflow_title=yaml_data.get("definition", {}).get("title")
                        if isinstance(yaml_data, dict)
                        else None,
                        error_type="validation",
                        message=f"Validation error: {str(e)}",
                        details={"validation_errors": e.errors()},
                    )
                )
            except Exception as e:
                diagnostics.append(
                    PullDiagnostic(
                        workflow_path=file_path,
                        workflow_title=None,
                        error_type="parse",
                        message=f"Unexpected parsing error: {str(e)}",
                        details={"error": str(e)},
                    )
                )

        return remote_workflows, diagnostics

    async def push(
        self,
        *,
        objects: Sequence[PushObject[RemoteWorkflowDefinition]],
        url: GitUrl,
        options: PushOptions,
    ) -> CommitInfo:
        """Push workflow definitions to a Git repository.

        Args:
            objects: PushObjects containing workflow definitions and target paths
            url: Git repository URL with target branch
            options: Push options including commit message and PR flag

        Returns:
            CommitInfo with commit SHA and branch/PR details
        """
        if len(objects) != 1:
            raise ValueError("We only support pushing one workflow object at a time")

        provider = self._detect_provider(url)

        if provider == VCSProvider.GITLAB:
            return await self._push_gitlab(objects=objects, url=url, options=options)

        return await self._push_github(objects=objects, url=url, options=options)

    async def _push_github(
        self,
        *,
        objects: Sequence[PushObject[RemoteWorkflowDefinition]],
        url: GitUrl,
        options: PushOptions,
    ) -> CommitInfo:
        """Push workflow definitions using GitHub App API operations."""
        [obj] = objects

        gh_svc = GitHubAppService(session=self.session, role=self.role)

        # Use new PyGithub-based method that handles installation resolution automatically
        gh = await gh_svc.get_github_client_for_repo(url)

        try:
            repo = await asyncio.to_thread(gh.get_repo, f"{url.org}/{url.repo}")

            # Get base branch (priority: options.branch > url.ref > repo default)
            base_branch_name = options.branch or url.ref or repo.default_branch
            base_branch = await asyncio.to_thread(repo.get_branch, base_branch_name)

            # Use stable branch name per workflow (allows reusing existing PRs)
            workflow_id = obj.data.id
            branch_name = f"tracecat-sync/{workflow_id}"

            # Check if branch already exists
            branch_exists = False  # noqa: F841
            try:
                await asyncio.to_thread(repo.get_branch, branch_name)
                branch_exists = True  # noqa: F841
                logger.info(
                    "Reusing existing branch via GitHub API",
                    branch=branch_name,
                    base_branch=base_branch_name,
                    repo=f"{url.org}/{url.repo}",
                )
            except GithubException as e:
                if e.status != 404:
                    raise
                # Branch doesn't exist, create it
                logger.info(
                    "Creating new branch via GitHub API",
                    branch=branch_name,
                    base_branch=base_branch_name,
                    repo=f"{url.org}/{url.repo}",
                )
                await asyncio.to_thread(
                    repo.create_git_ref,
                    ref=f"refs/heads/{branch_name}",
                    sha=base_branch.commit.sha,
                )

            # Create/update workflow files via API
            file_path = obj.path_str

            yaml_content = yaml.dump(
                obj.data.model_dump(mode="json", exclude_none=True, exclude_unset=True),
                sort_keys=False,
            )

            # NOTE: We intentionally omit author/committer parameters to enable
            # GitHub's automatic commit signing for GitHub Apps. Per GitHub docs:
            # "Signature verification for bots will only work if the request
            # contains no custom author information, custom committer information"
            # https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification

            try:
                # Try to get existing file to update it
                contents = await asyncio.to_thread(
                    repo.get_contents, file_path, ref=branch_name
                )
                # get_contents returns ContentFile for files, or list for directories
                if isinstance(contents, list):
                    raise GithubException(404, {"message": "Not a file"}, {})

                await asyncio.to_thread(
                    repo.update_file,
                    path=contents.path,
                    message=options.message,
                    content=yaml_content,
                    sha=contents.sha,
                    branch=branch_name,
                )
                logger.debug(
                    "Updated workflow file via API",
                    path=file_path,
                    branch=branch_name,
                )
            except GithubException as e:
                if e.status == 404:
                    # File doesn't exist, create it
                    await asyncio.to_thread(
                        repo.create_file,
                        path=file_path,
                        message=options.message,
                        content=yaml_content,
                        branch=branch_name,
                    )
                    logger.debug(
                        "Created workflow file via API",
                        path=file_path,
                        branch=branch_name,
                    )

            # Get the latest commit SHA from the branch
            branch = await asyncio.to_thread(repo.get_branch, branch_name)
            commit_sha = branch.commit.sha

            # Create PR if requested (only if one doesn't already exist)
            pr_url = None
            if options.create_pr:
                try:
                    # Check for existing open PR from this branch
                    existing_prs = await asyncio.to_thread(
                        repo.get_pulls,
                        head=f"{url.org}:{branch_name}",
                        base=base_branch_name,
                        state="open",
                    )
                    existing_pr_list = list(existing_prs)

                    if existing_pr_list:
                        # PR already exists, reuse it
                        pr_url = existing_pr_list[0].html_url
                        logger.info(
                            "Reusing existing open PR via GitHub API",
                            pr_number=existing_pr_list[0].number,
                            pr_url=pr_url,
                        )
                    else:
                        # No existing PR, create a new one
                        ws_svc = WorkspaceService(session=self.session)
                        workspace = await ws_svc.get_workspace(self.workspace_id)
                        if not workspace:
                            raise TracecatNotFoundError("Workspace not found")

                        try:
                            workflow_title = obj.data.definition.title
                            workflow_description = obj.data.definition.description
                        except ValueError:
                            workflow_title = (
                                "<An error occurred while determining the title>"
                            )
                            workflow_description = (
                                "<An error occurred while determining the description>"
                            )

                        try:
                            current_user = await self.session.get(
                                User, self.role.user_id
                            )
                        except Exception:
                            current_user = None

                        published_by = (
                            current_user.email if current_user else "<unknown>"
                        )

                        # Use workflow title in PR title for human readability
                        pr_title = f"Publish workflow: {workflow_title}"
                        if options.message:
                            pr_title = f"{pr_title} - {options.message}"

                        pr = await asyncio.to_thread(
                            repo.create_pull,
                            title=pr_title,
                            body=(
                                f"Automated workflow sync from Tracecat\n\n"
                                f"**Workspace:** {workspace.name}\n"
                                f"**Published by:** {published_by}\n"
                                f"**Workflow ID:** {workflow_id}\n"
                                f"**Workflow Title:** {workflow_title}\n"
                                f"**Workflow Description:** {workflow_description}"
                            ),
                            head=branch_name,
                            base=base_branch_name,
                        )
                        pr_url = pr.html_url

                        logger.info(
                            "Created PR via GitHub API",
                            pr_number=pr.number,
                            pr_url=pr_url,
                        )
                except GithubException as e:
                    logger.error(
                        "Failed to create/find PR via GitHub API",
                        error=str(e),
                        branch=branch_name,
                    )
                    # Don't fail the entire operation if PR creation fails

            logger.info(
                "Successfully pushed workflows via GitHub API",
                count=1,
                branch=branch_name,
                commit_sha=commit_sha,
                pr_created=pr_url is not None,
            )

            return CommitInfo(
                sha=commit_sha,
                ref=branch_name,
            )

        except GithubException as e:
            logger.error(
                "GitHub API error during push",
                status=e.status,
                data=e.data,
                repo=f"{url.org}/{url.repo}",
            )
            raise GitHubAppError(f"GitHub API error: {e.status} - {e.data}") from e
        finally:
            gh.close()

    async def _push_gitlab(
        self,
        *,
        objects: Sequence[PushObject[RemoteWorkflowDefinition]],
        url: GitUrl,
        options: PushOptions,
    ) -> CommitInfo:
        """Push workflow definitions using GitLab API operations."""
        [obj] = objects

        gl_svc = GitLabService(session=self.session, role=self.role)
        gl = await gl_svc.get_gitlab_client_for_repo(url)

        try:
            # Get project by path
            project_path = f"{url.org}/{url.repo}"
            project = await asyncio.to_thread(gl.projects.get, project_path)

            # Get base branch (priority: options.branch > url.ref > project default)
            base_branch_name = options.branch or url.ref or project.default_branch

            # Use stable branch name per workflow (allows reusing existing MRs)
            workflow_id = obj.data.id
            branch_name = f"tracecat-sync/{workflow_id}"

            # Check if branch already exists
            branch_exists = False  # noqa: F841
            try:
                await asyncio.to_thread(project.branches.get, branch_name)
                branch_exists = True  # noqa: F841
                logger.info(
                    "Reusing existing branch via GitLab API",
                    branch=branch_name,
                    base_branch=base_branch_name,
                    repo=project_path,
                )
            except GitlabError as e:
                if "404" not in str(e):
                    raise
                # Branch doesn't exist, create it
                logger.info(
                    "Creating new branch via GitLab API",
                    branch=branch_name,
                    base_branch=base_branch_name,
                    repo=project_path,
                )
                await asyncio.to_thread(
                    project.branches.create,
                    {"branch": branch_name, "ref": base_branch_name},
                )

            # Create/update workflow file
            file_path = obj.path_str
            yaml_content = yaml.dump(
                obj.data.model_dump(mode="json", exclude_none=True, exclude_unset=True),
                sort_keys=False,
            )

            try:
                # Try to get existing file to update it
                existing_file = await asyncio.to_thread(
                    project.files.get, file_path=file_path, ref=branch_name
                )
                # File exists, update it
                existing_file.content = yaml_content
                existing_file.encoding = "text"
                await asyncio.to_thread(
                    existing_file.save,
                    branch=branch_name,
                    commit_message=options.message,
                )
                logger.debug(
                    "Updated workflow file via GitLab API",
                    path=file_path,
                    branch=branch_name,
                )
            except GitlabError as e:
                if "404" in str(e):
                    # File doesn't exist, create it
                    await asyncio.to_thread(
                        project.files.create,
                        {
                            "file_path": file_path,
                            "branch": branch_name,
                            "content": yaml_content,
                            "commit_message": options.message,
                        },
                    )
                    logger.debug(
                        "Created workflow file via GitLab API",
                        path=file_path,
                        branch=branch_name,
                    )
                else:
                    raise

            # Get the latest commit SHA from the branch
            branch_obj = await asyncio.to_thread(project.branches.get, branch_name)
            commit_sha = branch_obj.commit["id"]

            # Create MR if requested (only if one doesn't already exist)
            mr_url = None
            if options.create_pr:
                try:
                    # Check for existing open MR from this branch
                    existing_mrs = await asyncio.to_thread(
                        project.mergerequests.list,
                        source_branch=branch_name,
                        target_branch=base_branch_name,
                        state="opened",
                    )

                    if existing_mrs:
                        # MR already exists, reuse it
                        mr_url = existing_mrs[0].web_url
                        logger.info(
                            "Reusing existing open MR via GitLab API",
                            mr_iid=existing_mrs[0].iid,
                            mr_url=mr_url,
                        )
                    else:
                        # No existing MR, create a new one
                        ws_svc = WorkspaceService(session=self.session)
                        workspace = await ws_svc.get_workspace(self.workspace_id)
                        if not workspace:
                            raise TracecatNotFoundError("Workspace not found")

                        try:
                            workflow_title = obj.data.definition.title
                            workflow_description = obj.data.definition.description
                        except ValueError:
                            workflow_title = (
                                "<An error occurred while determining the title>"
                            )
                            workflow_description = (
                                "<An error occurred while determining the description>"
                            )

                        try:
                            current_user = await self.session.get(
                                User, self.role.user_id
                            )
                        except Exception:
                            current_user = None

                        published_by = (
                            current_user.email if current_user else "<unknown>"
                        )

                        # Use workflow title in MR title for human readability
                        mr_title = f"Publish workflow: {workflow_title}"
                        if options.message:
                            mr_title = f"{mr_title} - {options.message}"

                        mr = await asyncio.to_thread(
                            project.mergerequests.create,
                            {
                                "source_branch": branch_name,
                                "target_branch": base_branch_name,
                                "title": mr_title,
                                "description": (
                                    f"Automated workflow sync from Tracecat\n\n"
                                    f"**Workspace:** {workspace.name}\n"
                                    f"**Published by:** {published_by}\n"
                                    f"**Workflow ID:** {workflow_id}\n"
                                    f"**Workflow Title:** {workflow_title}\n"
                                    f"**Workflow Description:** {workflow_description}"
                                ),
                            },
                        )
                        mr_url = mr.web_url

                        logger.info(
                            "Created MR via GitLab API",
                            mr_iid=mr.iid,
                            mr_url=mr_url,
                        )
                except GitlabError as e:
                    logger.error(
                        "Failed to create/find MR via GitLab API",
                        error=str(e),
                        branch=branch_name,
                    )
                    # Don't fail the entire operation if MR creation fails

            logger.info(
                "Successfully pushed workflows via GitLab API",
                count=1,
                branch=branch_name,
                commit_sha=commit_sha,
                mr_created=mr_url is not None,
            )

            return CommitInfo(
                sha=commit_sha,
                ref=branch_name,
            )

        except GitlabError as e:
            logger.error(
                "GitLab API error during push",
                error=str(e),
                repo=f"{url.org}/{url.repo}",
            )
            raise GitLabError(f"GitLab API error: {e}") from e

    async def list_commits(
        self,
        *,
        url: GitUrl,
        branch: str = "main",
        limit: int = 10,
    ) -> list[GitCommitInfo]:
        """List commits from a Git repository.

        Args:
            url: Git repository URL
            branch: Branch name to fetch commits from
            limit: Maximum number of commits to return

        Returns:
            List of GitCommitInfo objects with commit details

        Raises:
            GitHubAppError: If GitHub authentication or API errors occur
            GitLabError: If GitLab authentication or API errors occur
        """
        provider = self._detect_provider(url)

        if provider == VCSProvider.GITLAB:
            return await self._list_commits_gitlab(url=url, branch=branch, limit=limit)

        return await self._list_commits_github(url=url, branch=branch, limit=limit)

    async def _list_commits_github(
        self,
        *,
        url: GitUrl,
        branch: str = "main",
        limit: int = 10,
    ) -> list[GitCommitInfo]:
        """List commits from a GitHub repository."""
        try:
            # Get authenticated GitHub client
            gh_svc = GitHubAppService(session=self.session, role=self.role)
            gh = await gh_svc.get_github_client_for_repo(url)

            try:
                # Get repository object
                repo = await asyncio.to_thread(gh.get_repo, f"{url.org}/{url.repo}")

                # Fetch commits using PyGithub
                commits_paginated = await asyncio.to_thread(
                    repo.get_commits, sha=branch
                )

                # Get all tags to build SHA-to-tags mapping
                tags_paginated = await asyncio.to_thread(repo.get_tags)
                sha_to_tags: dict[str, list[str]] = {}

                # Build mapping of commit SHA to tag names in thread to avoid blocking
                def build_tag_mapping():
                    result_map = {}
                    for tag in tags_paginated:
                        tag_sha = tag.commit.sha
                        if tag_sha not in result_map:
                            result_map[tag_sha] = []
                        result_map[tag_sha].append(tag.name)
                    return result_map

                sha_to_tags = await asyncio.to_thread(build_tag_mapping)

                # Convert to GitCommitInfo objects
                commits = []
                count = 0
                for commit in commits_paginated:
                    if count >= limit:
                        break

                    # Get tags for this commit SHA, default to empty list
                    tags = sha_to_tags.get(commit.sha, [])

                    commits.append(
                        GitCommitInfo(
                            sha=commit.sha,
                            message=commit.commit.message,
                            author=commit.commit.author.name or "Unknown",
                            author_email=commit.commit.author.email or "",
                            date=commit.commit.author.date.isoformat(),
                            tags=tags,
                        )
                    )
                    count += 1

                return commits

            finally:
                gh.close()

        except GithubException as e:
            logger.error(
                "GitHub API error during commit listing",
                status=e.status,
                data=e.data,
                repo=f"{url.org}/{url.repo}",
                branch=branch,
            )
            raise GitHubAppError(f"GitHub API error: {e.status} - {e.data}") from e

    async def _list_commits_gitlab(
        self,
        *,
        url: GitUrl,
        branch: str = "main",
        limit: int = 10,
    ) -> list[GitCommitInfo]:
        """List commits from a GitLab repository."""
        try:
            # Get authenticated GitLab client
            gl_svc = GitLabService(session=self.session, role=self.role)
            gl = await gl_svc.get_gitlab_client_for_repo(url)

            # Get project by path
            project_path = f"{url.org}/{url.repo}"
            project = await asyncio.to_thread(gl.projects.get, project_path)

            # Fetch commits
            commits_list = await asyncio.to_thread(
                project.commits.list,
                ref_name=branch,
                per_page=limit,
            )

            # Get all tags to build SHA-to-tags mapping
            tags_list = await asyncio.to_thread(
                project.tags.list,
                iterator=False,
            )
            sha_to_tags: dict[str, list[str]] = {}
            for tag in tags_list:
                tag_sha = tag.commit["id"]
                if tag_sha not in sha_to_tags:
                    sha_to_tags[tag_sha] = []
                sha_to_tags[tag_sha].append(tag.name)

            # Convert to GitCommitInfo objects
            commits = []
            for commit in commits_list:
                # Get tags for this commit SHA, default to empty list
                tags = sha_to_tags.get(commit.id, [])

                commits.append(
                    GitCommitInfo(
                        sha=commit.id,
                        message=commit.message,
                        author=commit.author_name or "Unknown",
                        author_email=commit.author_email or "",
                        date=commit.created_at,
                        tags=tags,
                    )
                )

            return commits

        except GitlabError as e:
            logger.error(
                "GitLab API error during commit listing",
                error=str(e),
                repo=f"{url.org}/{url.repo}",
                branch=branch,
            )
            raise GitLabError(f"GitLab API error: {e}") from e
