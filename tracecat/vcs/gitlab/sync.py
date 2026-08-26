"""Custom (non-EE) GitLab workflow sync.

Implements workflow publish/pull/commit-listing against GitLab via the REST
API using the fork's organization-secret credentials, independent of the
entitlement-gated workspace sync engine.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any

import yaml
from gitlab.exceptions import GitlabError as GitlabApiError
from pydantic import ValidationError

from tracecat.db.models import User, Workflow
from tracecat.dsl.common import DSLInput
from tracecat.exceptions import TracecatNotFoundError, TracecatSettingsError
from tracecat.git.constants import GIT_HTTPS_URL_REGEX
from tracecat.git.types import GitUrl
from tracecat.git.utils import parse_git_url
from tracecat.identifiers.workflow import WorkflowUUID
from tracecat.logger import logger
from tracecat.registry.repositories.schemas import GitCommitInfo
from tracecat.service import BaseWorkspaceService
from tracecat.sync import PullDiagnostic, PullOptions, PullResult
from tracecat.vcs.gitlab.service import GitLabError, GitLabService
from tracecat.workflow.store.import_service import WorkflowImportService
from tracecat.workflow.store.schemas import (
    RemoteWebhook,
    RemoteWorkflowDefinition,
    RemoteWorkflowSchedule,
    RemoteWorkflowTag,
    WorkflowDslPublish,
    WorkflowDslPublishResult,
)
from tracecat.workspaces.service import WorkspaceService


def parse_gitlab_repo_url(url: str) -> GitUrl:
    """Parse a GitLab repository URL (HTTPS or git+ssh) into a GitUrl."""
    if match := GIT_HTTPS_URL_REGEX.match(url):
        path = match.group("path")
        # Split path into org (may contain nested groups) and repo
        org, sep, repo = path.rpartition("/")
        if not sep or not org or not repo:
            raise ValueError(f"Invalid GitLab repository path: {path}")
        return GitUrl(
            host=match.group("host"),
            org=org,
            repo=repo,
            ref=match.group("ref"),
        )
    # Fall back to the shared SSH URL parser
    return parse_git_url(url)


class GitLabWorkflowSyncService(BaseWorkspaceService):
    """Workflow sync operations against a workspace's GitLab repository."""

    service_name = "gitlab_workflow_sync"

    @classmethod
    async def if_gitlab_workspace(
        cls, *, session: Any, role: Any
    ) -> GitLabWorkflowSyncService | None:
        """Return a service instance when this workspace uses the custom GitLab sync.

        The custom path is active when the workspace's git provider is GitLab
        and the fork's organization GitLab credentials are configured.
        """
        svc = cls(session=session, role=role)
        try:
            workspace = await WorkspaceService(
                session=session, role=role
            ).get_workspace(svc.workspace_id)
            if not workspace or not workspace.settings:
                return None
            provider = workspace.settings.get("git_provider")
            if provider != "gitlab":
                # Legacy configs (pre git_provider) are detected by repo URL host.
                repo_url = workspace.settings.get("git_repo_url") or ""
                if provider is not None or "gitlab" not in repo_url.lower():
                    return None
            gl_svc = GitLabService(session=session, role=role)
            if not await gl_svc.has_credentials():
                return None
        except Exception:
            # This is a best-effort probe: any failure means the custom GitLab
            # path does not apply and the caller falls back to the default path.
            return None
        return svc

    async def _get_repo_url(self) -> GitUrl:
        """Resolve the workspace's configured GitLab repository URL."""
        workspace = await WorkspaceService(
            session=self.session, role=self.role
        ).get_workspace(self.workspace_id)
        if not workspace:
            raise TracecatNotFoundError("Workspace not found")
        git_repo_url = (workspace.settings or {}).get("git_repo_url")
        if not git_repo_url:
            raise TracecatSettingsError(
                "Git repository URL not configured for this workspace. "
                "Please contact your administrator to configure it."
            )
        try:
            return parse_gitlab_repo_url(git_repo_url)
        except ValueError as e:
            raise TracecatSettingsError(
                f"Invalid Git repository URL configured for this workspace: {e}"
            ) from e

    async def _get_workspace_default_branch(self) -> str | None:
        workspace = await WorkspaceService(
            session=self.session, role=self.role
        ).get_workspace(self.workspace_id)
        if workspace and workspace.settings:
            return workspace.settings.get("git_branch")
        return None

    async def _build_remote_definition(
        self, *, workflow: Workflow, workflow_id: WorkflowUUID, dsl: DSLInput
    ) -> RemoteWorkflowDefinition:
        await self.session.refresh(workflow, ["tags", "folder", "webhook", "schedules"])
        webhook = workflow.webhook

        folder_path = workflow.folder.path if workflow.folder else None

        return RemoteWorkflowDefinition(
            id=workflow_id.short(),
            alias=workflow.alias,
            folder_path=folder_path,
            tags=[RemoteWorkflowTag(name=t.name) for t in workflow.tags],
            schedules=[
                RemoteWorkflowSchedule(
                    status="online" if str(s.status) == "online" else "offline",
                    cron=s.cron,
                    every=s.every,
                    offset=s.offset,
                    start_at=s.start_at,
                    end_at=s.end_at,
                    timeout=s.timeout,
                )
                for s in (workflow.schedules or [])
            ],
            webhook=RemoteWebhook(
                methods=webhook.methods,
                status="online" if str(webhook.status) == "online" else "offline",
            ),
            definition=dsl,
        )

    async def publish_workflow(
        self,
        *,
        workflow: Workflow,
        workflow_id: WorkflowUUID,
        dsl: DSLInput,
        params: WorkflowDslPublish,
    ) -> WorkflowDslPublishResult:
        """Publish a single workflow definition to the workspace's GitLab repo.

        Commits ``workflows/<id>/definition.yml`` to the target branch
        (creating it from the base branch when missing) and optionally opens
        or reuses a merge request.
        """
        url = await self._get_repo_url()
        message = params.message or f"Publish workflow: {dsl.title}"

        defn = await self._build_remote_definition(
            workflow=workflow, workflow_id=workflow_id, dsl=dsl
        )
        file_path = f"workflows/{workflow_id.short()}/definition.yml"

        gl_svc = GitLabService(session=self.session, role=self.role)
        gl = await gl_svc.get_gitlab_client_for_repo(url)

        try:
            project_path = f"{url.org}/{url.repo}"
            project = await asyncio.to_thread(gl.projects.get, project_path)

            workspace_branch = await self._get_workspace_default_branch()
            base_branch_name = (
                params.pr_base_branch
                or workspace_branch
                or url.ref
                or project.default_branch
            )
            # Target branch: explicit param, else a stable per-workflow branch
            # so repeated publishes reuse the same MR.
            branch_name = params.branch or f"tracecat-sync/{workflow_id.short()}"

            if branch_name != base_branch_name:
                try:
                    await asyncio.to_thread(project.branches.get, branch_name)
                    logger.info(
                        "Reusing existing branch via GitLab API",
                        branch=branch_name,
                        base_branch=base_branch_name,
                        repo=project_path,
                    )
                except GitlabApiError as e:
                    if "404" not in str(e):
                        raise
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

            yaml_content = yaml.dump(
                defn.model_dump(mode="json", exclude_none=True, exclude_unset=True),
                sort_keys=False,
            )

            try:
                existing_file = await asyncio.to_thread(
                    project.files.get, file_path=file_path, ref=branch_name
                )
                existing_file.content = yaml_content
                existing_file.encoding = "text"
                await asyncio.to_thread(
                    existing_file.save,
                    branch=branch_name,
                    commit_message=message,
                )
                logger.debug(
                    "Updated workflow file via GitLab API",
                    path=file_path,
                    branch=branch_name,
                )
            except GitlabApiError as e:
                if "404" in str(e):
                    await asyncio.to_thread(
                        project.files.create,
                        {
                            "file_path": file_path,
                            "branch": branch_name,
                            "content": yaml_content,
                            "commit_message": message,
                        },
                    )
                    logger.debug(
                        "Created workflow file via GitLab API",
                        path=file_path,
                        branch=branch_name,
                    )
                else:
                    raise

            branch_obj = await asyncio.to_thread(project.branches.get, branch_name)
            commit_sha = branch_obj.commit["id"]

            mr_url: str | None = None
            mr_number: int | None = None
            mr_reused = False
            if params.create_pr and branch_name != base_branch_name:
                try:
                    existing_mrs = await asyncio.to_thread(
                        project.mergerequests.list,
                        source_branch=branch_name,
                        target_branch=base_branch_name,
                        state="opened",
                    )

                    if existing_mrs:
                        mr_url = existing_mrs[0].web_url
                        mr_number = existing_mrs[0].iid
                        mr_reused = True
                        logger.info(
                            "Reusing existing open MR via GitLab API",
                            mr_iid=mr_number,
                            mr_url=mr_url,
                        )
                    else:
                        ws_svc = WorkspaceService(session=self.session, role=self.role)
                        workspace = await ws_svc.get_workspace(self.workspace_id)
                        if not workspace:
                            raise TracecatNotFoundError("Workspace not found")

                        try:
                            current_user = await self.session.get(
                                User, self.role.user_id
                            )
                        except Exception:
                            current_user = None
                        published_by = (
                            current_user.email if current_user else "<unknown>"
                        )

                        mr_title = f"Publish workflow: {dsl.title}"
                        if params.message:
                            mr_title = f"{mr_title} - {params.message}"

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
                                    f"**Workflow ID:** {workflow_id.short()}\n"
                                    f"**Workflow Title:** {dsl.title}\n"
                                    f"**Workflow Description:** {dsl.description}"
                                ),
                            },
                        )
                        mr_url = mr.web_url
                        mr_number = mr.iid

                        logger.info(
                            "Created MR via GitLab API",
                            mr_iid=mr_number,
                            mr_url=mr_url,
                        )
                except GitlabApiError as e:
                    logger.error(
                        "Failed to create/find MR via GitLab API",
                        error=str(e),
                        branch=branch_name,
                    )
                    # Don't fail the entire operation if MR creation fails

            logger.info(
                "Successfully pushed workflow via GitLab API",
                branch=branch_name,
                commit_sha=commit_sha,
                mr_created=mr_url is not None,
            )

            return WorkflowDslPublishResult(
                status="committed",
                commit_sha=commit_sha,
                branch=branch_name,
                base_branch=base_branch_name,
                pr_url=mr_url,
                pr_number=mr_number,
                pr_reused=mr_reused,
                message=f"Published workflow to {branch_name}",
            )

        except GitlabApiError as e:
            logger.error(
                "GitLab API error during push",
                error=str(e),
                repo=f"{url.org}/{url.repo}",
            )
            raise GitLabError(f"GitLab API error: {e}") from e

    async def pull(
        self,
        *,
        options: PullOptions,
        sync_schedules: bool = False,
    ) -> PullResult:
        """Pull workflow definitions from GitLab at a specific commit SHA."""
        if not options.commit_sha:
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

        url = await self._get_repo_url()

        try:
            content_map = await self._fetch_repository_content(url, options.commit_sha)
            remote_workflows, parse_diagnostics = self._parse_workflow_definitions(
                content_map
            )

            if parse_diagnostics:
                return PullResult(
                    success=False,
                    commit_sha=options.commit_sha,
                    workflows_found=len(content_map),
                    workflows_imported=0,
                    diagnostics=parse_diagnostics,
                    message=f"Failed to parse {len(parse_diagnostics)} workflow definitions",
                )

            if options.dry_run:
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
                sync_schedules=sync_schedules,
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
        """Fetch workflow definitions from a GitLab repository."""
        gl_svc = GitLabService(session=self.session, role=self.role)
        gl = await gl_svc.get_gitlab_client_for_repo(url)

        try:
            project_path = f"{url.org}/{url.repo}"
            project = await asyncio.to_thread(gl.projects.get, project_path)

            try:
                workflows_items = await asyncio.to_thread(
                    project.repository_tree,
                    path="workflows",
                    ref=commit_sha,
                    iterator=False,
                )

                content_map: dict[str, str] = {}

                for item in workflows_items:
                    # "tree" is GitLab's term for directory
                    if item["type"] == "tree":
                        definition_path = f"{item['path']}/definition.yml"
                        try:
                            file_content = await asyncio.to_thread(
                                project.files.get,
                                file_path=definition_path,
                                ref=commit_sha,
                            )
                            content = base64.b64decode(file_content.content).decode(
                                "utf-8"
                            )
                            content_map[definition_path] = content
                        except GitlabApiError as e:
                            if "404" not in str(e):
                                logger.warning(f"Failed to get {definition_path}: {e}")

                return content_map

            except GitlabApiError as e:
                if "404" in str(e):
                    # No workflows directory found
                    return {}
                raise

        except GitlabApiError as e:
            raise GitLabError(f"GitLab API error: {e}") from e

    def _parse_workflow_definitions(
        self, content_map: dict[str, str]
    ) -> tuple[list[RemoteWorkflowDefinition], list[PullDiagnostic]]:
        """Parse workflow definitions from file contents."""
        remote_workflows: list[RemoteWorkflowDefinition] = []
        diagnostics: list[PullDiagnostic] = []

        for file_path, content in content_map.items():
            yaml_data: dict[str, Any] | None = None
            try:
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

    async def list_commits(
        self,
        *,
        branch: str = "main",
        limit: int = 10,
    ) -> list[GitCommitInfo]:
        """List commits from the workspace's GitLab repository."""
        url = await self._get_repo_url()
        try:
            gl_svc = GitLabService(session=self.session, role=self.role)
            gl = await gl_svc.get_gitlab_client_for_repo(url)

            project_path = f"{url.org}/{url.repo}"
            project = await asyncio.to_thread(gl.projects.get, project_path)

            commits_list = await asyncio.to_thread(
                project.commits.list,
                ref_name=branch,
                per_page=limit,
            )

            tags_list = await asyncio.to_thread(
                project.tags.list,
                iterator=False,
            )
            sha_to_tags: dict[str, list[str]] = {}
            for tag in tags_list:
                tag_sha = tag.commit["id"]
                sha_to_tags.setdefault(tag_sha, []).append(tag.name)

            commits = []
            for commit in commits_list:
                commits.append(
                    GitCommitInfo(
                        sha=commit.id,
                        message=commit.message,
                        author=commit.author_name or "Unknown",
                        author_email=commit.author_email or "",
                        date=commit.created_at,
                        tags=sha_to_tags.get(commit.id, []),
                    )
                )

            return commits

        except GitlabApiError as e:
            logger.error(
                "GitLab API error during commit listing",
                error=str(e),
                repo=f"{url.org}/{url.repo}",
                branch=branch,
            )
            raise GitLabError(f"GitLab API error: {e}") from e

    async def list_branches(self) -> list[str]:
        """List branches from the workspace's GitLab repository."""
        url = await self._get_repo_url()
        gl_svc = GitLabService(session=self.session, role=self.role)
        return await gl_svc.list_branches(url)
