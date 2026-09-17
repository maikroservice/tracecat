"""Tests for the superuser org registry sync remote-freshness behavior."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tracecat_ee.admin.organizations.service import AdminOrgService

from tracecat.auth.types import PlatformRole
from tracecat.db.models import Organization, RegistryRepository, RegistryVersion
from tracecat.registry.actions.types import RepositorySyncOutcome

pytestmark = pytest.mark.usefixtures("db")

OLD_SHA = "a" * 40
NEW_SHA = "b" * 40


def _make_manifest(action_name: str) -> dict[str, Any]:
    namespace, name = action_name.rsplit(".", 1)
    return {
        "actions": {
            action_name: {
                "namespace": namespace,
                "name": name,
                "action_type": "udf",
                "description": f"Test action {action_name}",
                "interface": {"expects": {}, "returns": None},
                "implementation": {
                    "type": "udf",
                    "module": "test_module",
                    "name": name,
                },
            }
        }
    }


@pytest.fixture
def platform_role() -> PlatformRole:
    return PlatformRole(
        type="user",
        user_id=uuid.uuid4(),
        service_id="tracecat-api",
    )


@pytest.fixture
async def org(session: AsyncSession) -> Organization:
    organization = Organization(
        id=uuid.uuid4(),
        name="Sync Org",
        slug=f"sync-org-{uuid.uuid4().hex[:8]}",
        is_active=True,
    )
    session.add(organization)
    await session.commit()
    return organization


async def _create_repo_with_version(
    session: AsyncSession,
    org: Organization,
    *,
    origin: str,
    commit_sha: str | None = OLD_SHA,
) -> RegistryRepository:
    repo = RegistryRepository(organization_id=org.id, origin=origin)
    session.add(repo)
    await session.flush()
    version = RegistryVersion(
        organization_id=org.id,
        repository_id=repo.id,
        version=commit_sha or "1.0.0",
        commit_sha=commit_sha,
        manifest=_make_manifest("test.action_v1"),
        tarball_uri="s3://test/v1.tar.gz",
    )
    session.add(version)
    await session.flush()
    repo.current_version_id = version.id
    session.add(repo)
    await session.commit()
    return repo


@asynccontextmanager
async def _fake_auth_context(**_kwargs: Any) -> AsyncIterator[dict[str, str]]:
    yield {"GIT_TERMINAL_PROMPT": "0"}


@pytest.mark.anyio
async def test_git_sync_skips_when_remote_matches_current_commit(
    session: AsyncSession,
    platform_role: PlatformRole,
    org: Organization,
) -> None:
    repo = await _create_repo_with_version(
        session, org, origin="git+https://github.com/testorg/testrepo.git"
    )
    service = AdminOrgService(session, role=platform_role)

    with (
        patch(
            "tracecat.git.auth.https_token_context",
            _fake_auth_context,
        ),
        patch(
            "tracecat.git.utils.resolve_git_ref",
            AsyncMock(return_value=OLD_SHA),
        ) as resolve_git_ref,
        patch(
            "tracecat.registry.actions.service.RegistryActionsService.sync_actions_from_repository",
            AsyncMock(),
        ) as sync_actions,
    ):
        response = await service.sync_org_repository(org.id, repo.id)

    assert response.skipped is True
    assert response.success is True
    assert response.commit_sha == OLD_SHA
    assert "up to date" in (response.message or "")
    resolve_git_ref.assert_awaited_once()
    sync_actions.assert_not_awaited()


@pytest.mark.anyio
async def test_git_sync_proceeds_when_remote_has_new_commit(
    session: AsyncSession,
    platform_role: PlatformRole,
    org: Organization,
) -> None:
    repo = await _create_repo_with_version(
        session, org, origin="git+https://github.com/testorg/testrepo.git"
    )
    service = AdminOrgService(session, role=platform_role)

    with (
        # Exercise the non-sandboxed path so the auth env forwarding is
        # observable; the sandboxed path fetches credentials in the worker.
        patch("tracecat.config.TRACECAT__REGISTRY_SYNC_SANDBOX_ENABLED", False),
        patch(
            "tracecat.git.auth.https_token_context",
            _fake_auth_context,
        ),
        patch(
            "tracecat.git.utils.resolve_git_ref",
            AsyncMock(return_value=NEW_SHA),
        ),
        patch(
            "tracecat.registry.actions.service.RegistryActionsService.sync_actions_from_repository",
            AsyncMock(
                return_value=RepositorySyncOutcome(commit_sha=NEW_SHA, version=NEW_SHA)
            ),
        ) as sync_actions,
    ):
        response = await service.sync_org_repository(org.id, repo.id)

    assert response.skipped is False
    assert response.success is True
    assert response.commit_sha == NEW_SHA
    sync_actions.assert_awaited_once()
    # The auth env from the token context is forwarded to the sync.
    assert sync_actions.await_args is not None
    assert sync_actions.await_args.kwargs["ssh_env"] == {"GIT_TERMINAL_PROMPT": "0"}
    # The previous version is retained (not force-deleted).
    versions = (
        (
            await session.execute(
                select(RegistryVersion).where(RegistryVersion.repository_id == repo.id)
            )
        )
        .scalars()
        .all()
    )
    assert {v.commit_sha for v in versions} == {OLD_SHA}


@pytest.mark.anyio
async def test_git_force_sync_deletes_current_version_without_remote_check(
    session: AsyncSession,
    platform_role: PlatformRole,
    org: Organization,
) -> None:
    repo = await _create_repo_with_version(
        session, org, origin="git+https://github.com/testorg/testrepo.git"
    )
    service = AdminOrgService(session, role=platform_role)

    with (
        patch(
            "tracecat.git.auth.https_token_context",
            _fake_auth_context,
        ),
        patch(
            "tracecat.git.utils.resolve_git_ref",
            AsyncMock(return_value=OLD_SHA),
        ) as resolve_git_ref,
        patch(
            "tracecat.registry.actions.service.RegistryActionsService.sync_actions_from_repository",
            AsyncMock(
                return_value=RepositorySyncOutcome(commit_sha=OLD_SHA, version=OLD_SHA)
            ),
        ) as sync_actions,
    ):
        response = await service.sync_org_repository(org.id, repo.id, force=True)

    assert response.skipped is False
    assert response.forced is True
    resolve_git_ref.assert_not_awaited()
    sync_actions.assert_awaited_once()
    versions = (
        (
            await session.execute(
                select(RegistryVersion).where(RegistryVersion.repository_id == repo.id)
            )
        )
        .scalars()
        .all()
    )
    assert versions == []


@pytest.mark.anyio
async def test_git_ssh_sync_also_compares_remote(
    session: AsyncSession,
    platform_role: PlatformRole,
    org: Organization,
) -> None:
    repo = await _create_repo_with_version(
        session, org, origin="git+ssh://git@github.com/testorg/testrepo.git"
    )
    service = AdminOrgService(session, role=platform_role)

    with (
        # SSH probes only run in non-sandboxed mode; sandboxed sync keeps all
        # SSH credentials in the worker.
        patch("tracecat.config.TRACECAT__REGISTRY_SYNC_SANDBOX_ENABLED", False),
        patch(
            "tracecat.ssh.ssh_context",
            _fake_auth_context,
        ),
        patch(
            "tracecat.git.utils.resolve_git_ref",
            AsyncMock(return_value=OLD_SHA),
        ) as resolve_git_ref,
        patch(
            "tracecat.registry.actions.service.RegistryActionsService.sync_actions_from_repository",
            AsyncMock(),
        ) as sync_actions,
    ):
        response = await service.sync_org_repository(org.id, repo.id)

    assert response.skipped is True
    resolve_git_ref.assert_awaited_once()
    sync_actions.assert_not_awaited()


@pytest.mark.anyio
async def test_non_git_sync_keeps_skip_unless_forced(
    session: AsyncSession,
    platform_role: PlatformRole,
    org: Organization,
) -> None:
    repo = await _create_repo_with_version(
        session, org, origin="local", commit_sha=None
    )
    service = AdminOrgService(session, role=platform_role)

    with patch(
        "tracecat.registry.actions.service.RegistryActionsService.sync_actions_from_repository",
        AsyncMock(),
    ) as sync_actions:
        response = await service.sync_org_repository(org.id, repo.id)

    assert response.skipped is True
    assert "already exists" in (response.message or "")
    sync_actions.assert_not_awaited()
