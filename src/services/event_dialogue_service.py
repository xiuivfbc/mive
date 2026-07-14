from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

from fastapi import Request

from src.db.repositories.character_memory_repo import CharacterMemoryRepository
from src.db.repositories.character_repo import CharacterRepository
from src.db.repositories.chat_session_repo import ChatSessionRepository
from src.db.repositories.event_repo import EventRepository
from src.db.repositories.message_repo import MessageRepository
from src.db.repositories.relation_repo import RelationRepository
from src.db.repositories.world_repo import WorldRepository
from src.llm.base import LLMPriority, LLMProvider, get_lang_hint, llm_operation
from src.models.character import Character
from src.models.enums import EventStatus, EventType
from src.models.message import Message
from src.services import stream_control as sc

logger = logging.getLogger(__name__)

# ── 事件专用调试日志（独立文件，不污染 backend.log）────────────────────────
# event_dialogue_service.py 位于 src/services/，需上溯三层到项目根再进 logs/
_LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "logs",
)
event_debug_logger = logging.getLogger("event_debug")
event_debug_logger.setLevel(logging.DEBUG)
event_debug_logger.propagate = False  # 防止冒泡到 root logger（backend.log）
if not event_debug_logger.handlers:
    _evt_handler = logging.FileHandler(
        os.path.join(_LOG_DIR, "event_debug.log"), encoding="utf-8", delay=True
    )
    _evt_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    event_debug_logger.addHandler(_evt_handler)

# ── Constants ──────────────────────────────────────────────────────────────────
MAX_TOTAL_SCENES = 10
RERANK_KEEP_N = 5
RERANK_RECALL_TOP_K = 15
_SEQUENCE_COUNTER_PREFIX = "seq:"
_SEQUENCE_COUNTER_TTL = 86400 * 7  # 7 days

# Display name mapping for non-character sender types
_SENDER_TYPE_DISPLAY_NAMES = {"system": "系统", "narrator": "旁白", "user": "用户"}


def _resolve_sender_name(msg: Message, char_id_map: dict[str, str]) -> str | None:
    """Resolve display name for a message.

    - Character messages: look up sender_id in char_id_map (id -> name)
    - System/narrator/user: use fixed display names
    """
    if msg.sender_type in _SENDER_TYPE_DISPLAY_NAMES:
        return _SENDER_TYPE_DISPLAY_NAMES[msg.sender_type]
    if msg.sender_id and msg.sender_id in char_id_map:
        return char_id_map[msg.sender_id]
    return None


# ── Prompt: 场景规划师 ──────────────────────────────────────────────────────
PLANNER_SYSTEM_PROMPT = """\
你是一个虚拟世界事件规划师。根据注入的事件，判断这个事件会在哪些地点、影响哪些势力/群体，规划出彼此独立的场景序列。

## 规则

1. 场景数量灵活控制在 1-5 个，根据事件复杂度自行判断。不要过度拆分
2. 每个场景代表一个独立的地点或群体，他们会对事件做出反应或被直接卷入
3. **factions** 填写该场景涉及的势力或群体名称（1-2 个）；若难以区分势力则填 ["相关人员"]
4. **goal** 说明这个场景的叙事目的：他们要讨论什么、决定什么，或经历什么（20字以内）
5. **atmosphere** 描述场景的环境氛围（20字以内），用于旁白渲染
6. **event_title** 简短有力，10字以内
7. 不要凑场景数量；若事件只影响一个群体，就只规划一个场景
8. **participants_count** 建议该场景的参与人数（整数，不指定具体角色名）

## 返回 JSON

```json
{
  "event_title": "简短标题",
  "scenes": [
    {
      "scene_id": 1,
      "location": "...",
      "atmosphere": "...",
      "factions": ["势力名称"],
      "goal": "本场景叙事目的",
      "participants_count": 3
    }
  ]
}
```"""


# ── Prompt: 场景选角 + 旁白 ─────────────────────────────────────────────────
SCENE_ORCHESTRATOR_SYSTEM_PROMPT = """\
你是一个虚拟世界场景导演。根据当前事件和场景信息，完成以下任务：

1. 从角色列表中选出参与这个场景的具体角色
2. 生成场景旁白，描述角色如何加入/场景如何展开（允许为空字符串）
3. 如果事件索引中有相关事件，返回该事件 ID
4. 判断是否可以注入上一个场景的摘要（见下方 can_inject 规则）

{world_bg}

## 规则

- 参与者数量参考 **participants_count**，若无则默认 2-4 人
- 优先选择属于场景势力的角色
- **first_speaker** 是最有可能率先开口的角色
- 只能使用角色列表中存在的角色名
- 旁白应自然地引出场景，描述角色到场或场景氛围
- 事件选择：若事件涉及某个已有事件，返回该事件 ID；若不涉及，返回 null

## can_inject 判断规则

如果提供了"上一个场景信息"，你需要判断当前场景是否能获知上一个场景的内容：
- 如果当前场景的参与者中有人在上一个场景中出现过 → **can_inject** 为 true
- 如果当前场景的地点与上一个场景相同 → **can_inject** 为 true
- 其他情况 → **can_inject** 为 false
如果没有提供"上一个场景信息"（第一个场景），**can_inject** 直接为 false。

角色列表：
{char_list_text}

事件索引：
{event_index_text}  （格式：eventId：事件名 - 摘要）

## 返回 JSON

```json
{{
  "participants": ["角色名1", "角色名2"],
  "first_speaker": "角色名1",
  "narration": "场景旁白文本或空字符串",
  "relevant_event": "事件ID或null",
  "can_inject": true或false
}}
```"""


# ── Prompt: 对话摘要员 ──────────────────────────────────────────────────────
SUMMARIZER_SYSTEM_PROMPT = """\
你是一个对话记录员。将以下场景对话总结为简洁的叙事摘要，用于判断后续场景计划是否需要调整。

## 要求

1. 100字以内
2. 聚焦于：做出了什么决定、各方立场、是否有明确的行动意图、透露了什么关键信息
3. 不评价对话质量，只客观描述事实
4. 用第三人称书写

## 返回 JSON

```json
{ "summary": "..." }
```"""


