from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.character import Character
from src.models.relation import Relation
from src.services.version_service import VersionService
from tests.factories import make_id, make_version
from tests.helpers import make_mock_session


def _mock_world_row(user_character_id=None, world_doc=None):
    """Create a mock M1World row for session.scalar()."""
    return SimpleNamespace(
        user_character_id=user_character_id,
        world_doc=world_doc,
    )


def _mock_execute_result(rows=None, scalar_value=None):
    """Create a mock result for session.execute().all() / .scalar_one() / .scalar_one_or_none()."""
    result = MagicMock()
    result.all.return_value = rows or []
    result.scalar_one.return_value = scalar_value if scalar_value is not None else 0
    result.scalar_one_or_none.return_value = scalar_value
    return result


def _setup_mock_session(world_row=None):
    """Create a mock session with scalar + execute properly configured."""
    mock_session = make_mock_session()
    mock_session.scalar = AsyncMock(return_value=world_row or _mock_world_row())
    mock_session.execute = AsyncMock(return_value=_mock_execute_result())
    return mock_session


def _make_mock_memory_repo():
    """Create a mock CharacterMemoryRepository with short/long term list methods."""
    mock = AsyncMock()
    mock.list_short_term = AsyncMock(return_value=[])
    mock.list_long_term = AsyncMock(return_value=[])
    return mock


