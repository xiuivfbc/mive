"""Unit tests for VersionService.delete_version."""

from unittest.mock import AsyncMock

import pytest

from src.services.version_service import VersionService
from tests.factories import make_id, make_version
from tests.helpers import make_mock_session


def _build_service(
    version_repo=None,
    session=None,
):
    char_repo = AsyncMock()
    rel_repo = AsyncMock()
    return VersionService(
        version_repo or AsyncMock(),
        char_repo,
        rel_repo,
        session=session or make_mock_session(),
    )


class TestDeleteVersion:
    async def test_delete_non_latest_version_succeeds(self):
        world_id = make_id()
        version_id = make_id()
        parent_id = make_id()

        mock_repo = AsyncMock()
        mock_session = make_mock_session()

        version = make_version(ver_id=version_id, world_id=world_id, parent_id=parent_id)
        mock_repo.get_by_id.return_value = version
        mock_repo.is_latest = AsyncMock(return_value=False)
        mock_repo.delete = AsyncMock(return_value=True)

        # Mock session.execute for update queries
        mock_session.execute = AsyncMock()

        service = _build_service(version_repo=mock_repo, session=mock_session)
        await service.delete_version(version_id, world_id)

        mock_repo.delete.assert_awaited_once_with(version_id)

    async def test_delete_latest_version_raises(self):
        world_id = make_id()
        version_id = make_id()

        mock_repo = AsyncMock()
        mock_session = make_mock_session()

        version = make_version(ver_id=version_id, world_id=world_id)
        mock_repo.get_by_id.return_value = version
        mock_repo.is_latest = AsyncMock(return_value=True)

        service = _build_service(version_repo=mock_repo, session=mock_session)
        with pytest.raises(ValueError, match="Cannot delete the current version"):
            await service.delete_version(version_id, world_id)

    async def test_delete_nonexistent_version_raises(self):
        world_id = make_id()
        version_id = make_id()

        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = None

        service = _build_service(version_repo=mock_repo)
        with pytest.raises(ValueError, match="Version not found"):
            await service.delete_version(version_id, world_id)

    async def test_delete_unlinks_chat_sessions(self):
        world_id = make_id()
        version_id = make_id()

        mock_repo = AsyncMock()
        mock_session = make_mock_session()

        version = make_version(ver_id=version_id, world_id=world_id)
        mock_repo.get_by_id.return_value = version
        mock_repo.is_latest = AsyncMock(return_value=False)
        mock_repo.delete = AsyncMock(return_value=True)

        mock_session.execute = AsyncMock()

        service = _build_service(version_repo=mock_repo, session=mock_session)
        await service.delete_version(version_id, world_id)

        # Two execute calls: one for M4ChatSession update, one for M2WorldVersion reparent
        assert mock_session.execute.await_count == 2

    async def test_delete_reparents_child_versions(self):
        world_id = make_id()
        version_id = make_id()
        parent_id = make_id()

        mock_repo = AsyncMock()
        mock_session = make_mock_session()

        version = make_version(ver_id=version_id, world_id=world_id, parent_id=parent_id)
        mock_repo.get_by_id.return_value = version
        mock_repo.is_latest = AsyncMock(return_value=False)
        mock_repo.delete = AsyncMock(return_value=True)

        mock_session.execute = AsyncMock()

        service = _build_service(version_repo=mock_repo, session=mock_session)
        await service.delete_version(version_id, world_id)

        # Verify flush was called (for each FK update + delete)
        assert mock_session.flush.await_count >= 2

    async def test_delete_no_session_raises_runtime_error(self):
        char_repo = AsyncMock()
        rel_repo = AsyncMock()
        service = VersionService(AsyncMock(), char_repo, rel_repo, session=None)
        with pytest.raises(RuntimeError, match="Session required"):
            await service.delete_version(make_id(), make_id())
