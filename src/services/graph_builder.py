"""M6 GraphBuilderService — Zep 图谱构建服务。

Phase 4: Zep is a pure consumer. This service reads character data from
M2Character and builds Zep graph nodes/edges. It does NOT write Zep data
back to MIVE DB.
"""

import asyncio
import logging
import threading
import time

from zep_cloud import EpisodeData

from src.services.task_manager import TaskManager, TaskStatus

logger = logging.getLogger(__name__)

# Zep 处理 episodes 的最长等待时间（秒）
_ZEP_POLL_INTERVAL = 15
_ZEP_POLL_MAX_ATTEMPTS = 20  # 20 * 15s = 5 min


class GraphBuilderService:
    def __init__(self, zep_client, session_factory=None, task_manager: TaskManager | None = None):
        self.zep = zep_client
        self.session_factory = session_factory
        self.task_manager = task_manager or TaskManager()

    def build_async(
        self,
        world_id: str,
        text: str = "",
        ontology: dict | None = None,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        batch_size: int = 3,
        characters: list[dict] | None = None,
        relations: list[dict] | None = None,
    ) -> str:
        task_id = self.task_manager.create_task(
            "graph_build",
            metadata={"world_id": world_id},
        )
        thread = threading.Thread(
            target=self._build_worker,
            args=(
                task_id,
                world_id,
                text,
                ontology,
                chunk_size,
                chunk_overlap,
                batch_size,
                characters,
                relations,
            ),
            daemon=True,
        )
        thread.start()
        return task_id

    def _build_worker(
        self,
        task_id: str,
        world_id: str,
        text: str,
        ontology: dict | None,
        chunk_size: int,
        chunk_overlap: int,
        batch_size: int,
        characters: list[dict] | None,
        relations: list[dict] | None,
    ):
        # world_id 同时作为 Zep user_id，使用用户图模式
        zep_user_id = world_id
        try:
            self.task_manager.update_task(
                task_id, status=TaskStatus.PROCESSING, progress=5, message="开始构建图谱"
            )

            # 标记 DB 状态为 building
            if self.session_factory:
                asyncio.run(self._update_graph_status(world_id, graph_status="building"))

            # 1. 创建 Zep 用户（已存在则忽略）
            try:
                self.zep.user.add(user_id=zep_user_id)
            except Exception:
                pass  # 用户已存在
            self.task_manager.update_task(task_id, progress=15, message="Zep 用户已就绪")

            # 2. Build episodes from characters and relations (M2Character data)
            episodes = self._build_episodes_from_characters(
                characters=characters or [],
                relations=relations or [],
                text=text,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            total = len(episodes)
            self.task_manager.update_task(task_id, progress=20, message=f"准备 {total} 个 episodes")

            # 3. 分批写入 episodes（绑定到用户图）
            for i in range(0, total, batch_size):
                batch = episodes[i : i + batch_size]
                ep_objects = [EpisodeData(data=ep, type="text") for ep in batch]
                self.zep.graph.add_batch(user_id=zep_user_id, episodes=ep_objects)
                progress = 30 + int((i + len(batch)) / total * 30)
                self.task_manager.update_task(
                    task_id,
                    progress=progress,
                    message=f"已写入 {i + len(batch)}/{total} 个 episodes",
                )

            # 4. 等待 Zep 处理完成（轮询直到节点出现或超时）
            self.task_manager.update_task(task_id, progress=62, message="等待 Zep 处理图谱...")
            nodes: list = []
            edges: list = []
            for attempt in range(_ZEP_POLL_MAX_ATTEMPTS):
                time.sleep(_ZEP_POLL_INTERVAL)
                try:
                    nodes = self.zep.graph.node.get_by_user_id(zep_user_id, limit=2000) or []
                except Exception:
                    nodes = []
                if nodes:
                    try:
                        edges = self.zep.graph.edge.get_by_user_id(zep_user_id, limit=2000) or []
                    except Exception:
                        edges = []
                    break
                poll_progress = 62 + min(attempt + 1, 15)
                self.task_manager.update_task(
                    task_id,
                    progress=poll_progress,
                    message=f"等待 Zep 处理... ({attempt + 1}/{_ZEP_POLL_MAX_ATTEMPTS})",
                )

            self.task_manager.update_task(task_id, progress=80, message="获取图谱数据完成")

            # 5. 转为普通 dict，避免跨线程传递 SDK 对象
            node_dicts = [
                {
                    "uuid": n.uuid_,
                    "name": n.name or "",
                    "labels": n.labels or [],
                    "summary": n.summary or "",
                }
                for n in nodes
            ]
            edge_dicts = [
                {
                    "uuid": e.uuid_,
                    "name": e.name or "",
                    "fact": e.fact or "",
                    "source_node_uuid": e.source_node_uuid,
                    "target_node_uuid": e.target_node_uuid,
                }
                for e in edges
            ]

            # 6. Update graph status to completed (no longer persisting to MIVE DB)
            if self.session_factory:
                asyncio.run(self._update_graph_status(world_id, graph_status="completed"))

            self.task_manager.complete_task(
                task_id,
                {
                    "graph_id": zep_user_id,
                    "node_count": len(node_dicts),
                    "edge_count": len(edge_dicts),
                },
            )

        except Exception as e:
            self.task_manager.fail_task(task_id, str(e))
            if self.session_factory:
                try:
                    asyncio.run(
                        self._update_graph_status(world_id, graph_status="failed", graph_id=None)
                    )
                except Exception:
                    pass

    @staticmethod
    def _build_episodes_from_characters(
        characters: list[dict],
        relations: list[dict],
        text: str,
        chunk_size: int,
        chunk_overlap: int,
    ) -> list[str]:
        """Build text episodes from M2Character data and optional raw text.

        Characters and relations are formatted into text episodes that Zep
        can process into graph nodes and edges.
        """
        from src.services.text_processor import TextProcessor

        episodes: list[str] = []

        # Build character episodes
        for char in characters:
            name = char.get("name", "未知")
            profile = char.get("profile", {})
            basic = profile.get("basic", {})
            brief = profile.get("brief", "")
            detail = profile.get("detail", "")
            entity_type = char.get("entity_type", "character")

            parts = [f"[{entity_type}] {name}"]
            if basic:
                for key in ("occupation", "gender", "age", "race"):
                    if basic.get(key):
                        parts.append(f"{key}: {basic[key]}")
            if brief:
                parts.append(f"简介: {brief}")
            if detail:
                parts.append(f"背景: {str(detail)[:500]}")
            episodes.append("。".join(parts))

        # Build relation episodes
        for rel in relations:
            char_a_name = rel.get("char_a_name", "未知")
            char_b_name = rel.get("char_b_name", "未知")
            rel_type = rel.get("type", "")
            description = rel.get("description", "")
            parts = [f"{char_a_name} 与 {char_b_name}"]
            if rel_type:
                parts.append(f"关系类型: {rel_type}")
            if description:
                parts.append(f"描述: {description}")
            episodes.append("。".join(parts))

        # Also include raw text chunks if provided
        if text:
            chunks = TextProcessor.split_text(text, chunk_size, chunk_overlap)
            episodes.extend(chunks)

        return episodes

    # ── 异步 DB 操作（在后台线程中通过 asyncio.run() 调用）──────────────────

    def _make_session_factory(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from src.config import settings

        engine = create_async_engine(settings.database_url, pool_size=1, max_overflow=0)
        return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine

    async def _update_graph_status(
        self,
        world_id: str,
        graph_status: str,
        graph_id: str | None = None,
    ) -> None:
        from src.db.repositories.world_repo import WorldRepository

        factory, engine = self._make_session_factory()
        try:
            async with factory() as session:
                async with session.begin():
                    repo = WorldRepository(session)
                    await repo.update_graph_fields(
                        world_id=world_id,
                        graph_id=graph_id,
                        graph_status=graph_status,
                    )
        finally:
            await engine.dispose()
