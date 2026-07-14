"""快照异步同步服务

负责：
1. bump_generation / publish_snapshot_dirty — 触发点调用
2. SnapshotSyncService — Redis Pub/Sub 消费者，debounce 后比对 generation 决定是否重建快照
3. 启动时全量兜底检查 (reconcile_all)

设计决策见 docs/tech/SNAPSHOT_REFORM.md 决策 5/6。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_PUBSUB_CHANNEL = "snapshot_dirty"
_DEBOUNCE_SECONDS = 5


# ---------------------------------------------------------------------------
# bump_generation helpers
# ---------------------------------------------------------------------------


async def bump_generation_sql(world_id: str, session: AsyncSession) -> None:
    """在事务内将 snapshot_generation 原子 +1。

    注意：调用方必须在外层事务 commit 之后再调用 publish_snapshot_dirty，
    否则消费者读到的是提交前的旧数据。
    """
    await session.execute(
        text("UPDATE m1_worlds SET snapshot_generation = snapshot_generation + 1 WHERE id = :wid"),
        {"wid": str(world_id)},
    )


async def publish_snapshot_dirty(redis: Redis, world_id: str, source: str = "unknown") -> None:
    """在事务 commit 之后发布 dirty 通知。"""
    try:
        message = json.dumps({"world_id": str(world_id), "source": source})
        await redis.publish(_PUBSUB_CHANNEL, message)
    except Exception as exc:
        # Pub/Sub 失败不影响主流程——启动时全量兜底会补救
        logger.warning("publish_snapshot_dirty failed world=%s: %s", world_id, exc)


def _build_version_service(session: AsyncSession):
    """Construct a VersionService for snapshot operations (eliminates duplicate construction)."""
    from src.db.repositories.character_memory_repo import CharacterMemoryRepository
    from src.db.repositories.character_repo import CharacterRepository
    from src.db.repositories.relation_repo import RelationRepository
    from src.db.repositories.version_repo import VersionRepository
    from src.services.version_service import VersionService

    return VersionService(
        version_repo=VersionRepository(session),
        character_repo=CharacterRepository(session),
        relation_repo=RelationRepository(session),
        session=session,
        memory_repo=CharacterMemoryRepository(session),
    )


# ---------------------------------------------------------------------------
# SnapshotSyncService — 消费者
# ---------------------------------------------------------------------------


class SnapshotSyncService:
    """Redis Pub/Sub 消费者，监听 snapshot_dirty 频道。

    收到 dirty 通知后 debounce 5 秒，再比对
    m1_worlds.snapshot_generation vs m2_world_versions.synced_generation，
    不一致则触发全量快照重建。
    """

    def __init__(self, redis: Redis, session_factory) -> None:
        self._redis = redis
        self._session_factory = session_factory  # async_session callable
        self._task: asyncio.Task | None = None
        # pending world_ids waiting for debounce
        self._pending: dict[str, asyncio.TimerHandle] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        # tracked background tasks to avoid leaks on shutdown
        self._tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        self._loop = asyncio.get_event_loop()
        self._task = asyncio.create_task(self._run(), name="snapshot_sync_consumer")
        logger.info("SnapshotSyncService started")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Cancel any pending debounce handles
        for handle in self._pending.values():
            handle.cancel()
        self._pending.clear()
        # Cancel and await all tracked background tasks
        for t in list(self._tasks):
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("SnapshotSyncService stopped")

    async def _run(self) -> None:
        """主消费循环：订阅 Redis Pub/Sub 频道并处理消息，断线自动重连。"""
        backoff = 1
        while True:
            pubsub = self._redis.pubsub()
            try:
                await pubsub.subscribe(_PUBSUB_CHANNEL)
                logger.debug("SnapshotSyncService subscribed to channel: %s", _PUBSUB_CHANNEL)
                backoff = 1  # 连接成功，重置退避
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    raw = message.get("data")
                    if isinstance(raw, bytes):
                        raw = raw.decode()
                    if isinstance(raw, str):
                        try:
                            parsed = json.loads(raw)
                            if isinstance(parsed, dict):
                                world_id = parsed.get("world_id", raw)
                                source = parsed.get("source", "unknown")
                            else:
                                world_id = raw
                                source = "unknown"
                        except (ValueError, TypeError):
                            # Backward compat: plain world_id string
                            world_id = raw
                            source = "unknown"
                    else:
                        continue
                    self._schedule_dirty(world_id, source)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug(
                    "SnapshotSyncService consumer error: %s — reconnecting in %ds", exc, backoff
                )
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    break
                backoff = min(backoff * 2, 30)
            finally:
                try:
                    await pubsub.unsubscribe(_PUBSUB_CHANNEL)
                except Exception:
                    pass
                try:
                    await pubsub.aclose()
                except Exception:
                    pass

    def _schedule_dirty(self, world_id: str, source: str = "unknown") -> None:
        """Debounce：重置定时器，5 秒内收到多次 dirty 只触发一次重建。"""
        existing = self._pending.get(world_id)
        if existing is not None:
            existing.cancel()
        loop = self._loop or asyncio.get_event_loop()

        def _fire(wid: str = world_id, src: str = source) -> None:
            t = asyncio.ensure_future(self._check_and_rebuild(wid, src))
            self._tasks.add(t)
            t.add_done_callback(self._tasks.discard)

        handle = loop.call_later(_DEBOUNCE_SECONDS, _fire)
        self._pending[world_id] = handle

    async def _check_and_rebuild(self, world_id: str, source: str = "unknown") -> None:
        """比对 generation，不一致时重建快照。"""
        self._pending.pop(world_id, None)
        try:
            await self._do_rebuild_if_dirty(world_id, source)
        except Exception as exc:
            logger.error("SnapshotSyncService rebuild error world=%s: %s", world_id, exc)

    async def _do_rebuild_if_dirty(self, world_id: str, source: str = "unknown") -> None:
        from src.db.models import M1World, M2WorldVersion

        async with self._session_factory() as session:
            # Read current snapshot_generation from m1_worlds
            world_row = await session.scalar(
                select(M1World).where(M1World.id == uuid.UUID(world_id))
            )
            if world_row is None:
                return
            current_gen = world_row.snapshot_generation

            # Read synced_generation of the latest snapshot
            latest_version = await session.scalar(
                select(M2WorldVersion)
                .where(M2WorldVersion.world_id == uuid.UUID(world_id))
                .order_by(M2WorldVersion.created_at.desc())
                .limit(1)
            )
            synced_gen = latest_version.synced_generation if latest_version is not None else -1

            if current_gen <= synced_gen:
                logger.debug(
                    "snapshot up-to-date world=%s gen=%d synced=%d",
                    world_id,
                    current_gen,
                    synced_gen,
                )
                return

            logger.info(
                "rebuilding snapshot world=%s gen=%d synced=%d", world_id, current_gen, synced_gen
            )
            await self._rebuild_snapshot(session, world_id, source)
            await session.commit()

    async def _rebuild_snapshot(
        self, session: AsyncSession, world_id: str, source: str = "unknown"
    ) -> None:
        """全量重建快照，并将 synced_generation 写入新版本记录。"""
        version_svc = _build_version_service(session)
        await version_svc.create_snapshot(
            world_id=world_id,
            created_by=f"sync:{source}",
            summary=f"结构快照同步 (source={source})",
            include_memories=False,
            include_dialogues=False,
        )


# ---------------------------------------------------------------------------
# 启动时全量兜底检查
# ---------------------------------------------------------------------------


async def reconcile_all(session_factory) -> None:
    """FastAPI lifespan 调用：对所有活跃世界执行 generation 比对，不一致则触发重建。"""
    from src.db.models import M1World, M2WorldVersion

    async with session_factory() as session:
        # 查所有 status='active' 的世界
        worlds = (
            await session.execute(
                select(M1World.id, M1World.snapshot_generation).where(M1World.status == "active")
            )
        ).all()

        dirty_worlds: list[tuple[str, int]] = []
        for world_id, snap_gen in worlds:
            latest_version = await session.scalar(
                select(M2WorldVersion)
                .where(M2WorldVersion.world_id == world_id)
                .order_by(M2WorldVersion.created_at.desc())
                .limit(1)
            )
            synced_gen = latest_version.synced_generation if latest_version is not None else -1
            if snap_gen > synced_gen:
                dirty_worlds.append((str(world_id), snap_gen))

    if not dirty_worlds:
        logger.info("reconcile_all: all snapshots up-to-date (%d worlds checked)", len(worlds))
        return

    logger.info("reconcile_all: %d world(s) need snapshot rebuild", len(dirty_worlds))
    for world_id, generation in dirty_worlds:
        try:
            async with session_factory() as session:
                version_svc = _build_version_service(session)
                await version_svc.create_snapshot(
                    world_id=world_id,
                    created_by="reconcile",
                    summary="启动兜底快照同步",
                )
                await session.commit()
            logger.info("reconcile_all: rebuilt snapshot world=%s gen=%d", world_id, generation)
        except Exception as exc:
            logger.error("reconcile_all: failed world=%s: %s", world_id, exc)