class TestVersionServiceCreateSnapshot:
    async def test_create_snapshot_fetches_current_state(self):
        mock_version_repo = AsyncMock()
        mock_char_repo = AsyncMock()
        mock_rel_repo = AsyncMock()
        mock_memory_repo = _make_mock_memory_repo()
        mock_session = _setup_mock_session()

        world_id = make_id()
        char_id = make_id()
        chars = [
            Character(
                id=char_id,
                world_id=world_id,
                name="叶文洁",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        ]
        rels = [
            Relation(
                id=make_id(),
                world_id=world_id,
                character_a=char_id,
                character_b=make_id(),
                type="同事",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        ]
        mock_char_repo.list_by_world.return_value = chars
        mock_rel_repo.list_by_world.return_value = rels
        mock_version_repo.get_latest.return_value = None
        mock_version_repo.create.return_value = make_version()

        service = VersionService(
            mock_version_repo,
            mock_char_repo,
            mock_rel_repo,
            session=mock_session,
            memory_repo=mock_memory_repo,
        )
        await service.create_snapshot(world_id, "user", "创建角色")

        mock_char_repo.list_by_world.assert_called_once_with(world_id)
        mock_rel_repo.list_by_world.assert_called_once_with(world_id)
        # 完整快照应查询记忆
        mock_memory_repo.list_short_term.assert_called_once()
        mock_memory_repo.list_long_term.assert_called_once()

    async def test_create_snapshot_chains_to_parent(self):
        mock_version_repo = AsyncMock()
        mock_char_repo = AsyncMock()
        mock_rel_repo = AsyncMock()
        mock_memory_repo = _make_mock_memory_repo()
        mock_session = _setup_mock_session()

        world_id = make_id()
        parent = make_version(ver_id=make_id())
        mock_version_repo.get_latest.return_value = parent
        mock_version_repo.create.return_value = make_version(ver_id=make_id(), parent_id=parent.id)
        mock_char_repo.list_by_world.return_value = []
        mock_rel_repo.list_by_world.return_value = []

        service = VersionService(
            mock_version_repo,
            mock_char_repo,
            mock_rel_repo,
            session=mock_session,
            memory_repo=mock_memory_repo,
        )
        await service.create_snapshot(world_id, "user", "更新角色")

        # 验证 create 被调用时传入了 parent_version_id
        call_kwargs = mock_version_repo.create.call_args
        assert call_kwargs[1]["parent_version_id"] == parent.id

    async def test_create_snapshot_first_version_has_no_parent(self):
        mock_version_repo = AsyncMock()
        mock_char_repo = AsyncMock()
        mock_rel_repo = AsyncMock()
        mock_memory_repo = _make_mock_memory_repo()
        mock_session = _setup_mock_session()

        world_id = make_id()
        mock_version_repo.get_latest.return_value = None
        mock_version_repo.create.return_value = make_version()
        mock_char_repo.list_by_world.return_value = []
        mock_rel_repo.list_by_world.return_value = []

        service = VersionService(
            mock_version_repo,
            mock_char_repo,
            mock_rel_repo,
            session=mock_session,
            memory_repo=mock_memory_repo,
        )
        await service.create_snapshot(world_id, "user", "初始版本")

        call_kwargs = mock_version_repo.create.call_args
        assert call_kwargs[1].get("parent_version_id") is None

    async def test_create_snapshot_light_skips_memory_queries(self):
        """轻量快照（include_memories=False）应跳过记忆查询。"""
        mock_version_repo = AsyncMock()
        mock_char_repo = AsyncMock()
        mock_rel_repo = AsyncMock()
        mock_memory_repo = _make_mock_memory_repo()
        mock_session = _setup_mock_session()

        world_id = make_id()
        char_id = make_id()
        chars = [
            Character(
                id=char_id,
                world_id=world_id,
                name="叶文洁",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        ]
        mock_char_repo.list_by_world.return_value = chars
        mock_rel_repo.list_by_world.return_value = []
        mock_version_repo.get_latest.return_value = None
        mock_version_repo.create.return_value = make_version()

        service = VersionService(
            mock_version_repo,
            mock_char_repo,
            mock_rel_repo,
            session=mock_session,
            memory_repo=mock_memory_repo,
        )
        await service.create_snapshot(world_id, "user", "轻量快照", include_memories=False)

        # 轻量快照不应查询记忆
        mock_memory_repo.list_short_term.assert_not_called()
        mock_memory_repo.list_long_term.assert_not_called()

        # 快照中角色 memories 应为空
        call_kwargs = mock_version_repo.create.call_args
        snapshot = call_kwargs[1]["snapshot"]
        assert snapshot["snapshot_type"] == "light"
        assert snapshot["characters"][0]["memories"] == {"short_term": [], "long_term": []}

    async def test_create_snapshot_full_has_snapshot_type_full(self):
        """完整快照的 snapshot_type 应为 'full'。"""
        mock_version_repo = AsyncMock()
        mock_char_repo = AsyncMock()
        mock_rel_repo = AsyncMock()
        mock_memory_repo = _make_mock_memory_repo()
        mock_session = _setup_mock_session()

        world_id = make_id()
        mock_char_repo.list_by_world.return_value = []
        mock_rel_repo.list_by_world.return_value = []
        mock_version_repo.get_latest.return_value = None
        mock_version_repo.create.return_value = make_version()

        service = VersionService(
            mock_version_repo,
            mock_char_repo,
            mock_rel_repo,
            session=mock_session,
            memory_repo=mock_memory_repo,
        )
        await service.create_snapshot(world_id, "user", "完整快照")

        call_kwargs = mock_version_repo.create.call_args
        snapshot = call_kwargs[1]["snapshot"]
        assert snapshot["snapshot_type"] == "full"


class TestVersionServiceRollback:
    async def test_rollback_creates_new_version_with_target_snapshot(self):
        mock_version_repo = AsyncMock()
        mock_char_repo = AsyncMock()
        mock_rel_repo = AsyncMock()
        mock_memory_repo = _make_mock_memory_repo()
        mock_session = _setup_mock_session()

        world_id = make_id()
        target_snapshot = {
            "snapshot_type": "full",
            "characters": [{"id": make_id()}],
            "relations": [],
        }
        target_version = make_version(ver_id=make_id(), world_id=world_id, snapshot=target_snapshot)
        mock_version_repo.get_by_id.return_value = target_version
        mock_version_repo.get_latest.return_value = make_version(
            ver_id=make_id(), world_id=world_id
        )
        mock_version_repo.create.return_value = make_version(ver_id=make_id(), world_id=world_id)
        # 回滚前 create_snapshot 需要 list_by_world 返回可迭代列表
        mock_char_repo.list_by_world.return_value = []
        mock_rel_repo.list_by_world.return_value = []

        service = VersionService(
            mock_version_repo,
            mock_char_repo,
            mock_rel_repo,
            session=mock_session,
            memory_repo=mock_memory_repo,
        )
        await service.rollback(target_version.id, world_id)

        # rollback 创建两次版本记录：回滚前自动快照 + 回滚版本
        # 最后一次 create 调用是回滚版本，snapshot 应与目标一致
        call_kwargs = mock_version_repo.create.call_args
        assert call_kwargs[1]["snapshot"] == target_snapshot
        assert "回滚" in call_kwargs[1]["summary"]

    async def test_rollback_creates_pre_rollback_snapshot_first(self):
        """回滚前应先创建一个完整快照（回滚前自动快照），然后再创建回滚版本。"""
        mock_version_repo = AsyncMock()
        mock_char_repo = AsyncMock()
        mock_rel_repo = AsyncMock()
        mock_memory_repo = _make_mock_memory_repo()
        mock_session = _setup_mock_session()

        world_id = make_id()
        target_snapshot = {
            "snapshot_type": "light",
            "characters": [],
            "relations": [],
        }
        target_version = make_version(ver_id=make_id(), world_id=world_id, snapshot=target_snapshot)
        mock_version_repo.get_by_id.return_value = target_version
        mock_version_repo.get_latest.return_value = None
        mock_version_repo.create.return_value = make_version(ver_id=make_id(), world_id=world_id)
        mock_char_repo.list_by_world.return_value = []
        mock_rel_repo.list_by_world.return_value = []

        service = VersionService(
            mock_version_repo,
            mock_char_repo,
            mock_rel_repo,
            session=mock_session,
            memory_repo=mock_memory_repo,
        )
        await service.rollback(target_version.id, world_id)

        # 应创建两次版本记录
        assert mock_version_repo.create.call_count == 2

        # 第一次：回滚前自动快照（完整快照，由 system 创建）
        first_call_kwargs = mock_version_repo.create.call_args_list[0]
        assert first_call_kwargs[1]["created_by"] == "system"
        assert "回滚前" in first_call_kwargs[1]["summary"]
        assert first_call_kwargs[1]["snapshot"]["snapshot_type"] == "full"

        # 第二次：回滚版本（使用目标快照数据）
        second_call_kwargs = mock_version_repo.create.call_args_list[1]
        assert "回滚" in second_call_kwargs[1]["summary"]
        assert second_call_kwargs[1]["snapshot"] == target_snapshot

    async def test_rollback_nonexistent_version_raises(self):
        mock_version_repo = AsyncMock()
        mock_char_repo = AsyncMock()
        mock_rel_repo = AsyncMock()

        mock_version_repo.get_by_id.return_value = None

        service = VersionService(mock_version_repo, mock_char_repo, mock_rel_repo)
        with pytest.raises(ValueError, match="Version not found"):
            await service.rollback("nonexistent", make_id())
