"""Custom (non-EE) GitLab VCS router.

Replaces the entitlement-gated GitLab token endpoints with the fork's
organization-secret based credential management. Mounted unconditionally
from the API app (not gated by any feature flag or entitlement).
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import noload

from tracecat.auth.dependencies import OrgUserRole
from tracecat.authz.controls import require_scope
from tracecat.db.dependencies import AsyncDBSession
from tracecat.db.models import Workspace
from tracecat.logger import logger
from tracecat.vcs.gitlab.service import GitLabError, GitLabService
from tracecat.vcs.gitlab.sync import parse_gitlab_repo_url
from tracecat.vcs.schemas import (
    GitLabCredentialsRequest,
    GitLabCredentialsStatus,
    GitLabTestConnectionRequest,
    GitLabTestConnectionResponse,
    GitLabWorkspaceConfig,
)

gitlab_router = APIRouter(prefix="/gitlab", tags=["vcs", "gitlab", "organization"])
"""Manage GitLab credentials for organization-level features."""


@gitlab_router.post("/credentials", status_code=status.HTTP_201_CREATED)
@require_scope("org:settings:update")
async def save_gitlab_credentials(
    *,
    session: AsyncDBSession,
    role: OrgUserRole,
    request: GitLabCredentialsRequest,
) -> dict[str, str]:
    """Save GitLab credentials (register new or update existing)."""
    try:
        gitlab_service = GitLabService(session=session, role=role)
        config, was_created = await gitlab_service.save_gitlab_credentials(
            access_token=request.access_token,
            gitlab_url=request.gitlab_url,
        )

        action = "created" if was_created else "updated"
        logger.info(
            f"GitLab credentials {action}",
            gitlab_url=request.gitlab_url,
        )

        return {
            "message": f"GitLab credentials {action} successfully",
            "action": action,
            "gitlab_url": config.gitlab_url,
        }

    except GitLabError as e:
        logger.error("Failed to save GitLab credentials", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to save GitLab credentials: {str(e)}",
        ) from e
    except Exception as e:
        logger.error("Error saving GitLab credentials", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while saving credentials",
        ) from e


@gitlab_router.get("/credentials/status", response_model=GitLabCredentialsStatus)
@require_scope("org:settings:read")
async def get_gitlab_credentials_status(
    *,
    session: AsyncDBSession,
    role: OrgUserRole,
) -> GitLabCredentialsStatus:
    """Get the status of GitLab credentials."""
    try:
        gitlab_service = GitLabService(session=session, role=role)
        status_data = await gitlab_service.get_gitlab_credentials_status()
        return GitLabCredentialsStatus(**status_data)

    except Exception as e:
        logger.error("Error getting GitLab credentials status", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while getting credentials status",
        ) from e


@gitlab_router.delete("/credentials", status_code=status.HTTP_204_NO_CONTENT)
@require_scope("org:settings:delete")
async def delete_gitlab_credentials(
    *,
    session: AsyncDBSession,
    role: OrgUserRole,
) -> None:
    """Delete GitLab credentials."""
    try:
        gitlab_service = GitLabService(session=session, role=role)
        await gitlab_service.delete_gitlab_credentials()
        logger.info("GitLab credentials deleted")

    except GitLabError as e:
        logger.error("Failed to delete GitLab credentials", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to delete GitLab credentials: {str(e)}",
        ) from e
    except Exception as e:
        logger.error("Error deleting GitLab credentials", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while deleting credentials",
        ) from e


@gitlab_router.post("/test-connection", response_model=GitLabTestConnectionResponse)
@require_scope("org:settings:read")
async def test_gitlab_connection(
    *,
    session: AsyncDBSession,
    role: OrgUserRole,
    request: GitLabTestConnectionRequest,
) -> GitLabTestConnectionResponse:
    """Test connection to a GitLab repository and list available branches."""
    try:
        git_url = parse_gitlab_repo_url(request.git_repo_url)

        gitlab_service = GitLabService(session=session, role=role)
        result = await gitlab_service.test_connection(git_url)

        return GitLabTestConnectionResponse(
            success=True,
            project_name=result.get("project_name"),
            default_branch=result.get("default_branch"),
            branches=result.get("branches", []),
            branch_count=result.get("branch_count", 0),
        )

    except ValueError as e:
        logger.warning("Invalid Git URL format", error=str(e))
        return GitLabTestConnectionResponse(
            success=False,
            error=f"Invalid repository URL: {str(e)}",
        )
    except GitLabError as e:
        logger.error("GitLab connection test failed", error=str(e))
        return GitLabTestConnectionResponse(
            success=False,
            error=str(e),
        )
    except Exception as e:
        logger.error("Error testing GitLab connection", error=str(e))
        return GitLabTestConnectionResponse(
            success=False,
            error="Internal server error while testing connection",
        )


@gitlab_router.get("/workspaces", response_model=list[GitLabWorkspaceConfig])
@require_scope("org:settings:read")
async def list_gitlab_workspace_configs(
    *,
    session: AsyncDBSession,
    role: OrgUserRole,
) -> list[GitLabWorkspaceConfig]:
    """List all workspaces with their git repository configuration.

    Returns only workspace id, name, git_repo_url, and git_branch for the GitLab
    integration overview. This follows least privilege by not exposing
    other workspace settings.
    """
    statement = (
        select(Workspace)
        .options(noload("*"))
        .where(Workspace.organization_id == role.organization_id)
    )
    result = await session.execute(statement)
    workspaces = result.scalars().all()

    return [
        GitLabWorkspaceConfig(
            id=str(ws.id),
            name=ws.name,
            git_repo_url=ws.settings.get("git_repo_url") if ws.settings else None,
            git_branch=ws.settings.get("git_branch") if ws.settings else None,
        )
        for ws in workspaces
    ]


# Standalone router with the full prefix for unconditional mounting in app.py
gitlab_org_router = APIRouter(prefix="/organization/vcs", tags=["vcs", "organization"])
gitlab_org_router.include_router(gitlab_router)