# ── Prompt: 场景修订师（核心） ───────────────────────────────────────────────
REVISER_SYSTEM_PROMPT = """\
你是虚拟世界叙事连贯性审核员。在一个场景对话结束后，判断剩余的场景计划是否需要调整。

## 核心原则：信息壁垒是世界的默认状态

不同地点、不同势力之间，信息严格隔离。一个势力私下讨论的内容，对其他所有势力来说"不存在"。
只有满足以下物理传递机制之一，信息才能跨越壁垒：
  A. 对话中明确派遣了信使/使者前往另一势力
  B. 对话结果产生了可被外部直接观察的行动（军队开拔、公开宣战、公开处决等）
  C. 对话发生在真正公开的场合（城市广场、朝堂大殿、公开宴席），无法防止旁观者获知

## 三种允许修改的情况（需明确满足其一，否则输出 changes: none）

### ① 提前解决

本场景结果已经解决了某后续场景的核心议题，使该场景失去意义。
→ 可移除该后续场景，或将其 **goal** 改为决策执行后的后续行动。
判断标准：只有当后续场景的议题与本场景决策完全重叠时才成立；部分重叠不算。

### ② 信息外溢（极为罕见，必须满足 A/B/C 之一）

本场景结论通过明确物理机制已经或将要传递给另一势力，且改变了该势力的原有行动目标。
→ 可修改受影响势力后续场景的 **goal**，使其反映获知新信息后的状态。
→ 严禁假设"可能察觉"、"也许知道"、"应该能感觉到"——模糊推断不构成信息外溢。
→ 即使本场景气氛紧张、关系剧变，也不构成其他势力知情的依据。

### ③ 同势力跨场景连贯

某势力在本场景做出了重要决策，且计划中该势力在后续场景中还会出现。
→ 可更新该势力后续场景的 **goal**，反映已决定的事（避免重复讨论）。
→ 仅限该势力自身的后续场景，不得波及其他势力的场景。

## 严禁的修改

- ✗ 为增加戏剧效果或故事张力而添加新场景
- ✗ 让一个势力感知另一势力的私下决策（无物理机制支撑）
- ✗ 修改与本场景无直接逻辑联系的后续场景
- ✗ 无具体依据地新增参与者、更换地点或调整氛围
- ✗ **updated_scenes** 中遗漏任何输入中存在的剩余场景

## 输出格式

```json
{
  "changes": "none" 或 "modified",
  "reasoning": "一句话说明判断依据（无修改时说明满足信息壁垒的理由）",
  "updated_scenes": [剩余场景的完整列表，changes 为 none 时与输入完全相同]
}
```"""


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _sse(event: str, data: dict | str) -> str:
    if isinstance(data, dict):
        data = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n"


