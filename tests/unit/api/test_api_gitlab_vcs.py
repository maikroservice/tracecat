"""HTTP-level tests for VCS API endpoints.

Tests verify role-based access control for VCS endpoints, specifically that
the GitLab credentials status endpoint is accessible to workspace editors
(not just org admins).
"""

from collections.abc import Callable, Generator
from typing import get_args
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from tracecat.api.app import app
from tracecat.auth.dependencies import OrgAdminUser, WorkspaceUserRole
from tracecat.auth.types import AccessLevel, Role
from tracecat.authz.enums import WorkspaceRole
from tracecat.db.engine import get_async_session
from tracecat.vcs import router as vcs_router


def _make_editor_role() -> Role:
    return Role(
        type="user",
        access_level=AccessLevel.BASIC,
        workspace_id=uuid4(),
        workspace_role=WorkspaceRole.EDITOR,
        user_id=uuid4(),
        service_id="tracecat-api",
    )


def _make_admin_role() -> Role:
    return Role(
        type="user",
        access_level=AccessLevel.ADMIN,
        workspace_id=uuid4(),
        user_id=uuid4(),
        service_id="tracecat-api",
    )


@pytest.fixture
def vcs_client_factory() -> Generator[Callable[[Role], TestClient], None, None]:
    """Factory fixture that creates a VCS test client bound to a specific role.

    Uses closures over the role so that overrides work correctly regardless
    of thread context propagation.

    - WorkspaceUserRole: passes through any role (no min_access_level)
    - OrgAdminUser (from tracecat.auth.dependencies): enforces ADMIN access level
    """

    def make_client(role: Role) -> TestClient:
        def override_workspace_user() -> Role:
            return role

        def override_org_admin() -> Role:
            if role.access_level < AccessLevel.ADMIN:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden"
                )
            return role

        mock_session = AsyncMock(name="mock_async_session")

        async def override_get_async_session() -> AsyncMock:
            return mock_session

        ws_user_dep = get_args(WorkspaceUserRole)[1].dependency
        org_admin_dep = get_args(OrgAdminUser)[1].dependency

        app.dependency_overrides[ws_user_dep] = override_workspace_user
        app.dependency_overrides[org_admin_dep] = override_org_admin
        app.dependency_overrides[get_async_session] = override_get_async_session

        return TestClient(app, raise_server_exceptions=False)

    yield make_client

    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_gitlab_credentials_status_accessible_to_workspace_editors(
    vcs_client_factory: Callable[[Role], TestClient],
) -> None:
    """Workspace editors should be able to check if GitLab credentials exist.

    The credentials status endpoint only reveals whether credentials are
    configured (a boolean), not the actual token. This information is needed
    by the workflow builder UI to decide whether to show the git publish
    button — so all workspace members must be able to call it.
    """
    vcs_client = vcs_client_factory(_make_editor_role())

    with patch.object(vcs_router, "GitLabService") as MockGitLabService:
        mock_svc = AsyncMock()
        mock_svc.get_gitlab_credentials_status.return_value = {
            "exists": True,
            "gitlab_url": "https://gitlab.com",
            "created_at": None,
        }
        MockGitLabService.return_value = mock_svc

        response = vcs_client.get("/organization/vcs/gitlab/credentials/status")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["exists"] is True
    assert data["gitlab_url"] == "https://gitlab.com"


@pytest.mark.anyio
async def test_gitlab_credentials_status_accessible_to_org_admins(
    vcs_client_factory: Callable[[Role], TestClient],
) -> None:
    """Org admins should also be able to check GitLab credentials status."""
    vcs_client = vcs_client_factory(_make_admin_role())

    with patch.object(vcs_router, "GitLabService") as MockGitLabService:
        mock_svc = AsyncMock()
        mock_svc.get_gitlab_credentials_status.return_value = {
            "exists": False,
            "gitlab_url": None,
            "created_at": None,
        }
        MockGitLabService.return_value = mock_svc

        response = vcs_client.get("/organization/vcs/gitlab/credentials/status")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["exists"] is False
