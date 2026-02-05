"""VCS integration router for organization-level platform features."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from tracecat.auth.dependencies import OrgAdminUser
from tracecat.db.dependencies import AsyncDBSession
from tracecat.logger import logger
from tracecat.vcs.github.app import GitHubAppError, GitHubAppService
from tracecat.vcs.github.flows import handle_manifest_conversion
from tracecat.vcs.github.manifest import generate_github_app_manifest
from tracecat.vcs.gitlab.service import GitLabError, GitLabService
from tracecat.vcs.schemas import (
    GitHubAppCredentialsRequest,
    GitHubAppCredentialsStatus,
    GitHubAppManifestResponse,
    GitLabCredentialsRequest,
    GitLabCredentialsStatus,
)

org_router = APIRouter(prefix="/organization/vcs", tags=["vcs", "organization"])
"""Manage organization-level VCS features."""

github_router = APIRouter(prefix="/github", tags=["vcs", "github", "organization"])
"""Manage GitHub App for organization-level features."""


@github_router.get("/manifest", response_model=GitHubAppManifestResponse)
async def get_github_app_manifest(
    *,
    _role: OrgAdminUser,
) -> GitHubAppManifestResponse:
    """Generate GitHub App manifest for enterprise installation."""
    try:
        manifest = generate_github_app_manifest()
        return GitHubAppManifestResponse(
            manifest=manifest,
            instructions=[
                "1. Copy the manifest JSON below",
                "2. Go to GitHub.com and navigate to your organization settings",
                "3. Go to Developer settings > GitHub Apps > New GitHub App",
                "4. Click 'Create GitHub App from manifest'",
                "5. Paste the manifest JSON and click 'Create'",
                "6. GitHub will redirect back to Tracecat to complete the setup automatically",
            ],
        )

    except Exception as e:
        logger.error("Error generating GitHub App manifest", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error generating GitHub App manifest",
        ) from e


@github_router.get("/install")
async def github_app_install_callback(
    *,
    session: AsyncDBSession,
    role: OrgAdminUser,
    code: str = Query(..., description="Temporary code from GitHub manifest flow"),
):
    """Handle GitHub App installation flow.

    This endpoint handles two different flows:
    1. Code exchange: When GitHub redirects with a temporary code after manifest submission
    2. Installation callback: When GitHub redirects after app installation
    """
    logger.info("GitHub App installation callback", code=code[:5] + "...")
    try:
        # Code exchange flow: Convert manifest code to app credentials
        return await handle_manifest_conversion(session, role, code)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error handling GitHub App install", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during GitHub App installation",
        ) from e


@github_router.post("/webhook")
async def github_webhook(*, payload: dict[str, Any]) -> dict[str, str]:
    """Handle GitHub webhook events."""
    try:
        event_type = payload.get("action")
        installation_data = payload.get("installation", {})
        installation_id = installation_data.get("id")

        logger.info(
            "Received GitHub webhook",
            event_type=event_type,
            installation_id=installation_id,
        )

        # Handle installation events
        if event_type in ("created", "deleted") and installation_id:
            logger.info(
                f"GitHub App installation {event_type}",
                installation_id=installation_id,
                account=installation_data.get("account", {}).get("login"),
            )
            # Note: We don't automatically set installation_id here because
            # we cannot reliably correlate webhooks to specific workspaces
            # without additional context. The installation callback flow
            # handles this more reliably.

        # TODO: Process other webhook events
        # - repository access changes
        # - push events for synchronization

        return {"message": "Webhook processed successfully"}

    except Exception as e:
        logger.error("Error processing GitHub webhook", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing webhook",
        ) from e


@github_router.post("/credentials", status_code=status.HTTP_201_CREATED)
async def save_github_app_credentials(
    *,
    session: AsyncDBSession,
    role: OrgAdminUser,
    request: GitHubAppCredentialsRequest,
) -> dict[str, str]:
    """Save GitHub App credentials (register new or update existing)."""
    # Organization-level operation, no specific checks needed since this is org VCS
    try:
        github_service = GitHubAppService(session=session, role=role)
        config, was_created = await github_service.save_github_app_credentials(
            app_id=request.app_id,
            private_key_pem=request.private_key,
            webhook_secret=request.webhook_secret,
            client_id=request.client_id,
        )

        action = "created" if was_created else "updated"
        logger.info(
            f"GitHub App credentials {action}",
            app_id=request.app_id,
        )

        return {
            "message": f"GitHub App credentials {action} successfully",
            "action": action,
            "app_id": config.app_id or request.app_id,
        }

    except GitHubAppError as e:
        logger.error("Failed to save GitHub App credentials", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to save GitHub App credentials: {str(e)}",
        ) from e
    except Exception as e:
        logger.error("Error saving GitHub App credentials", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while saving credentials",
        ) from e


@github_router.get("/credentials/status", response_model=GitHubAppCredentialsStatus)
async def get_github_app_credentials_status(
    *,
    session: AsyncDBSession,
    role: OrgAdminUser,
) -> GitHubAppCredentialsStatus:
    """Get the status of GitHub App credentials."""
    # Organization-level operation, no specific checks needed since this is org VCS
    try:
        github_service = GitHubAppService(session=session, role=role)
        status_data = await github_service.get_github_app_credentials_status()
        return GitHubAppCredentialsStatus(**status_data)

    except Exception as e:
        logger.error("Error getting GitHub App credentials status", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while getting credentials status",
        ) from e


# GitLab router

gitlab_router = APIRouter(prefix="/gitlab", tags=["vcs", "gitlab", "organization"])
"""Manage GitLab credentials for organization-level features."""


@gitlab_router.post("/credentials", status_code=status.HTTP_201_CREATED)
async def save_gitlab_credentials(
    *,
    session: AsyncDBSession,
    role: OrgAdminUser,
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
async def get_gitlab_credentials_status(
    *,
    session: AsyncDBSession,
    role: OrgAdminUser,
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
async def delete_gitlab_credentials(
    *,
    session: AsyncDBSession,
    role: OrgAdminUser,
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


# Mount GitHub sub-router to organization VCS router (gated by git-sync feature flag)
org_router.include_router(github_router)

# GitLab router is mounted separately in app.py (not gated by feature flag)
# Export gitlab_router with the full prefix for standalone mounting
gitlab_org_router = APIRouter(prefix="/organization/vcs", tags=["vcs", "organization"])
gitlab_org_router.include_router(gitlab_router)