class EventDialogueService:
    def __init__(
        self,
        llm: LLMProvider,
        character_repo: CharacterRepository,
        message_repo: MessageRepository,
        event_repo: EventRepository,
        world_repo: WorldRepository,
        session_factory,
        memory_repo=None,  # CharacterMemoryRepository，可选避免循环依赖
        redis=None,  # redis.asyncio.Redis，可选，用于角色名缓存
        element_retrieval_service=None,  # ElementRetrievalService，可选
        memory_module=None,  # MemoryModule，可选（向后兼容）
        memory_propagation_service=None,  # MemoryPropagationService，可选（向后兼容）
        memory_orchestrator=None,  # MemoryOrchestrator，可选，统一记忆生命周期
        select_llm=None,  # LLMProvider for location/faction selection (副模型)
        rerank_llm=None,  # LLMProvider for element reranking
        rerank_provider=None,  # RerankProvider | None
    ):
        self.llm = llm
        self.character_repo = character_repo
        self.message_repo = message_repo
        self.event_repo = event_repo
        self.world_repo = world_repo
        self.session_factory = session_factory
        self.memory_repo = memory_repo
        self._redis = redis
        self.element_retrieval_service = element_retrieval_service
        self.memory_orchestrator = memory_orchestrator
        self.select_llm = select_llm or llm
        self.rerank_llm = rerank_llm or llm
        self.rerank_provider = rerank_provider

    async def _next_sequence(self, session_id: str) -> int:
        """Allocate next sequence number (Redis INCR with DB fallback)."""
        if self._redis is not None:
            try:
                key = f"{_SEQUENCE_COUNTER_PREFIX}{session_id}"
                value = await self._redis.incr(key)
                await self._redis.expire(key, _SEQUENCE_COUNTER_TTL)
                return int(value)
            except Exception:
                logger.debug("Redis INCR failed for seq:%s, falling back to DB", session_id)
        max_seq = await self.message_repo.get_max_sequence(session_id)
        return max_seq + 1

    async def stream_dialogue(
        self,
        world_id: str,
        raw_input: str,
        request: Request,
        *,
        session_id: str | None = None,
        memories_enabled: bool = False,
        action_descriptions: bool = False,
        show_narration: bool = False,
        element_rerank: bool = False,
        element_injection_ids: list[str] | None = None,
        constraint: str | None = None,
    ) -> AsyncGenerator[str, None]:
        ctrl = sc.start_stream(world_id)
        try:
            async for chunk in self._stream_dialogue_inner(
                world_id,
                raw_input,
                request,
                ctrl,
                session_id=session_id,
                memories_enabled=memories_enabled,
                action_descriptions=action_descriptions,
                show_narration=show_narration,
                element_rerank=element_rerank,
                element_injection_ids=element_injection_ids,
                constraint=constraint,
            ):
                yield chunk
        finally:
            sc.end_stream(world_id)

    async def _stream_dialogue_inner(
        self,
        world_id: str,
        raw_input: str,
        request: Request,
        ctrl: sc.StreamControl,
        *,
        session_id: str | None = None,
        memories_enabled: bool = False,
        action_descriptions: bool = False,
        show_narration: bool = False,
        element_rerank: bool = False,
        element_injection_ids: list[str] | None = None,
        constraint: str | None = None,
    ) -> AsyncGenerator[str, None]:
        llm_operation.set("事件推演")
        # ── 清理旧消息 ──────────────────────────────────────────────────────
        await self._cleanup_old_messages(world_id)

        # ── 写事件行 ─────────────────────────────────────────────────────────
        session = self.event_repo.session
        event_row = await self.event_repo.create(
            world_id,
            {
                "event_type": EventType.USER_INJECTED,
                "name": raw_input[:50],
                "description": raw_input,
                "status": EventStatus.SCHEDULED,
            },
        )
        await session.commit()

        # ── 加载世界背景和角色 ───────────────────────────────────────────────
        characters = await self.character_repo.list_by_world(world_id, include_extra=False)
        char_names = {c.name for c in characters}
        char_map = {c.name: c for c in characters}
        char_id_map = {c.id: c.name for c in characters}  # id -> name for sender resolution

        world_doc = await self.world_repo.get(world_id)
        lang_hint = get_lang_hint()
        world_bg = ""
        world_elements_ctx = ""
        common_sense = ""
        if world_doc:
            common_sense = getattr(getattr(world_doc, "source", None), "common_sense", None) or ""
            plot_development = (
                getattr(getattr(world_doc, "source", None), "plot_development", None) or ""
            )
            core_conflict = getattr(getattr(world_doc, "source", None), "core_conflict", None) or ""
            tone_and_atmosphere = (
                getattr(getattr(world_doc, "source", None), "tone_and_atmosphere", None) or ""
            )
            world_bg_parts = []
            if common_sense:
                world_bg_parts.append(f"<world_setting>{common_sense}</world_setting>")
            if plot_development:
                world_bg_parts.append(f"<plot_development>{plot_development}</plot_development>")
            if core_conflict:
                world_bg_parts.append(f"<core_conflict>{core_conflict}</core_conflict>")
            if tone_and_atmosphere:
                world_bg_parts.append(
                    f"<tone_and_atmosphere>{tone_and_atmosphere}</tone_and_atmosphere>"
                )
            world_bg = "\n\n".join(world_bg_parts) if world_bg_parts else ""

            # ── 手动元素注入或自动选择 ───────────────────────────────────
            if element_injection_ids:
                # Path D: 手动选择元素注入（事件模式）
                elem_id_map = {e.id: e for e in (getattr(world_doc, "elements", None) or [])}
                detail_parts = []
                used = 0
                for eid in element_injection_ids:
                    elem = elem_id_map.get(eid)
                    if not elem:
                        continue
                    detail_text = elem.detail or elem.brief
                    prefix = f'<element category="{elem.category}" name="{elem.name}">'
                    suffix = "</element>"
                    line = f"{prefix}{detail_text}{suffix}"
                    if used + len(line) > 1200:
                        remaining = 1200 - used - len(prefix) - len(suffix) - 1
                        if remaining > 20:
                            detail_parts.append(f"{prefix}{detail_text[:remaining]}…{suffix}")
                        break
                    detail_parts.append(line)
                    used += len(line)
                world_elements_ctx = "\n".join(detail_parts)
                selected_locs: list = []
                selected_facs: list = []
            else:
                # 自动选择：副模型选择地点/势力
                all_elements = getattr(world_doc, "elements", None) or []
                loc_elements = [e for e in all_elements if "场所" in (e.category or "")]
                fac_elements = [e for e in all_elements if "势力" in (e.category or "")]
                selected_locs, selected_facs = await self._select_locations_and_factions(
                    raw_input, loc_elements, fac_elements, lang_hint
                )

            # Step 3: 副模型选择为空时，用向量检索兜底
            # 手动注入时跳过检索（world_elements_ctx 已在 Path D 填充）
            retrieved = []
            if not element_injection_ids and not selected_locs and not selected_facs:
                if self.element_retrieval_service:
                    try:
                        retrieved = await self.element_retrieval_service.retrieve(
                            world_id=world_id,
                            query=raw_input,
                            top_k=RERANK_RECALL_TOP_K,
                            element_types=["element"],
                        )
                    except Exception:
                        logger.warning("[event_dialogue] retrieval failed", exc_info=True)
                        retrieved = []
                else:
                    retrieved = []

                if retrieved:
                    if element_rerank:
                        retrieved = await self._rerank_elements(raw_input, retrieved)
                    elif self.rerank_provider is not None:
                        try:
                            docs = [f"[{r.category}] {r.name}：{r.brief}" for r in retrieved]
                            rerank_results = await self.rerank_provider.rerank(
                                raw_input, docs, top_n=RERANK_KEEP_N
                            )
                            order_map = {r.index: i for i, r in enumerate(rerank_results)}
                            reranked = [retrieved[i] for i in order_map if i < len(retrieved)]
                            retrieved = (
                                reranked[:RERANK_KEEP_N] if reranked else retrieved[:RERANK_KEEP_N]
                            )
                        except Exception:
                            logger.warning(
                                "[event_dialogue] rerank provider failed, using raw top-K",
                                exc_info=True,
                            )
                            retrieved = retrieved[:RERANK_KEEP_N]
                    else:
                        retrieved = retrieved[:RERANK_KEEP_N]

                if retrieved:
                    # 向量检索返回了结果，格式化为上下文
                    _detail_budget = 1200
                    detail_parts = []
                    used = 0
                    for r in retrieved:
                        line = f"  {r.name}：{r.brief}"
                        if used + len(line) > _detail_budget:
                            remaining = _detail_budget - used
                            if remaining > 20:
                                detail_parts.append(line[:remaining] + "…")
                            break
                        detail_parts.append(line)
                        used += len(line)
                    elements_body = "\n".join(detail_parts)
                    if elements_body:
                        title = getattr(world_doc.source, "title", "") if world_doc.source else ""
                        header = (
                            f"对于给出对话可能有用的世界元素（{title}）："
                            if title
                            else "对于给出对话可能有用的世界元素："
                        )
                        world_elements_ctx = header + "\n" + elements_body
                else:
                    from src.services.element_retrieval_service import retrieve_as_context

                    elements_body = await retrieve_as_context(
                        self.element_retrieval_service,
                        world_id=world_id,
                        query=raw_input,
                        world_doc=world_doc,
                        top_k=12,
                    )
                    if elements_body:
                        title = getattr(world_doc.source, "title", "") if world_doc.source else ""
                        header = (
                            f"对于给出对话可能有用的世界元素（{title}）："
                            if title
                            else "对于给出对话可能有用的世界元素："
                        )
                        world_elements_ctx = header + "\n" + elements_body

            # Step 4: 构建地点/势力上下文 + 其他元素上下文
            if selected_locs or selected_facs:
                _loc_budget = 800
                _fac_budget = 800
                _other_budget = 600
                ctx_parts = []
                if selected_locs:
                    loc_lines = []
                    used = 0
                    for e in selected_locs:
                        content = f"{e.brief}（{e.detail}）" if e.detail else e.brief
                        prefix = f'<element category="{e.category or "场所"}" name="{e.name}">'
                        suffix = "</element>"
                        line = f"{prefix}{content}{suffix}"
                        if used + len(line) > _loc_budget:
                            remaining = _loc_budget - used - len(prefix) - len(suffix) - 1
                            if remaining > 20:
                                loc_lines.append(f"{prefix}{content[:remaining]}…{suffix}")
                            break
                        loc_lines.append(line)
                        used += len(line)
                    ctx_parts.append("事件相关地点：\n" + "\n".join(loc_lines))
                if selected_facs:
                    fac_lines = []
                    used = 0
                    for e in selected_facs:
                        content = f"{e.brief}（{e.detail}）" if e.detail else e.brief
                        prefix = f'<element category="{e.category or "势力"}" name="{e.name}">'
                        suffix = "</element>"
                        line = f"{prefix}{content}{suffix}"
                        if used + len(line) > _fac_budget:
                            remaining = _fac_budget - used - len(prefix) - len(suffix) - 1
                            if remaining > 20:
                                fac_lines.append(f"{prefix}{content[:remaining]}…{suffix}")
                            break
                        fac_lines.append(line)
                        used += len(line)
                    ctx_parts.append("事件相关势力/群体：\n" + "\n".join(fac_lines))

                # 补充：向量检索的其他类型元素（排除已选地点/势力）
                selected_names = {e.name for e in selected_locs} | {e.name for e in selected_facs}
                if retrieved:
                    other_parts = []
                    used = 0
                    for r in retrieved:
                        if r.name in selected_names:
                            continue
                        prefix = f'<element category="{r.category or "其他"}" name="{r.name}">'
                        suffix = "</element>"
                        line = f"{prefix}{r.brief}{suffix}"
                        if used + len(line) > _other_budget:
                            remaining = _other_budget - used - len(prefix) - len(suffix) - 1
                            if remaining > 20:
                                other_parts.append(f"{prefix}{r.brief[:remaining]}…{suffix}")
                            break
                        other_parts.append(line)
                        used += len(line)
                    if other_parts:
                        ctx_parts.append("其他相关元素：\n" + "\n".join(other_parts))

                if ctx_parts:
                    world_elements_ctx = "\n\n".join(ctx_parts)

        char_list_lines = []
        for c in characters:
            profile = c.profile or {}
            brief = profile.get("brief", "暂无")
            char_list_lines.append(f"- {c.name}：{brief}。")
        char_list_text = "\n".join(char_list_lines) or "（暂无角色）"

        # ── PLAN：生成场景计划 ───────────────────────────────────────────────
        planner_user = (
            f"世界观背景：\n{world_bg}\n\n"
            + (f"{world_elements_ctx}\n\n" if world_elements_ctx else "")
            + f"角色列表：\n{char_list_text}\n\n"
            f"注入事件：\n{raw_input}" + (f"\n\n【约束】{constraint}" if constraint else "")
        )

        try:
            plan_result = await self.llm.complete_json(
                PLANNER_SYSTEM_PROMPT + lang_hint, planner_user, priority=LLMPriority.EVENT
            )
        except Exception as e:
            yield _sse("error", {"message": f"planner LLM 调用失败: {e}"})
            return

        event_debug_logger.info(
            "[PLAN] event_title=%s | scenes=%s",
            plan_result.get("event_title", "") if isinstance(plan_result, dict) else "",
            json.dumps(
                plan_result.get("scenes", []) if isinstance(plan_result, dict) else [],
                ensure_ascii=False,
            ),
        )

        if isinstance(plan_result, list) or not plan_result.get("scenes"):
            yield _sse("error", {"message": "planner 未能生成场景计划"})
            return

        event_title: str = plan_result.get("event_title", raw_input[:50])
        pending_scenes: list[dict] = plan_result.get("scenes", [])

        # 用 Planner 输出的标题更新事件记录的 name 字段
        if event_title:
            from sqlalchemy import update as sa_update

            from src.db.models import M3Event

            await session.execute(
                sa_update(M3Event)
                .where(M3Event.id == uuid.UUID(event_row.id))
                .values(name=event_title)
            )
            await session.commit()

        # ── 创建聊天会话 ────────────────────────────────────────────────────
        chat_session_id: str | None = None
        try:
            from src.db.repositories.version_repo import VersionRepository

            chat_session_repo = ChatSessionRepository(session)
            version_repo = VersionRepository(session)
            latest_version = await version_repo.get_latest(world_id)
            current_version_id = latest_version.id if latest_version else None

            # 如果提供了 session_id，验证其存在性并复用
            if session_id:
                existing_session = await chat_session_repo.get_by_id(session_id)
                if existing_session:
                    chat_session_id = session_id
                else:
                    # session_id 无效时创建新 session
                    chat_session = await chat_session_repo.create(
                        world_id, "event", title=event_title, version_id=current_version_id
                    )
                    chat_session_id = str(chat_session.id)
            else:
                chat_session = await chat_session_repo.create(
                    world_id, "event", title=event_title, version_id=current_version_id
                )
                chat_session_id = str(chat_session.id)
        except Exception:
            pass

        # ── 写事件卡片（初始参与者为空，场景执行后才确定）────────────────────
        event_card_content = json.dumps(
            {"title": event_title, "description": raw_input, "participants": []},
            ensure_ascii=False,
        )
        event_seq = None
        if chat_session_id:
            try:
                event_seq = await self._next_sequence(chat_session_id)
            except Exception:
                logger.warning(
                    "_next_sequence failed for event card, session=%s",
                    chat_session_id,
                    exc_info=True,
                )
        event_msg = Message(
            id=str(uuid.uuid4()),
            world_id=world_id,
            session_id=chat_session_id,
            type="event",
            sender_type="system",
            sender_id=None,
            content=event_card_content,
            sequence=event_seq,
        )
        await self.message_repo.create(event_msg)
        await session.commit()

        yield _sse(
            "event_injected",
            {
                "event_id": event_row.id,
                "card_message_id": event_msg.id,
                "title": event_title,
                "description": raw_input,
                "participants": [],
                "card_message_sequence": event_seq,
                "session_id": chat_session_id,
            },
        )

        # ── EXECUTE-REVISE 循环 ──────────────────────────────────────────────
        all_dialogue_messages: list[Message] = []
        all_participants: set[str] = set()
        scene_index = 0

        # 跨场景消息隔离：跟踪上一个场景的摘要信息
        prev_scene_summary: str | None = None
        prev_scene_participants: list[str] = []
        prev_scene_location: str | None = None

        # 加载事件索引（场景选角 prompt 需要）
        event_index_map: dict[str, str] = {}
        event_index_items: list[tuple[str, str, str]] = []  # (id, name, brief)
        if self.memory_repo:
            from src.db.repositories.event_index_repo import EventIndexRepository

            _eir = EventIndexRepository(self.memory_repo.session)
            _eis = await _eir.list_by_world(world_id)
            for e in _eis:
                eid = str(e.id)
                event_index_map[eid] = e.event_name
                event_index_items.append((eid, e.event_name, e.brief or ""))
        # Build event index text with budget to avoid overflow
        _event_index_budget = 1500
        _eidx_parts = []
        _eidx_used = 0
        for eid, ename, brief in event_index_items:
            line = f"{eid}: {ename} - {brief}" if brief else f"{eid}: {ename}"
            if _eidx_used + len(line) > _event_index_budget:
                remaining = _event_index_budget - _eidx_used
                if remaining > 20:
                    _eidx_parts.append(line[:remaining] + "…")
                break
            _eidx_parts.append(line)
            _eidx_used += len(line)
        event_index_text = "\n".join(_eidx_parts) or "（暂无事件索引）"

        while pending_scenes and scene_index < MAX_TOTAL_SCENES:
            if await request.is_disconnected():
                break
            if await ctrl.wait_if_paused():
                break

            scene = pending_scenes.pop(0)
            scene_index += 1

            location: str = scene.get("location", f"场景{scene_index}")
            atmosphere: str = scene.get("atmosphere", "")
            factions: list[str] = scene.get("factions", [])
            goal: str = scene.get("goal") or scene.get("purpose", "")
            participants_count = scene.get("participants_count")

            # ── 选角 + 旁白合并调用 ─────────────────────────────────────────
            orch_system = SCENE_ORCHESTRATOR_SYSTEM_PROMPT.format(
                world_bg=world_bg,
                char_list_text=char_list_text,
                event_index_text=event_index_text,
            )
            orch_user = (
                f"当前场景：\n"
                f"- 地点：{location}\n"
                f"- 涉及势力：{', '.join(factions) if factions else '不限'}\n"
                f"- 场景目的：{goal}\n\n"
                f"当前事件：{raw_input}"
            )
            if participants_count:
                try:
                    count = max(1, min(int(participants_count), 8))
                    orch_user += f"\n\n建议参与人数：{count} 人"
                except (TypeError, ValueError):
                    pass
            # 注入上一个场景信息供 can_inject 判断
            if prev_scene_summary and prev_scene_location:
                orch_user += (
                    f"\n\n上一个场景信息：\n"
                    f"- 地点：{prev_scene_location}\n"
                    f"- 参与者：{', '.join(prev_scene_participants)}\n"
                    f"- 摘要：{prev_scene_summary}"
                )

            try:
                orch_result = await self.llm.complete_json(
                    orch_system + lang_hint,
                    orch_user,
                    priority=LLMPriority.EVENT,
                )
            except Exception as e:
                yield _sse("error", {"message": f"场景选角 LLM 调用失败: {e}"})
                continue

            # can_inject：是否可以注入上一个场景摘要
            can_inject = (
                bool(orch_result.get("can_inject", False))
                if isinstance(orch_result, dict)
                else False
            )

            event_debug_logger.info(
                "[SCENE %d] location=%s | participants=%s | first_speaker=%s "
                "| narration=%s | can_inject=%s",
                scene_index,
                location,
                orch_result.get("participants", []) if isinstance(orch_result, dict) else [],
                orch_result.get("first_speaker", "") if isinstance(orch_result, dict) else "",
                (
                    (orch_result.get("narration") or "" if isinstance(orch_result, dict) else "")[
                        :100
                    ]
                    or "(empty)"
                ),
                can_inject,
            )

            if isinstance(orch_result, list):
                continue

            scene_participants: list[str] = [
                p for p in orch_result.get("participants", []) if p in char_names
            ]
            first_speaker: str | None = orch_result.get("first_speaker")

            if not scene_participants:
                continue
            if not first_speaker or first_speaker not in char_names:
                first_speaker = scene_participants[0]

            all_participants.update(scene_participants)

            # 旁白：从选角结果中取（受 show_narration 开关控制）
            narration_text = orch_result.get("narration") or ""
            if narration_text:
                narr_seq = None
                if chat_session_id:
                    try:
                        narr_seq = await self._next_sequence(chat_session_id)
                    except Exception:
                        logger.warning(
                            "_next_sequence failed for narration, session=%s",
                            chat_session_id,
                            exc_info=True,
                        )
                narrator_msg = Message(
                    id=str(uuid.uuid4()),
                    world_id=world_id,
                    session_id=chat_session_id,
                    type="narration",
                    sender_type="system",
                    sender_id=None,
                    content=narration_text,
                    sequence=narr_seq,
                )
                await self.message_repo.create(narrator_msg)
                await session.commit()

                yield _sse(
                    "narrator_turn",
                    {
                        "id": narrator_msg.id,
                        "content": narration_text,
                        "sequence": narr_seq,
                    },
                )

            # 从选角结果中取 relevant_event（用于对话链注入事件上下文）
            relevant_event_id = orch_result.get("relevant_event") or None
            if not (
                relevant_event_id
                and isinstance(relevant_event_id, str)
                and relevant_event_id in event_index_map
            ):
                relevant_event_id = None

            # ── 对话链（自然结束） ───────────────────────────────────────────
            scene_messages: list[Message] = []
            current_speaker: str | None = first_speaker
            scene_turn = 0
            MAX_TURNS_PER_SCENE = 8  # noqa: N806

            while current_speaker is not None and scene_turn < MAX_TURNS_PER_SCENE:
                if await request.is_disconnected():
                    return
                if await ctrl.wait_if_paused():
                    return

                character = char_map.get(current_speaker)
                if character is None:
                    break

                profile = character.profile or {}
                brief = profile.get("brief", "暂无")
                detailed = profile.get("detail", "暂无")
                from src.utils.memory_format import get_persona_fields

                _persona_tag_map = {"性格特点": "personality", "说话风格": "speech_style"}
                persona_lines = "".join(
                    f"<{_persona_tag_map.get(label, 'trait')}>{value}"
                    f"</{_persona_tag_map.get(label, 'trait')}>\n"
                    for label, value in get_persona_fields(profile)
                )

                # 从新表查短期记忆；长期记忆仅在 relevant_event_id 存在时注入该事件相关记忆
                if self.memory_repo:
                    short_mems = await self.memory_repo.list_short_term(character.id, limit=5)
                    from src.utils.memory_format import (
                        format_short_term_for_injection,
                    )

                    short_text = format_short_term_for_injection(list(short_mems))
                    long_text = ""
                    if relevant_event_id:
                        event_mems = await self.memory_repo.list_by_event_name_for_characters(
                            [character.id], relevant_event_id
                        )
                        if event_mems:
                            from src.utils.memory_format import format_long_term_for_injection

                            long_text = format_long_term_for_injection(
                                event_mems, event_index=event_index_map
                            )
                else:
                    short_text = profile.get("recent_memory", "暂无") or "暂无"
                    long_text = ""

                recent_msgs = await self.message_repo.list_filtered(
                    world_id, session_id=chat_session_id, limit=20
                )
                # 同角色连续发言合并为一条（方案A）
                history_entries: list[tuple[str, str]] = []  # (speaker_name, content)
                for m in reversed(recent_msgs):
                    if m.type not in ("event", "narration"):
                        display_name = _resolve_sender_name(m, char_id_map)
                        if not display_name:
                            continue
                        if history_entries and history_entries[-1][0] == display_name:
                            # 同一角色连续发言，合并内容
                            prev_name, prev_content = history_entries[-1]
                            history_entries[-1] = (prev_name, prev_content + "\n" + m.content)
                        else:
                            history_entries.append((display_name, m.content))
                history_lines = [f"[{name}] {content}" for name, content in history_entries]
                history_text = "\n".join(history_lines) or "（暂无历史）"

                action_rule = (
                    "7. 根据需要在角色 content 中穿插动作/神情描写，"
                    "用 *星号* 包裹，例如：*她放下书抬起头* 啊，你好！；"
                    "不要每轮都强制加，加了要自然\n"
                    if action_descriptions
                    else "7. 不要添加任何动作描写或神情描写（星号格式），只输出对白文本\n"
                )
                event_ctx = ""
                if relevant_event_id and relevant_event_id in event_index_map:
                    event_ctx = f"\n相关事件背景：{event_index_map[relevant_event_id]}\n"
                # 跨场景消息隔离：上一个场景摘要注入
                prev_scene_ctx = ""
                if can_inject and prev_scene_summary:
                    prev_scene_ctx = (
                        f"\n上一个场景摘要（{prev_scene_location}，参与者："
                        f"{', '.join(prev_scene_participants)}）：\n{prev_scene_summary}\n"
                    )
                speaker_system = (
                    f"你正在扮演虚拟世界中的角色 **{current_speaker}**。"
                    "根据当前事件、场景情境和对话历史，"
                    "生成该角色的 1-3 条连贯对话，"
                    "并决定下一个发言的角色。\n\n"
                    f"## 角色资料\n\n"
                    f'<character name="{current_speaker}">\n'
                    f"<brief>{brief}</brief>\n"
                    f"<detail>{detailed or '暂无'}</detail>\n"
                    + persona_lines
                    + f"<short_term_memory>\n{short_text}\n</short_term_memory>\n"
                    + (
                        f"<long_term_memory>\n{long_text}\n</long_term_memory>\n"
                        if long_text
                        else ""
                    )
                    + "</character>\n"
                    + "\n"
                    + (f"{event_ctx}\n" if event_ctx else "")
                    + (f"{prev_scene_ctx}\n" if prev_scene_ctx else "")
                    + (f"{world_elements_ctx}\n\n" if world_elements_ctx else "")
                    + f"**当前场景**：{location}（{atmosphere}）\n"
                    f"**场景目的**：{goal}\n"
                    f"**本场景参与者**：{', '.join(scene_participants)}\n\n"
                    "## 规则\n\n"
                    "1. 对话内容必须符合角色的性格特点、说话风格和当前情境\n"
                    "2. 为该角色生成 1-3 条连贯对话\n"
                    f"3. 所有对话必须以 {current_speaker} 的第一人称视角表达，"
                    "只生成该角色自己的台词\n"
                    f"4. **next_speaker** 从本场景参与者列表中选择"
                    f"（不能是 {current_speaker} 自己），"
                    "或设为 null 表示对话自然结束\n"
                    "5. 不要让同一个角色连续发言超过两次\n"
                    "6. 如果话题已充分讨论或达成结论，"
                    "返回 next_speaker: null\n"
                    f"{action_rule}\n"
                    "## 返回 JSON\n\n"
                    "```json\n"
                    '{"dialogues": ["对白1", "对白2", ...], '
                    '"next_speaker": "下一个发言者" 或 null}\n'
                    "```"
                )
                if history_lines:
                    speaker_user = (
                        f"当前事件：{raw_input}\n\n"
                        "以下是已经发生的对话历史"
                        "（不可重复，必须推进剧情）：\n"
                        f"{history_text}\n\n"
                        f"请以 {current_speaker} 的身份发言，"
                        "接续以上对话推进剧情。决定下一个发言者。"
                        + (f"\n【约束】{constraint}" if constraint else "")
                    )
                else:
                    speaker_user = (
                        f"当前事件：{raw_input}\n\n"
                        f"请以 {current_speaker} 的身份发言，"
                        "从头开始推进剧情。决定下一个发言者。"
                        + (f"\n【约束】{constraint}" if constraint else "")
                    )

                event_debug_logger.debug(
                    "[TURN %d] speaker=%s | system_len=%d | user_len=%d | history_lines=%d",
                    scene_turn,
                    current_speaker,
                    len(speaker_system),
                    len(speaker_user),
                    len(history_lines),
                )

                try:
                    speaker_result = await self._generate_batch_dialogues(
                        speaker_system, speaker_user, lang_hint
                    )
                except Exception as e:
                    yield _sse("error", {"message": f"角色 {current_speaker} LLM 调用失败: {e}"})
                    break

                if isinstance(speaker_result, list):
                    break

                # 解析 dialogues 数组（新格式：字符串数组）
                raw_dialogues = speaker_result.get("dialogues", [])
                next_sp = speaker_result.get("next_speaker")

                # 兼容旧格式：单条 content + next_speaker
                if not raw_dialogues and "content" in speaker_result:
                    raw_dialogues = [speaker_result["content"]]
                    next_sp = next_sp or speaker_result.get("next_speaker")

                # 规范化 dialogues 为字符串列表
                dialogues: list[str] = []
                for d in raw_dialogues:
                    if isinstance(d, str) and d.strip():
                        dialogues.append(d.strip())
                    elif isinstance(d, dict):
                        # 兼容旧格式 {"content": "...", "next_speaker": "..."}
                        c = d.get("content") or ""
                        if c.strip():
                            dialogues.append(c.strip())
                        # 兜底：旧格式 per-dialogue next_speaker（顶层缺失时取最后一个 dict 的值）
                        if not next_sp and d.get("next_speaker"):
                            next_sp = d["next_speaker"]

                if not dialogues:
                    # LLM 错误或空结果，结束当前场景
                    current_speaker = None
                    scene_turn += 1
                    continue

                # 校验 next_speaker
                if next_sp and (next_sp not in char_names or next_sp == current_speaker):
                    next_sp = None

                event_debug_logger.debug(
                    "[TURN %d] dialogues_count=%d | next_speaker=%s",
                    scene_turn,
                    len(dialogues),
                    next_sp,
                )

                # 逐条保存 dialogues
                for content in dialogues:
                    if await request.is_disconnected():
                        return
                    if await ctrl.wait_if_paused():
                        return

                    dlg_seq = None
                    if chat_session_id:
                        try:
                            dlg_seq = await self._next_sequence(chat_session_id)
                        except Exception:
                            logger.warning(
                                "_next_sequence failed for dialogue, session=%s",
                                chat_session_id,
                                exc_info=True,
                            )
                    msg = Message(
                        id=str(uuid.uuid4()),
                        world_id=world_id,
                        session_id=chat_session_id,
                        type="dialogue",
                        sender_type="character",
                        sender_id=character.id,
                        content=content,
                        sequence=dlg_seq,
                    )
                    await self.message_repo.create(msg)
                    await session.commit()
                    scene_messages.append(msg)
                    all_dialogue_messages.append(msg)

                    yield _sse(
                        "speaker_turn",
                        {
                            "id": msg.id,
                            "sender_name": current_speaker,
                            "sender_id": character.id,
                            "content": content,
                            "sequence": dlg_seq,
                        },
                    )

                current_speaker = next_sp

                scene_turn += 1

            # ── 摘要 + REVISE（每 2 个场景 revise 一次） ──────────────────────
            should_revise = (
                pending_scenes
                and scene_messages
                and (scene_index % 2 == 0 or len(pending_scenes) <= 1)
            )
            scene_summary = ""
            if scene_messages:
                dialogue_text = "\n".join(
                    f"[{_resolve_sender_name(m, char_id_map) or m.sender_type}] {m.content}"
                    for m in scene_messages
                )
                summary_user = (
                    f"场景：{location}（{atmosphere}）\n"
                    f"场景目的：{goal}\n"
                    f"参与者：{', '.join(scene_participants)}\n\n"
                    f"对话内容：\n{dialogue_text}"
                )

                try:
                    summary_result = await self.llm.complete_json(
                        SUMMARIZER_SYSTEM_PROMPT + lang_hint,
                        summary_user,
                        priority=LLMPriority.EVENT,
                    )
                    scene_summary = (
                        summary_result.get("summary", "")
                        if isinstance(summary_result, dict)
                        else ""
                    )
                except Exception:
                    scene_summary = ""

                event_debug_logger.info(
                    "[SCENE %d SUMMARY] can_inject_next=%s | summary=%s",
                    scene_index,
                    bool(scene_summary),
                    scene_summary[:100] if scene_summary else "(empty)",
                )

                # 更新跨场景摘要（仅在有摘要时更新）
                if scene_summary:
                    prev_scene_summary = scene_summary

            # 跨场景跟踪：更新上一个场景的位置和参与者（在对话链+摘要完成后）
            prev_scene_location = location
            prev_scene_participants = list(scene_participants)

            if should_revise and scene_summary:
                remaining_json = json.dumps(pending_scenes, ensure_ascii=False)
                revise_user = (
                    f"当前事件：{raw_input}\n\n"
                    f"刚完成的场景：\n"
                    f"- 地点：{location}\n"
                    f"- 参与势力：{', '.join(factions) if factions else '不限'}\n"
                    f"- 场景目的：{goal}\n"
                    f"- 对话摘要：{scene_summary}\n\n"
                    f"剩余待执行场景：\n{remaining_json}\n\n"
                    "请判断剩余场景计划是否需要调整。"
                )

                try:
                    revise_result = await self.llm.complete_json(
                        REVISER_SYSTEM_PROMPT + lang_hint,
                        revise_user,
                        priority=LLMPriority.EVENT,
                    )
                    if isinstance(revise_result, dict):
                        updated = revise_result.get("updated_scenes")
                        if isinstance(updated, list):
                            # 向后兼容：LLM 可能返回 purpose 而非 goal
                            for s in updated:
                                if isinstance(s, dict) and "location" in s:
                                    if "goal" not in s and "purpose" in s:
                                        s["goal"] = s.pop("purpose")
                            valid = [s for s in updated if isinstance(s, dict) and "location" in s]
                            pending_scenes = valid[: MAX_TOTAL_SCENES - scene_index]
                except Exception:
                    pass  # revise 失败不中断流程，继续原计划

        # ── Update session last_active_at ──────────────────────────────
        if chat_session_id:
            try:
                chat_session_repo = ChatSessionRepository(session)
                await chat_session_repo.update_last_active_at(chat_session_id)
                await session.commit()
            except Exception:
                logger.warning("Failed to update last_active_at for session %s", chat_session_id)

        # ── 记忆异步更新 ─────────────────────────────────────────────────────
        yield _sse("memory_updating", {})
        if memories_enabled:
            asyncio.create_task(
                self._update_memories(
                    world_id,
                    list(all_participants),
                    raw_input,
                    all_dialogue_messages,
                    chat_session_id,
                    event_id=str(event_row.id),
                )
            )
        yield _sse("done", {})

    async def _generate_batch_dialogues(
        self, speaker_system: str, speaker_user: str, lang_hint: str
    ) -> dict:
        """调用 LLM 生成批量对话，失败时返回空 dialogues。"""
        event_debug_logger.debug(
            "[LLM_CALL] system_len=%d | user_len=%d\n  system_head=%s\n  user_head=%s",
            len(speaker_system),
            len(speaker_user),
            speaker_system[:300],
            speaker_user[:300],
        )
        try:
            result = await self.llm.complete_json(
                speaker_system + lang_hint, speaker_user, priority=LLMPriority.EVENT
            )
        except Exception:
            return {"dialogues": []}
        if not isinstance(result, dict):
            return {"dialogues": []}
        # 兼容旧格式
        if "dialogues" not in result and "content" in result:
            return {"dialogues": [result]}
        # 校验 dialogues 为 list（LLM 可能返回非预期类型）
        if isinstance(result.get("dialogues"), list):
            return result
        # 有 dialogues key 但值不是 list，退化为空
        if "dialogues" in result:
            return {"dialogues": []}
        return result

    async def _select_locations_and_factions(
        self,
        raw_input: str,
        locations: list,
        factions: list,
        lang_hint: str,
    ) -> tuple[list, list]:
        """Use sub-model to select relevant locations and factions.

        Returns (selected_locations, selected_factions).
        Falls back to returning all input elements on any failure.
        """
        if not locations and not factions:
            return [], []
        try:
            loc_lines = "\n".join(f"- [{e.id}] {e.name}：{e.brief}" for e in locations)
            fac_lines = "\n".join(f"- [{e.id}] {e.name}：{e.brief}" for e in factions)
            parts = []
            if loc_lines:
                parts.append(f"地点列表：\n{loc_lines}")
            if fac_lines:
                parts.append(f"势力列表：\n{fac_lines}")
            options_text = "\n\n".join(parts)

            select_system = (
                "你是一个元素相关性判断助手。根据用户输入的事件文本，从以下列表中"
                "挑选与该事件直接相关的地点和势力。只选择确实会出现在事件中的地点和势力，"
                "不要虚构列表外的名称。\n\n"
                "## 输出 JSON\n\n"
                "```json\n"
                '{"location_ids": ["元素ID"], "faction_ids": ["元素ID"]}\n'
                "```"
            )
            select_user = f"事件文本：{raw_input}\n\n{options_text}"

            result = await self.select_llm.complete_json(
                select_system + lang_hint,
                select_user,
                priority=LLMPriority.EVENT,
            )

            if not isinstance(result, dict):
                logger.warning("[event_dialogue] location/faction selection returned non-dict")
                _max_fb = 8
                return locations[:_max_fb], factions[:_max_fb]

            loc_ids = set(result.get("location_ids") or [])
            fac_ids = set(result.get("faction_ids") or [])

            selected_locs = [e for e in locations if e.id in loc_ids]
            selected_facs = [e for e in factions if e.id in fac_ids]

            # Log unmatched IDs for debugging
            all_loc_ids = {e.id for e in locations}
            all_fac_ids = {e.id for e in factions}
            unmatched_loc = loc_ids - all_loc_ids
            unmatched_fac = fac_ids - all_fac_ids
            if unmatched_loc:
                logger.warning("[event_dialogue] unmatched location_ids: %s", unmatched_loc)
            if unmatched_fac:
                logger.warning("[event_dialogue] unmatched faction_ids: %s", unmatched_fac)

            event_debug_logger.info(
                "[SELECT_LOCS_FACS] locations=%s | factions=%s",
                [e.name for e in selected_locs],
                [e.name for e in selected_facs],
            )

            return selected_locs, selected_facs
        except Exception:
            logger.warning(
                "[event_dialogue] location/faction selection failed, using truncated fallback",
                exc_info=True,
            )
            _max_fallback = 8
            return locations[:_max_fallback], factions[:_max_fallback]

    async def _rerank_elements(
        self, query: str, retrieved: list, keep_n: int = RERANK_KEEP_N
    ) -> list:
        """AI 元素精排（reranker）：把候选（仅 名称+一句话摘要）喂副模型，重排筛选。

        输出包含 high/medium/low 三档相关性，调用方只保留 high+medium。
        失败任何异常 → 返回原始向量结果（沿用现有降级哲学）。
        """
        try:
            candidates_text = "\n".join(f"- {r.name}：{r.brief}" for r in retrieved)
            system_prompt = (
                "你是一个相关性精排器。给定当前事件的语境和一组候选世界元素"
                "（仅名称+摘要），挑出此时最相关的若干个，按相关性从高到低排序。\n\n"
                "## 相关性评级\n\n"
                "对每个相关的元素，给出三档评级：\n"
                "- **high**：元素与当前事件直接相关，是事件的核心话题\n"
                "- **medium**：元素与当前事件有一定关联，但不是核心话题\n"
                "- **low**：与当前事件无关或只有非常弱的关联，不应保留\n\n"
                "低相关的元素不要出现在输出中。\n\n"
                "## 输出格式\n\n"
                '```json\n{"relevant": [{"name": "元素名1", "relevance": "high"}, '
                '{"name": "元素名2", "relevance": "medium"}]}\n```'
            )
            user_prompt = (
                f"事件语境：\n{query}\n\n候选元素：\n{candidates_text}\n\n"
                "请输出相关元素及其相关性评级。"
            )
            result = await self.rerank_llm.complete_json(
                system_prompt, user_prompt, priority=LLMPriority.CHAT
            )
            if isinstance(result, dict):
                items = result.get("relevant") or result.get("elements") or []
            elif isinstance(result, list):
                items = result
            else:
                items = []
            filtered = []
            for item in items:
                if isinstance(item, dict):
                    name = item.get("name")
                    relevance = item.get("relevance", "")
                elif isinstance(item, str):
                    name = item
                    relevance = "high"
                else:
                    continue
                if relevance not in ("high", "medium"):
                    continue
                filtered.append(name)
            if not filtered:
                return retrieved[:keep_n]
            order = {name: i for i, name in enumerate(filtered)}
            picked = [r for r in retrieved if r.name in order]
            if not picked:
                return retrieved[:keep_n]
            picked.sort(key=lambda r: order[r.name])
            return picked[:keep_n]
        except Exception:
            logger.warning(
                "[event_dialogue] element rerank failed, using raw results", exc_info=True
            )
            return retrieved[:keep_n]

    async def _cleanup_old_messages(self, world_id: str) -> None:
        three_days_ago = _utcnow() - timedelta(days=3)
        event_count = await self.event_repo.count_by_world(world_id)

        cutoff_time = three_days_ago
        if event_count > 50:
            cutoff_by_event = await self.event_repo.get_nth_event_time(world_id, n=50)
            if cutoff_by_event and cutoff_by_event > cutoff_time:
                cutoff_time = cutoff_by_event

        await self.message_repo.delete_before_real_time(world_id, cutoff_time)
        await self.event_repo.session.commit()

    async def _update_memories(
        self,
        world_id: str,
        participants: list[str],
        event_description: str,
        dialogue_messages: list[Message],
        session_id: str | None,
        event_id: str | None = None,
    ) -> None:
        sid = uuid.UUID(session_id) if session_id else None

        async with self.session_factory() as session:
            char_repo = CharacterRepository(session)
            memory_repo = CharacterMemoryRepository(session)
            relation_repo = RelationRepository(session)

            # ── Load all participating characters ────────────────────────
            char_map: dict[str, Character] = {}
            char_id_map_mem: dict[str, str] = {}
            for char_name in participants:
                character = await char_repo.find_by_name(world_id, char_name)
                if character:
                    char_map[char_name] = character
                    char_id_map_mem[character.id] = character.name

            if not char_map:
                return

            dialogue_text = "\n".join(
                f"[{_resolve_sender_name(m, char_id_map_mem) or m.sender_type}] {m.content}"
                for m in dialogue_messages
            )

            # ── Generate short-term memories via orchestrator ────────────
            if self.memory_orchestrator is not None:
                # Get embedding provider for memory vector search
                _emb_provider = None
                if self.element_retrieval_service:
                    _emb_provider = self.element_retrieval_service.embedding_provider

                newly_written = await self.memory_orchestrator.generate_short_term_memories(
                    session=session,
                    world_id=world_id,
                    char_map=char_map,
                    dialogue_text=dialogue_text,
                    event_description=event_description,
                    memory_repo=memory_repo,
                    session_id=sid,
                    embedding_provider=_emb_provider,
                )

                # ── Promote long-term memories via orchestrator ──────────
                await self.memory_orchestrator.check_and_promote(
                    session=session,
                    world_id=world_id,
                    char_map=char_map,
                    memory_repo=memory_repo,
                    world_repo=self.world_repo,
                    relation_repo=relation_repo,
                    char_repo=char_repo,
                )
            else:
                newly_written = []

            await session.commit()

        # ── Memory propagation (async, independent session) ──────────────
        if event_id and newly_written and self.memory_orchestrator is not None:
            asyncio.create_task(
                self.memory_orchestrator.dispatch_event_propagation(
                    world_id=world_id,
                    event_id=event_id,
                    participant_names=participants,
                    newly_written_memories=newly_written,
                    virtual_time=_utcnow(),
                )
            )

    async def discard_event(self, event_id: str, message_ids: list[str]) -> None:
        await self.message_repo.delete_by_ids(message_ids)
        await self.event_repo.update_status(event_id, "cancelled")
        await self.event_repo.session.commit()

    async def rewind_to_event(self, world_id: str, card_message_id: str) -> dict:
        session = self.event_repo.session
        chat_session_repo = ChatSessionRepository(session)

        target_msg = await self.message_repo.get_by_id(card_message_id)
        if target_msg is None or target_msg.session_id is None:
            raise ValueError("事件卡片消息不存在")

        target_session = await chat_session_repo.get_by_id(target_msg.session_id)
        if target_session is None:
            raise ValueError("对应的会话不存在")

        later_sessions = await chat_session_repo.list_event_sessions_after(
            world_id, target_session.created_at
        )

        deleted_ids: list[str] = []
        for s in later_sessions:
            msgs = await self.message_repo.list_by_session(s.id)
            deleted_ids.extend(m.id for m in msgs)
            await chat_session_repo.delete(s.id)

        await self.event_repo.cancel_after(world_id, target_session.created_at)
        await session.commit()

        return {
            "deleted_message_ids": deleted_ids,
        }
