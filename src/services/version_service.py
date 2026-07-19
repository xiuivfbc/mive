import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.repositories.character_memory_repo import CharacterMemoryRepository
from src.db.repositories.character_repo import CharacterRepository
from src.db.repositories.relation_repo import RelationRepository
from src.db.repositories.version_repo import VersionRepository
from src.models.proposal import WorldVersion
from src.services.snapshot_sync_service import bump_generation_sql

if TYPE_CHECKING:
    from src.services.character_service import CharacterService

logger = logging.getLogger(__name__)


def _to_json_safe(obj):
    """递归将 datetime 转为 ISO 字符串，确保 JSONB 可序列化。"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_json_safe(item) for item in obj]
    return obj


class VersionService:
    def __init__(
        self,
        version_repo: VersionRepository,
        character_repo: CharacterRepository,
        relation_repo: RelationRepository,
        session: AsyncSession | None = None,
        memory_repo: CharacterMemoryRepository | None = None,
        redis: Redis | None = None,
        character_service: "CharacterService | None" = None,
    ):
        self.version_repo = version_repo
        self.character_repo = character_repo
        self.relation_repo = relation_repo
        self.session = session
        self.memory_repo = memory_repo
        self.redis = redis
        self._character_service = character_service

    async def _build_snapshot_data(
        self,
        world_id: str,
        include_memories: bool = True,
        include_dialogues: bool = True,
    ) -> dict:
        """构建快照数据字典（从当前世界状态读取），供 create_snapshot / update_snapshot 复用。"""
        from src.db.models import M1World

        if self.session is None:
            raise RuntimeError("Session required for building snapshot data")

        # 1. 查询世界行（获取 user_character_id 和 elements）
        world_row = await self.session.scalar(
            select(M1World).where(M1World.id == uuid.UUID(world_id))
        )
        world_user_char_id: str | None = (
            str(world_row.user_character_id) if world_row and world_row.user_character_id else None
        )

        # Elements 存储在 world_doc JSONB 中
        elements_data: list[dict] = []
        if world_row and world_row.world_doc:
            raw_elements = world_row.world_doc.get("elements", [])
            for el in raw_elements:
                elements_data.append(
                    {
                        "name": el.get("name", ""),
                        "category": el.get("category", ""),
                        "brief": el.get("brief", ""),
                        "detail": el.get("detail", ""),
                    }
                )

        # 2. 角色数据（不含 UUID）
        characters = await self.character_repo.list_by_world(world_id)
        char_snapshot_list: list[dict] = []
        for char in characters:
            is_user_char = world_user_char_id is not None and char.id == world_user_char_id

            # 查询记忆（仅完整快照时查询，跳过 DB 查询以优化性能）
            # 每个角色独立 dict，避免共享可变对象被意外篡改
            memories: dict = {"short_term": [], "long_term": []}
            if include_memories and self.memory_repo is not None:
                char_uuid = uuid.UUID(char.id)
                short_term_rows = await self.memory_repo.list_short_term(char_uuid, limit=10)
                long_term_rows = await self.memory_repo.list_long_term(char_uuid)
                memories = {
                    "short_term": [m.content for m in reversed(short_term_rows)],
                    "long_term": [m.content for m in long_term_rows],
                }

            char_snapshot_list.append(
                {
                    "name": char.name,
                    "tier": char.tier,
                    "entity_type": char.entity_type,
                    "is_user_character": is_user_char,
                    "profile": char.profile,
                    "memories": memories,
                }
            )

        # 3. 关系数据（用名字，不用 UUID）
        id_to_name: dict[str, str] = {c.id: c.name for c in characters}
        relations = await self.relation_repo.list_by_world(world_id)
        rel_snapshot_list: list[dict] = []
        for rel in relations:
            name_a = id_to_name.get(rel.character_a)
            name_b = id_to_name.get(rel.character_b)
            if name_a is None or name_b is None:
                continue
            rel_snapshot_list.append(
                {
                    "character_a": name_a,
                    "character_b": name_b,
                    "description": rel.description,
                    "direction": rel.direction,
                    "type": rel.type,
                }
            )

        # 4. 对话 session 元数据（仅完整快照时查询）
        dialogues: list[dict] = []
        if include_dialogues:
            dialogues = await self.version_repo.get_dialogue_metadata(world_id)

        snapshot_type = "full" if include_memories else "light"

        return {
            "format_version": "v2",
            "snapshot_type": snapshot_type,
            "characters": char_snapshot_list,
            "relations": rel_snapshot_list,
            "elements": elements_data,
            "dialogues": dialogues,
        }

    async def create_snapshot(
        self,
        world_id: str,
        created_by: str | None = None,
        summary: str | None = None,
        include_memories: bool = True,
        include_dialogues: bool = True,
    ) -> WorldVersion:
        """创建 v2 格式快照。characters/relations/elements 不存 UUID，只存业务数据。

        Args:
            include_memories: False 时跳过记忆查询（轻量快照），角色 memories 为空。
            include_dialogues: False 时跳过对话元数据查询（轻量快照），dialogues 为空。
        """
        from src.db.models import M1World

        snapshot = await self._build_snapshot_data(world_id, include_memories, include_dialogues)

        latest = await self.version_repo.get_latest(world_id)
        parent_id = latest.id if latest else None

        new_version = await self.version_repo.create(
            world_id=world_id,
            snapshot=snapshot,
            created_by=created_by,
            summary=summary,
            parent_version_id=parent_id,
        )

        # Bug 4: 写入 synced_generation，使快照记录与当前 generation 对齐
        world_uuid = uuid.UUID(world_id)
        current_gen = await self.session.scalar(
            select(M1World.snapshot_generation).where(M1World.id == world_uuid)
        )
        if current_gen is not None:
            await self.version_repo.update_synced_generation(new_version.id, current_gen)

        return new_version

    async def update_snapshot(self, version_id: str, world_id: str) -> WorldVersion:
        """将指定版本或最新版本的快照数据更新为当前世界状态。"""
        version = await self.version_repo.get_by_id(version_id)
        if version is None:
            raise ValueError("Version not found")

        snapshot = await self._build_snapshot_data(
            world_id, include_memories=True, include_dialogues=True
        )
        updated = await self.version_repo.update_snapshot(version_id, snapshot)
        if updated is None:
            raise ValueError("Version not found")
        return updated

    async def create_version(self, world_id: str) -> WorldVersion:
        """创建新版本：先自动更新当前版本快照，再创建新版本。"""
        snapshot = await self._build_snapshot_data(
            world_id, include_memories=True, include_dialogues=True
        )

        # 1. 更新当前最新版本的快照（保存当前状态到现有版本）
        latest = await self.version_repo.get_latest(world_id)
        if latest:
            await self.version_repo.update_snapshot(latest.id, snapshot)

        # 2. 创建新版本
        new_version = await self.version_repo.create(
            world_id=world_id,
            snapshot=snapshot,
            created_by="user",
            summary=None,
            parent_version_id=latest.id if latest else None,
        )

        # 3. 写入 synced_generation
        from src.db.models import M1World

        world_uuid = uuid.UUID(world_id)
        current_gen = await self.session.scalar(
            select(M1World.snapshot_generation).where(M1World.id == world_uuid)
        )
        if current_gen is not None:
            await self.version_repo.update_synced_generation(new_version.id, current_gen)

        return new_version

    async def rollback(self, version_id: str, world_id: str) -> WorldVersion:
        """回滚到指定版本快照。用户角色原地 UPDATE，NPC 删建重建。"""
        target = await self.version_repo.get_by_id(version_id)
        if target is None:
            raise ValueError("Version not found")

        # 回滚前自动保存完整快照，便于撤销误操作
        await self.create_snapshot(world_id, created_by="system", summary="回滚前自动快照")

        snapshot = target.snapshot

        if self.session is None:
            raise RuntimeError("Session required for rollback")

        from src.db.models import M1World, M2Character, M2CharacterMemory

        async with self.session.begin_nested():
            # 1. 查世界行，获取用户角色 UUID
            world_row = await self.session.scalar(
                select(M1World).where(M1World.id == uuid.UUID(world_id))
            )
            user_char_id: str | None = (
                str(world_row.user_character_id)
                if world_row and world_row.user_character_id
                else None
            )

            # 2. 从快照中找 is_user_character=true 的记录
            snap_chars: list[dict] = snapshot.get("characters", [])
            user_char_snap: dict | None = next(
                (c for c in snap_chars if c.get("is_user_character")), None
            )
            npc_snaps = [c for c in snap_chars if not c.get("is_user_character")]

            # 3. 全删关系（必须先于角色）
            await self.relation_repo.delete_all_by_world(world_id)

            # 4. 删非用户角色
            # 通过 CharacterService 安全路径：先清理事件引用再删除
            if self._character_service is not None:
                if user_char_id:
                    await self._character_service.force_delete_non_user_characters(
                        world_id, user_char_id
                    )
                else:
                    await self._character_service.force_delete_all_by_world(world_id)
            else:
                # 向后兼容：无 character_service 时直接操作 repo（旧路径）
                await self.character_repo.list_by_world(world_id)
                if user_char_id:
                    await self.character_repo.delete_non_user_characters(world_id, user_char_id)
                else:
                    await self.character_repo.delete_all_by_world(world_id)

            # 5. 用户角色原地 UPDATE（UUID 不动）
            if user_char_id and user_char_snap is not None:
                await self.session.execute(
                    update(M2Character)
                    .where(M2Character.id == uuid.UUID(user_char_id))
                    .values(
                        profile=user_char_snap.get("profile", {}),
                        tier=user_char_snap.get("tier"),
                        entity_type=user_char_snap.get("entity_type", "character"),
                    )
                )
                await self.session.flush()

                # 无条件清除旧记忆，从快照恢复（轻量快照 memories 为空即清空）
                await self.version_repo.delete_memories_by_character_ids([user_char_id])
                user_memories = user_char_snap.get("memories", {})
                for content in user_memories.get("short_term", []):
                    self.session.add(
                        M2CharacterMemory(
                            character_id=uuid.UUID(user_char_id),
                            world_id=uuid.UUID(world_id),
                            memory_type="short_term",
                            content=content,
                        )
                    )
                for content in user_memories.get("long_term", []):
                    self.session.add(
                        M2CharacterMemory(
                            character_id=uuid.UUID(user_char_id),
                            world_id=uuid.UUID(world_id),
                            memory_type="long_term",
                            content=content,
                        )
                    )
                await self.session.flush()

            # 8. 重建 NPC（新 UUID，bulk_create 自动生成）
            name_to_id: dict[str, str] = {}
            if npc_snaps:
                # Strip any id field to ensure fresh UUIDs
                clean_npcs = [
                    {k: v for k, v in npc.items() if k not in ("id", "is_user_character")}
                    for npc in npc_snaps
                ]
                created_npcs = await self.character_repo.bulk_create(world_id, clean_npcs)
                for char in created_npcs:
                    name_to_id[char.name] = char.id

            # 9. 从快照恢复 NPC 记忆（按名字匹配新 UUID，轻量快照 memories 为空即不恢复）
            all_current_chars = await self.character_repo.list_by_world(world_id)
            npc_name_to_char = {
                c.name: c for c in all_current_chars if user_char_id is None or c.id != user_char_id
            }
            npc_memory_source = {
                npc_snap.get("name", ""): npc_snap.get("memories", {}) for npc_snap in npc_snaps
            }
            for npc_name, memories in npc_memory_source.items():
                char = npc_name_to_char.get(npc_name)
                if char is None:
                    continue
                for content in memories.get("short_term", []):
                    self.session.add(
                        M2CharacterMemory(
                            character_id=uuid.UUID(char.id),
                            world_id=uuid.UUID(world_id),
                            memory_type="short_term",
                            content=content,
                        )
                    )
                for content in memories.get("long_term", []):
                    self.session.add(
                        M2CharacterMemory(
                            character_id=uuid.UUID(char.id),
                            world_id=uuid.UUID(world_id),
                            memory_type="long_term",
                            content=content,
                        )
                    )
            await self.session.flush()

            # 10. 用户角色也加入 name_to_id（用旧 UUID）
            if user_char_id and user_char_snap is not None:
                user_char_name = user_char_snap.get("name", "")
                if user_char_name:
                    name_to_id[user_char_name] = user_char_id

            # 11. 从快照恢复关系（NPC 用新 UUID，用户角色用旧 UUID）
            snap_rels: list[dict] = snapshot.get("relations", [])
            if snap_rels:
                resolved_rels = []
                for rel in snap_rels:
                    name_a = rel.get("character_a", "")
                    name_b = rel.get("character_b", "")
                    id_a = name_to_id.get(name_a)
                    id_b = name_to_id.get(name_b)
                    if id_a is None or id_b is None:
                        logger.warning(
                            "[回滚] 关系跳过（名字未匹配）: %s ↔ %s world=%s",
                            name_a,
                            name_b,
                            world_id,
                        )
                        continue
                    resolved_rels.append(
                        {
                            "character_a": id_a,
                            "character_b": id_b,
                            "description": rel.get("description"),
                            "direction": rel.get("direction", "bidirectional"),
                            "type": rel.get("type"),
                        }
                    )
                if resolved_rels:
                    await self.relation_repo.bulk_create(world_id, resolved_rels)

            # 12. 从快照恢复 elements（更新 world_doc JSONB）
            snap_elements: list[dict] = snapshot.get("elements", [])
            if snap_elements and world_row is not None:
                world_doc = dict(world_row.world_doc) if world_row.world_doc else {}
                # Rebuild elements list with UUIDs (keep existing IDs if possible)
                existing_el_map: dict[str, str] = {}
                for el in world_doc.get("elements", []):
                    if el.get("name"):
                        existing_el_map[el["name"]] = el.get("id", str(uuid.uuid4()))
                new_elements = []
                for el in snap_elements:
                    name = el.get("name", "")
                    new_elements.append(
                        {
                            "id": existing_el_map.get(name, str(uuid.uuid4())),
                            "name": name,
                            "category": el.get("category", ""),
                            "brief": el.get("brief", ""),
                            "detail": el.get("detail", ""),
                        }
                    )
                world_doc["elements"] = new_elements
                world_row.world_doc = world_doc
                await self.session.flush()

            # 13. 创建新版本记录（回滚版本成为新的活跃版本）
            latest = await self.version_repo.get_latest(world_id)
            parent_id = latest.id if latest else None

            new_version = await self.version_repo.create(
                world_id=world_id,
                snapshot=snapshot,
                created_by="user",
                summary=f"回滚到版本 {version_id[:8]}",
                parent_version_id=parent_id,
            )

            # 14. 标记快照 generation 脏位（事务内，外层 commit 后由调用方 publish）
            await bump_generation_sql(world_id, self.session)

            # 15. 写入 synced_generation，使新版本记录与当前 generation 对齐
            #     bump 之后 snapshot_generation 已是新值，必须同步写入，否则同步服务
            #     比对 snapshot_generation > synced_generation 时会崩溃或触发冗余重建。
            world_uuid = uuid.UUID(world_id)
            current_gen = await self.session.scalar(
                select(M1World.snapshot_generation).where(M1World.id == world_uuid)
            )
            if current_gen is not None:
                await self.version_repo.update_synced_generation(new_version.id, current_gen)

            return new_version

    async def list_by_world(self, world_id: str) -> list[WorldVersion]:
        return await self.version_repo.list_by_world(world_id)

    async def delete_version(self, version_id: str, world_id: str) -> None:
        """Delete a version with FK cleanup. Raises ValueError if latest or not found."""
        if self.session is None:
            raise RuntimeError("Session required for delete_version")

        version = await self.version_repo.get_by_id(version_id)
        if version is None:
            raise ValueError("Version not found")

        if await self.version_repo.is_latest(version_id, world_id):
            raise ValueError("Cannot delete the current version")

        # 1. Unlink chat sessions (prevent CASCADE deleting chat data)
        from src.db.models import M4ChatSession

        await self.session.execute(
            update(M4ChatSession)
            .where(M4ChatSession.version_id == uuid.UUID(version_id))
            .values(version_id=None)
        )
        await self.session.flush()

        # 2. Re-parent child versions to deleted version's parent
        parent_id = version.parent_version_id
        from src.db.models import M2WorldVersion

        await self.session.execute(
            update(M2WorldVersion)
            .where(M2WorldVersion.parent_version_id == uuid.UUID(version_id))
            .values(parent_version_id=uuid.UUID(parent_id) if parent_id else None)
        )
        await self.session.flush()

        # 3. Delete the version
        deleted = await self.version_repo.delete(version_id)
        if not deleted:
            raise ValueError("Version not found")

    async def update_summary(self, version_id: str, summary: str | None) -> WorldVersion:
        cleaned = summary.strip() if isinstance(summary, str) else None
        version = await self.version_repo.update_summary(version_id, cleaned or None)
        if version is None:
            raise ValueError("Version not found")
        return version
