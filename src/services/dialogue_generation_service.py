from __future__ import annotations

import logging
import random
import uuid
from typing import TYPE_CHECKING

from src.db.repositories.character_memory_repo import CharacterMemoryRepository
from src.db.repositories.character_repo import CharacterRepository
from src.db.repositories.message_repo import MessageRepository
from src.db.repositories.world_repo import WorldRepository

if TYPE_CHECKING:
    from src.db.repositories.relation_repo import RelationRepository
from src.llm.base import LLMPriority, LLMProvider, get_lang_hint, llm_operation
from src.models.message import Message

if TYPE_CHECKING:
    from src.services.element_retrieval_service import ElementRetrievalService

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
# select_participants 阶段候选元素可见数量
SELECT_PARTICIPANTS_ELEMENT_CAP = 10
# 精排开启时召回候选数量，由副模型重排筛选
RERANK_RECALL_TOP_K = 15
# 精排后保留的元素数量上限（按 high/medium 筛选后截断）
RERANK_KEEP_N = 5
# Path C 兜底截断
ELEMENT_CAP_FALLBACK = 5
INPUT_CAP_FOR_PARTICIPANTS = 15
MAX_SPEAKERS = 5
MAX_RELATED_SAMPLE = 4
ELEMENT_DETAIL_BUDGET = 1200
MAX_BACKGROUND = 8  # 背景角色硬截断上限
MAX_RELEVANT_ELEMENTS = 5  # select_participants 选出的相关元素上限
MAX_RELEVANT_EVENTS = 1  # select_participants 选出的相关事件上限
MAX_RELATIONS_PER_CHAR = 8  # 每角色注入关系描述上限
CHARACTER_RECALL_TOP_K = 3  # 角色召回 top_k

_TIER_PRIORITY = ["core", "supporting", "extra"]

# Display name mapping for non-character sender types
_SENDER_TYPE_DISPLAY_NAMES = {"system": "系统", "narrator": "旁白", "user": "用户"}


_EXPLORER_PERSONA = (
    "你是一位游离于命运之外的时空旅行者，来历不明，却与这个世界有着奇妙的缘分。"
    "世界中的每一位角色都本能地感到，与你倾谈是安全的——他们愿意对你知无不言，真心相待，毫无保留。"
    "你以观察者与参与者的双重身份穿梭其中，带着来自另一个时空的温柔目光。"
)


def _extract_work_info(world_doc) -> str:
    """从 world_doc 提取作品名和作者，返回一行格式化文本。"""
    if not world_doc or not getattr(world_doc, "source", None):
        return ""
    title = getattr(world_doc.source, "title", "") or ""
    author = getattr(world_doc.source, "author", "") or ""
    if not title and not author:
        return ""
    parts = []
    if title:
        parts.append(f"作品：{title}")
    if author:
        parts.append(f"作者：{author}")
    return "，".join(parts)


def _build_elements_context(world_doc) -> str:
    """返回纯元素行列表，不含 header。"""
    if not world_doc or not getattr(world_doc, "elements", None):
        return ""
    non_char = [
        e
        for e in world_doc.elements
        if e.category and "人物" not in e.category and "角色" not in e.category
    ]
    non_char.sort(key=lambda e: e.category)
    non_char = non_char[:SELECT_PARTICIPANTS_ELEMENT_CAP]
    if not non_char:
        return ""
    return "\n".join(f"  [{e.category}] {e.name}：{e.brief}" for e in non_char)


def _build_cacheable_prefix(world_doc, role_label: str) -> str:
    """构建 cacheable_system_prefix，包含作品信息和世界设定（常识）。

    角色列表、元素详情等动态内容由调用方拼入变量部分。
    """
    parts = [f"你是一个虚拟世界的{role_label}。请根据以下信息生成内容。"]
    work_info = _extract_work_info(world_doc)
    if work_info:
        parts.append(work_info)
    common_sense = getattr(getattr(world_doc, "source", None), "common_sense", None)
    if common_sense:
        parts.append(f"## 世界设定\n{common_sense}")
    plot_development = getattr(getattr(world_doc, "source", None), "plot_development", None)
    if plot_development:
        parts.append(f"## 剧情发展\n{plot_development}")
    core_conflict = getattr(getattr(world_doc, "source", None), "core_conflict", None)
    if core_conflict:
        parts.append(f"## 核心冲突\n{core_conflict}")
    tone_and_atmosphere = getattr(getattr(world_doc, "source", None), "tone_and_atmosphere", None)
    if tone_and_atmosphere:
        parts.append(f"## 氛围基调\n{tone_and_atmosphere}")
    return "\n".join(parts)


async def _build_participant_input(
    characters: list,
    selected_char_ids: list[str],
    relation_repo: RelationRepository | None = None,
    world_id: str = "",
) -> list:
    """构建输入给 LLM 的角色列表（包含模式）。

    优先级：用户选定角色 > 关联角色随机抽样 > core > supporting > extra
    """

    char_map = {c.id: c for c in characters}
    selected_set = set(selected_char_ids)

    # 1. 用户选定角色保底（不受 INPUT_CAP 限制）
    result = [char_map[cid] for cid in selected_char_ids if cid in char_map]

    if len(result) >= INPUT_CAP_FOR_PARTICIPANTS:
        return result

    # 2. 查询关联角色
    related_candidates: list = []
    if relation_repo and selected_set:
        try:
            all_relations = await relation_repo.list_by_world(world_id)
            related_ids: set[str] = set()
            for rel in all_relations:
                if str(rel.character_a) in selected_set:
                    related_ids.add(str(rel.character_b))
                elif str(rel.character_b) in selected_set:
                    related_ids.add(str(rel.character_a))
            # 优先取 extra，其次 supporting，跳过 core
            related_chars = [
                char_map[rid]
                for rid in related_ids
                if rid in char_map and rid not in selected_set and char_map[rid].tier != "core"
            ]
            # 按 tier 排序：extra > supporting（优先取低 tier）
            tier_order = {"extra": 0, "supporting": 1}
            related_chars.sort(key=lambda c: tier_order.get(c.tier or "extra", 0))
            # 随机抽样
            random.shuffle(related_chars)
            related_candidates = related_chars[:MAX_RELATED_SAMPLE]
            result_ids = {c.id for c in result}
            related_candidates = [c for c in related_candidates if c.id not in result_ids]
        except Exception:
            pass

    result.extend(related_candidates)

    if len(result) >= INPUT_CAP_FOR_PARTICIPANTS:
        return result[:INPUT_CAP_FOR_PARTICIPANTS]

    # 3. 按 tier 贪心填充
    result_ids = {c.id for c in result}
    remaining = [c for c in characters if c.id not in result_ids]
    for tier in _TIER_PRIORITY:
        tier_chars = [c for c in remaining if (c.tier or "extra") == tier]
        for c in tier_chars:
            if len(result) >= INPUT_CAP_FOR_PARTICIPANTS:
                break
            result.append(c)
        if len(result) >= INPUT_CAP_FOR_PARTICIPANTS:
            break

    return result


class DialogueGenerationService:
    def __init__(
        self,
        llm: LLMProvider,
        character_repo: CharacterRepository,
        message_repo: MessageRepository,
        world_repo: WorldRepository | None = None,
        memory_repo: CharacterMemoryRepository | None = None,
        relation_repo: RelationRepository | None = None,
        element_retrieval_service: ElementRetrievalService | None = None,
        rerank_llm: LLMProvider | None = None,
        select_llm: LLMProvider | None = None,
        rerank_provider=None,  # RerankProvider | None
    ):
        self.llm = llm
        # 选角（判断类调用）走副模型；未注入时回落主模型
        self.select_llm = select_llm or llm
        self.character_repo = character_repo
        self.message_repo = message_repo
        self.world_repo = world_repo
        self.memory_repo = memory_repo
        self.relation_repo = relation_repo
        self.element_retrieval_service = element_retrieval_service
        # 精排用副模型（判断类调用）；未注入时回落主模型
        self.rerank_llm = rerank_llm or llm
        self.rerank_provider = rerank_provider

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
                "你是一个相关性精排器。给定用户当前的对话语境和一组候选世界元素"
                "（仅名称+摘要），挑出此时最相关的若干个，按相关性从高到低排序。\n\n"
                "## 相关性评级\n\n"
                "对每个相关的元素，给出三档评级：\n"
                "- **high**：元素与当前对话直接相关，是对话的核心话题\n"
                "- **medium**：元素与当前对话有一定关联，但不是核心话题\n"
                "- **low**：与当前对话无关或只有非常弱的关联，不应保留\n\n"
                "低相关的元素不要出现在输出中。\n\n"
                "## 输出格式\n\n"
                '```json\n{"relevant": [{"name": "元素名1", "relevance": "high"}, '
                '{"name": "元素名2", "relevance": "medium"}]}\n```'
            )
            user_prompt = (
                f"对话语境：\n{query}\n\n候选元素：\n{candidates_text}\n\n"
                "请输出相关元素及其相关性评级。"
            )
            result = await self.rerank_llm.complete_json(
                system_prompt, user_prompt, priority=LLMPriority.CHAT
            )
            # complete_json 返回 dict | list，两种都处理
            if isinstance(result, dict):
                items = result.get("relevant") or result.get("elements") or []
            elif isinstance(result, list):
                items = result
            else:
                items = []
            # 只保留 high + medium
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
            picked.sort(key=lambda r: order.get(r.name, len(order)))
            return picked[:keep_n]
        except Exception:
            logger.warning(
                "[generate_response] element rerank failed, using raw results", exc_info=True
            )
            return retrieved[:keep_n]

    async def _retrieve_augmented_characters(
        self,
        world_id: str,
        query: str,
        all_characters: list,
    ) -> list:
        """Retrieve relevant characters via vector search, fill remaining slots by tier."""
        if not self.element_retrieval_service:
            return all_characters

        try:
            retrieved = await self.element_retrieval_service.retrieve(
                world_id=world_id,
                query=query,
                top_k=CHARACTER_RECALL_TOP_K,
                element_types=["character"],
            )
            if not retrieved:
                return all_characters

            char_by_name = {c.name: c for c in all_characters}
            selected = []
            selected_ids = set()
            for r in retrieved:
                if r.name in char_by_name and r.name not in selected_ids:
                    selected.append(char_by_name[r.name])
                    selected_ids.add(r.name)

            # Fill remaining slots by tier
            remaining = [c for c in all_characters if c.name not in selected_ids]
            for tier in _TIER_PRIORITY:
                for c in remaining:
                    if (c.tier or "extra") == tier and len(selected) < INPUT_CAP_FOR_PARTICIPANTS:
                        selected.append(c)
                        selected_ids.add(c.name)
                if len(selected) >= INPUT_CAP_FOR_PARTICIPANTS:
                    break

            return selected
        except Exception:
            logger.warning("[select_participants] retrieval failed, using all chars", exc_info=True)
            # Rollback to clear InFailedSQLTransactionError state
            try:
                await self.message_repo.session.rollback()
            except Exception:
                pass
            return all_characters

    async def select_participants(
        self,
        world_id: str,
        user_message: str,
        session_id: str | None = None,
        current_participants: list[dict] | None = None,
        previous_participants: list[dict] | None = None,
        participant_mode: str = "auto",
        show_narration: bool = False,
        event_map: dict[str, str] | None = None,
        user_role: str | None = None,
    ) -> dict:
        """Call 1: 选角 + 旁白 + 选元素 + 选事件。

        返回 {speakers: [{id, name}], background: [str], narration: str,
               relevant_elements: [str], relevant_event: str | None}
        """
        llm_operation.set("角色聊天")
        world_doc = await self.world_repo.get(world_id) if self.world_repo else None
        world_user_char_id = (
            str(world_doc.user_character_id) if world_doc and world_doc.user_character_id else None
        )
        all_characters = await self.character_repo.list_by_world(world_id, include_extra=False)
        # Exclude world user character from NPC list (user_role is not excluded here,
        # as the user's current role should be selectable as a participant)
        characters = [c for c in all_characters if str(c.id) != world_user_char_id]
        char_name_to_id = {c.name: c.id for c in characters}

        # ── edit 模式：跳过 LLM，直接构建 speakers + background ─────────
        if participant_mode == "edit" and current_participants:
            selected_names = {p["name"] for p in current_participants}
            speakers = [
                {"id": str(char_name_to_id[n]), "name": n}
                for n in selected_names
                if n in char_name_to_id
            ]
            # background = 与选定角色有关系的角色（复用关系数据）
            background: list[str] = []
            if self.relation_repo:
                try:
                    selected_ids = {p["id"] for p in current_participants}
                    all_relations = await self.relation_repo.list_by_world(world_id)
                    related_ids: set[str] = set()
                    for rel in all_relations:
                        if str(rel.character_a) in selected_ids:
                            related_ids.add(str(rel.character_b))
                        elif str(rel.character_b) in selected_ids:
                            related_ids.add(str(rel.character_a))
                    char_map_by_id = {str(c.id): c.name for c in characters}
                    for rid in related_ids:
                        if rid not in selected_ids and rid in char_map_by_id:
                            name = char_map_by_id[rid]
                            if name not in selected_names:
                                background.append(name)
                                if len(background) >= MAX_BACKGROUND:
                                    break
                except Exception:
                    pass
            return {
                "speakers": speakers,
                "background": background,
                "narration": "",
                "relevant_elements": [],
                "relevant_event": None,
            }

        # ── include/auto 模式：构建输入角色列表 → LLM 选角 ──────────────

        # 构建输入角色列表
        if participant_mode == "include" and current_participants:
            selected_ids = [p["id"] for p in current_participants]
            input_chars = await _build_participant_input(
                characters=characters,
                selected_char_ids=selected_ids,
                relation_repo=self.relation_repo,
                world_id=world_id,
            )
            input_chars_brief = "\n".join(
                f"- {c.name}: {c.profile.get('brief', '')}" for c in input_chars
            )
        else:
            # Try retrieval-augmented selection
            input_chars = await self._retrieve_augmented_characters(
                world_id, user_message, characters
            )
            input_chars_brief = "\n".join(
                f"- {c.name}: {c.profile.get('brief', '')}" for c in input_chars
            )

        history = await self.message_repo.list_by_session(session_id) if session_id else []
        history = [
            m
            for m in history
            if m.type not in ("event", "narration") and getattr(m, "status", "normal") != "failed"
        ][-20:]
        # Build id->name map for history resolution
        _char_id_to_name = {c.id: c.name for c in characters}

        def _sender_label(msg):
            return _char_id_to_name.get(msg.sender_id, "") or _SENDER_TYPE_DISPLAY_NAMES.get(
                msg.sender_type, msg.sender_type
            )

        history_desc = "\n".join(f"[{_sender_label(msg)}] {msg.content}" for msg in history)

        # ── 构建非事件元素上下文（name + brief，截断防 token 溢出） ────────
        max_element_count = 12
        max_element_ctx_len = 1200
        non_char_elements_ctx = ""
        if world_doc and getattr(world_doc, "elements", None):
            non_char_elems = [
                e
                for e in world_doc.elements
                if e.category and "人物" not in e.category and "角色" not in e.category
            ]
            if non_char_elems:
                non_char_elems = non_char_elems[:max_element_count]
                non_char_elements_ctx = "\n".join(f"- {e.name}：{e.brief}" for e in non_char_elems)
                if len(non_char_elements_ctx) > max_element_ctx_len:
                    non_char_elements_ctx = non_char_elements_ctx[:max_element_ctx_len] + "…"

        # ── 构建事件上下文（event_id -> name + brief） ────────────────────
        events_ctx = ""
        valid_event_ids: set[str] = set()
        if event_map:
            valid_event_ids = set(event_map.keys())
            events_ctx = "\n".join(f"- {eid}：{desc}" for eid, desc in event_map.items())

        cacheable_prefix = _build_cacheable_prefix(world_doc, "对话引擎")

        # ── 规则与输出格式 ─────────────────────────────────────────────────
        rule_num = 2  # 规则 1 = 选角，已在下面硬编码
        element_rule = ""
        element_output = ""
        if non_char_elements_ctx:
            rule_num += 1
            element_rule = (
                f"{rule_num}. 从世界元素中选出与当前对话最相关的"
                f"至多{MAX_RELEVANT_ELEMENTS}个元素（仅在明显相关时选择，不相关则为空列表）\n"
            )
            element_output = ', "relevant_elements": ["元素名1", "元素名2"]'

        event_rule = ""
        event_output = ""
        if events_ctx:
            rule_num += 1
            event_rule = (
                f"{rule_num}. 事件选择规则：\n"
                "  - 若用户问题只涉及单个具体事件，返回该事件 ID\n"
                '  - 若用户问题涉及全局性事件回顾或多事件关联讨论，返回 "all"\n'
                "  - 若不涉及事件，返回 null\n"
            )
            event_output = ', "relevant_event": "事件ID或all或null"'

        rule_num += 1
        output_rule = f"{rule_num}. 输出 JSON 格式\n\n"

        output_format = (
            '```json\n{"speakers": ["角色名A", "角色名B"], "background": ["角色名C"], '
            '"narration": "..."' + element_output + event_output + "}\n```"
        )

        # 用户扮演角色的排除说明
        user_char_exclude_rule = ""
        if world_user_char_id:
            _user_char = next((c for c in all_characters if str(c.id) == world_user_char_id), None)
            _uc_name = _user_char.name if _user_char else "用户"
            user_char_exclude_rule = (
                f"。用户正在扮演角色【{_uc_name}】，"
                "该角色绝对不允许出现在 speakers 或 background 中\n"
            )

        system_prompt = (
            f"\n\n## 候选角色列表\n{input_chars_brief}\n\n"
            + (
                f"## 世界元素列表（名称+摘要）\n{non_char_elements_ctx}\n\n"
                if non_char_elements_ctx
                else ""
            )
            + (f"## 事件列表（ID+摘要）\n{events_ctx}\n\n" if events_ctx else "")
            + "## 规则\n\n"
            "1. 从候选角色列表中选出发言角色（通常 2-4 人），"
            "可选填背景角色（仅在场不发言，通常留空）"
            + (user_char_exclude_rule or "\n")
            + (
                "2. 生成一段场景旁白（可含地点/氛围），允许为空字符串\n"
                if show_narration
                else "2. narration 字段必须为空字符串\n"
            )
            + element_rule
            + event_rule
            + output_rule
            + output_format
            + get_lang_hint()
        )

        user_prompt = (
            f"## 最近对话历史\n{history_desc}\n\n"
            f"用户刚刚说：{user_message}\n\n"
            "请选出参与角色、生成旁白"
            + ("、选出相关元素" if non_char_elements_ctx else "")
            + ("和相关事件" if events_ctx else "")
            + "。"
        )

        # 选角切到副模型（线 A 单点验证）；回退链由 FallbackLLMProvider 内部兜底
        result = await self.select_llm.complete_json(
            system_prompt,
            user_prompt,
            cacheable_system_prefix=cacheable_prefix,
            priority=LLMPriority.CHAT,
        )

        if not isinstance(result, dict):
            result = {}

        # 解析 speakers
        raw_speakers = result.get("speakers", [])
        speakers = [
            {"id": str(char_name_to_id[name]), "name": name}
            for name in raw_speakers
            if name in char_name_to_id and str(char_name_to_id[name]) != world_user_char_id
        ]
        # 确保用户当前扮演的角色一定在参与者列表中
        if user_role:
            user_role_char = next((c for c in all_characters if str(c.id) == user_role), None)
            if user_role_char and not any(s["id"] == user_role for s in speakers):
                speakers.append({"id": user_role, "name": user_role_char.name})
        # 硬截断
        speakers = speakers[:MAX_SPEAKERS]

        # 解析 background（白名单校验 + 硬截断）
        raw_background = result.get("background", [])
        input_names = {c.name for c in input_chars}
        background = [
            name
            for name in raw_background
            if isinstance(name, str)
            and name in input_names
            and name not in {s["name"] for s in speakers}
        ][:MAX_BACKGROUND]

        # 解析 relevant_elements（幻觉过滤：名称必须在输入元素列表中）
        relevant_elements: list[str] = []
        if non_char_elements_ctx:
            valid_elem_names = {
                e.name
                for e in (world_doc.elements if world_doc else [])
                if e.category and "人物" not in e.category and "角色" not in e.category
            }
            raw_elements = result.get("relevant_elements", [])
            if isinstance(raw_elements, list):
                seen_elems: set[str] = set()
                for name in raw_elements:
                    if (
                        isinstance(name, str)
                        and name in valid_elem_names
                        and name not in seen_elems
                    ):
                        relevant_elements.append(name)
                        seen_elems.add(name)
                        if len(relevant_elements) >= MAX_RELEVANT_ELEMENTS:
                            break

        # 解析 relevant_event（幻觉过滤：ID 必须在 event_map 中，或为特殊值 "all"）
        relevant_event: str | None = None
        if event_map and valid_event_ids:
            raw_event = result.get("relevant_event")
            if isinstance(raw_event, str):
                if raw_event == "all":
                    relevant_event = "all"
                elif raw_event in valid_event_ids:
                    relevant_event = raw_event
            elif isinstance(raw_event, list) and raw_event:
                # LLM 可能返回列表，取第一个有效 ID
                for eid in raw_event:
                    if isinstance(eid, str) and eid in valid_event_ids:
                        relevant_event = eid
                        break

        return {
            "speakers": speakers,
            "background": background,
            "narration": result.get("narration", ""),
            "relevant_elements": relevant_elements,
            "relevant_event": relevant_event,
        }

    async def _supplement_context(
        self,
        world_id: str,
        user_message: str,
        session_id: str | None,
        event_map: dict[str, str],
        world_doc,
    ) -> dict:
        """轻量级补充调用：从对话历史中选取相关事件和元素。

        返回 {"relevant_event": str | None, "relevant_elements": list[str]}
        """
        history = await self.message_repo.list_by_session(session_id) if session_id else []
        history = [
            m
            for m in history
            if m.type not in ("event", "narration") and getattr(m, "status", "normal") != "failed"
        ][-20:]
        all_characters = await self.character_repo.list_by_world(world_id, include_extra=False)
        char_id_to_name = {c.id: c.name for c in all_characters}
        _name_map = char_id_to_name
        _display = _SENDER_TYPE_DISPLAY_NAMES

        def _sender_label(msg: Message) -> str:
            return _name_map.get(msg.sender_id or "", "") or _display.get(
                msg.sender_type, msg.sender_type
            )

        history_desc = "\n".join(f"[{_sender_label(msg)}] {msg.content}" for msg in history)

        # Build event context
        events_ctx = ""
        valid_event_ids: set[str] = set()
        if event_map:
            valid_event_ids = set(event_map.keys())
            events_ctx = "\n".join(f"- {eid}：{desc}" for eid, desc in event_map.items())

        # Build element context
        non_char_elements_ctx = ""
        valid_elem_names: set[str] = set()
        if world_doc and getattr(world_doc, "elements", None):
            non_char_elems = [
                e
                for e in world_doc.elements
                if e.category and "人物" not in e.category and "角色" not in e.category
            ]
            if non_char_elems:
                valid_elem_names = {e.name for e in non_char_elems}
                non_char_elements_ctx = "\n".join(f"- {e.name}：{e.brief}" for e in non_char_elems)

        system_prompt = (
            "你是一个上下文分析助手。根据对话历史和用户输入，选出最相关的事件和元素。\n\n"
            + (f"### 事件列表（ID+摘要）\n\n{events_ctx}\n\n" if events_ctx else "")
            + (
                f"### 世界元素列表（名称+摘要）\n\n{non_char_elements_ctx}\n\n"
                if non_char_elements_ctx
                else ""
            )
            + "## 规则\n\n"
            + ("1. 从事件列表中选出至多1个最相关的事件ID，不相关则为null\n" if events_ctx else "")
            + (
                "2. 从世界元素中选出至多3个最相关的元素名，不相关则为空列表\n"
                if non_char_elements_ctx
                else ""
            )
            + "3. 输出 JSON 格式\n\n"
            + "## 输出格式\n\n"
            + '```json\n{"relevant_event": "事件ID或null", "relevant_elements": ["元素名1"]}\n```'
            + get_lang_hint()
        )

        user_prompt = (
            f"## 最近对话历史\n{history_desc}\n\n"
            f"用户刚刚说：{user_message}\n\n"
            "请选出相关事件和元素。"
        )

        result = await self.select_llm.complete_json(
            system_prompt,
            user_prompt,
            priority=LLMPriority.CHAT,
        )

        if not isinstance(result, dict):
            return {"relevant_event": None, "relevant_elements": []}

        # Parse and validate (hallucination filtering)
        relevant_event: str | None = None
        raw_event = result.get("relevant_event")
        if isinstance(raw_event, str) and raw_event in valid_event_ids:
            relevant_event = raw_event
        elif isinstance(raw_event, list) and raw_event:
            for eid in raw_event:
                if isinstance(eid, str) and eid in valid_event_ids:
                    relevant_event = eid
                    break

        relevant_elements: list[str] = []
        raw_elements = result.get("relevant_elements", [])
        if isinstance(raw_elements, list):
            seen: set[str] = set()
            for name in raw_elements:
                if isinstance(name, str) and name in valid_elem_names and name not in seen:
                    relevant_elements.append(name)
                    seen.add(name)
                    if len(relevant_elements) >= MAX_RELEVANT_ELEMENTS:
                        break

        return {"relevant_event": relevant_event, "relevant_elements": relevant_elements}

    async def generate_response(
        self,
        world_id: str,
        user_message: str,
        participants: list[dict] | None = None,
        session_id: str | None = None,
        background: list[str] | None = None,
        relevant_elements: list[str] | None = None,
        relevant_event: str | None = None,
        action_descriptions: bool = False,
        element_rerank: bool = False,
        next_sequence: int | None = None,
        user_role: str | None = None,
        manual_elements: list[str] | None = None,
        constraint: str | None = None,
        _is_retry: bool = False,
    ) -> list[Message]:
        llm_operation.set("角色聊天")
        # 1. 读取世界元素 + 角色列表
        world_doc = await self.world_repo.get(world_id) if self.world_repo else None
        world_user_char_id = (
            str(world_doc.user_character_id) if world_doc and world_doc.user_character_id else None
        )
        all_characters = await self.character_repo.list_by_world(world_id, include_extra=False)
        char_id_to_char = {c.id: c for c in all_characters}
        # Exclude world user character from NPC list (but keep in id→char map for identity lookup)
        characters = [c for c in all_characters if str(c.id) != world_user_char_id]
        char_name_to_id = {c.name: c.id for c in characters}

        # 记录用户扮演的角色ID（用于后续prompt告知LLM不要生成该角色台词）
        # 注意：不从participants中移除该角色，因为角色确实在场
        exclude_role_id = user_role or world_user_char_id
        # 找到用户扮演角色的名字（用于后续从发言列表中排除）
        exclude_role_name = None
        if exclude_role_id:
            exclude_char = next((c for c in all_characters if str(c.id) == exclude_role_id), None)
            exclude_role_name = exclude_char.name if exclude_char else None

        # 参与角色的详细档案（detail + 关系概览）
        participant_names = [p["name"] for p in (participants or [])]
        participant_ids = {p["id"] for p in (participants or [])}
        participant_chars = [
            c for c in characters if str(c.id) in participant_ids or c.name in participant_names
        ]

        # 查询参与角色之间的关系，构建关系概览（两轮：先参与角色间，再填充场外关系）
        _rel_map: dict[str, list[str]] = {}  # char_id -> [关系描述, ...]
        if self.relation_repo and participant_chars:
            try:
                all_relations = await self.relation_repo.list_by_world(world_id)
                p_id_set = {str(c.id) for c in participant_chars}
                _id_to_name = {str(c.id): c.name for c in characters}

                # Round 1: inject relations between participants with per-char cap
                for rel in all_relations:
                    if rel.status != "active":
                        continue
                    a_id, b_id = str(rel.character_a), str(rel.character_b)
                    if a_id not in p_id_set or b_id not in p_id_set:
                        continue
                    rel_type = rel.type or "关联"
                    if rel.direction == "unidirectional":
                        _rel_map.setdefault(a_id, []).append(
                            f"{_id_to_name[a_id]}对{_id_to_name[b_id]}是{rel_type}关系"
                        )
                        _rel_map.setdefault(b_id, []).append(
                            f"{_id_to_name[b_id]}对{_id_to_name[a_id]}是{rel_type}关系"
                        )
                    else:
                        desc = f"{_id_to_name[a_id]}和{_id_to_name[b_id]}是{rel_type}关系"
                        _rel_map.setdefault(a_id, []).append(desc)
                        _rel_map.setdefault(b_id, []).append(desc)

                # Round 2: inject at most 2 off-field relations, only if <=3 participants
                if len(participant_chars) <= 3:
                    max_round2 = 2
                    injected_round2 = 0
                    for rel in all_relations:
                        if injected_round2 >= max_round2:
                            break
                        if rel.status != "active":
                            continue
                        a_id, b_id = str(rel.character_a), str(rel.character_b)
                        a_in, b_in = a_id in p_id_set, b_id in p_id_set
                        if a_in == b_in:
                            continue
                        p_id, other_id = (a_id, b_id) if a_in else (b_id, a_id)
                        rel_type = rel.type or "关联"
                        other_name = _id_to_name.get(other_id, "未知")
                        if rel.direction == "unidirectional":
                            desc = f"{_id_to_name[p_id]}对{other_name}是{rel_type}关系"
                        else:
                            desc = f"{_id_to_name[p_id]}和{other_name}是{rel_type}关系"
                        _rel_map.setdefault(p_id, []).append(desc)
                        injected_round2 += 1
            except Exception:
                logger.warning(
                    "[generate_response] failed to load relations for profiles", exc_info=True
                )

        # Truncate per-char relations to MAX_RELATIONS_PER_CHAR
        for cid in _rel_map:
            if len(_rel_map[cid]) > MAX_RELATIONS_PER_CHAR:
                _rel_map[cid] = _rel_map[cid][:MAX_RELATIONS_PER_CHAR]

        def _format_profile(c) -> str:
            from src.utils.memory_format import get_persona_fields

            detail = c.profile.get("detail", "") or c.profile.get("brief", "")
            lines = [f"## *{c.name}*"]
            lines.append(f"详细: {detail}")
            tag_map = {"性格特点": "性格", "说话风格": "说话风格"}
            for label, value in get_persona_fields(c.profile):
                display_label = tag_map.get(label, label)
                lines.append(f"{display_label}: {value}")
            rels = _rel_map.get(str(c.id))
            if rels:
                lines.append("关系:")
                for r in rels:
                    lines.append(f"* {r}")
            return "\n".join(lines)

        participant_profiles = "\n\n".join(_format_profile(c) for c in participant_chars)

        # 读取参与角色的记忆（短期 + 长期）
        participant_memories = ""
        # V2: load event index for name resolution (with error handling)
        event_index_map: dict[str, str] = {}
        if self.memory_repo and participant_chars:
            from src.utils.memory_format import format_short_term_for_injection

            try:
                from src.db.repositories.event_index_repo import EventIndexRepository

                ei_repo = EventIndexRepository(self.memory_repo.session)
                ei_entries = await ei_repo.list_by_world(uuid.UUID(world_id))
                event_index_map = {str(e.id): e.event_name for e in ei_entries}
            except Exception:
                pass  # 降级：不解析事件名

            # Get embedding provider for vector search (graceful fallback if unavailable)
            embedding_provider = None
            if self.element_retrieval_service:
                embedding_provider = self.element_retrieval_service.embedding_provider

            # Pre-compute query embedding once for all characters
            query_embedding: list[float] | None = None
            if embedding_provider is not None:
                try:
                    embeddings = await embedding_provider.embed([user_message])
                    if embeddings:
                        query_embedding = embeddings[0]
                except Exception:
                    logger.debug("Failed to embed user_message for memory search")

            memory_parts = []
            for c in participant_chars:
                try:
                    # ── Short-term: vector search + recent force-inject ──
                    force_recent_count = 2
                    c_uuid = uuid.UUID(c.id)
                    recent_mems = await self.memory_repo.list_short_term(
                        c_uuid, limit=force_recent_count
                    )
                    recent_ids = {m.id for m in recent_mems}

                    short_mems_list: list = list(recent_mems)
                    if query_embedding is not None:
                        try:
                            vec_mems = await self.memory_repo.search_short_term_by_vector(
                                c_uuid, query_embedding, limit=5
                            )
                            for m in vec_mems:
                                if m.id not in recent_ids:
                                    short_mems_list.append(m)
                                    recent_ids.add(m.id)
                        except Exception:
                            logger.debug("Vector search failed for %s, using recent only", c.name)

                    # Fallback: if vector search yielded nothing extra, top up from recent
                    if len(short_mems_list) <= force_recent_count:
                        fallback_mems = await self.memory_repo.list_short_term(c_uuid, limit=5)
                        for m in fallback_mems:
                            if m.id not in recent_ids:
                                short_mems_list.append(m)
                                recent_ids.add(m.id)

                    # Cap at 5 total: recent items first (time-ordered),
                    # then vector/fallback results (relevance-ordered)
                    short_mems_list = short_mems_list[:5]

                    short_text = format_short_term_for_injection(list(short_mems_list))
                    # 短期记忆统一注入；长期记忆不再全量加载，
                    # 仅当 relevant_event 为具体事件 ID 时由下方事件专属注入逻辑处理
                    memory_parts.append(
                        f'<memory_group character="{c.name}">\n{short_text}\n</memory_group>'
                    )
                except Exception:
                    logger.warning("Failed to load memories for character %s, skipping", c.name)
            participant_memories = "\n".join(memory_parts)

        # 事件相关长期记忆注入（当 relevant_event 为具体事件 ID 时）
        event_memories_ctx = ""
        if relevant_event and relevant_event != "all" and self.memory_repo and participant_chars:
            try:
                p_ids = [uuid.UUID(c.id) for c in participant_chars]
                event_mems = await self.memory_repo.list_by_event_name_for_characters(
                    p_ids, relevant_event
                )
                if event_mems:
                    # Resolve event display name
                    event_display = relevant_event
                    if event_index_map and relevant_event in event_index_map:
                        event_display = event_index_map[relevant_event]
                    mem_lines = []
                    for m in event_mems:
                        char = next((c for c in participant_chars if c.id == m.character_id), None)
                        char_name = char.name if char else "未知"
                        content_parts = []
                        if isinstance(m.perspective_detail, str) and m.perspective_detail:
                            content_parts.append(m.perspective_detail)
                        if isinstance(m.reflection, str) and m.reflection:
                            content_parts.append(f"感悟：{m.reflection}")
                        mem_lines.append(
                            f'<memory type="long_term" character="{char_name}">'
                            f"{' '.join(content_parts)}</memory>"
                        )
                    if mem_lines:
                        event_memories_ctx = f"事件「{event_display}」的相关记忆：\n" + "\n".join(
                            mem_lines
                        )
            except Exception:
                logger.debug("Failed to load event-specific memories for %s", relevant_event)

        # 全量事件列表注入（relevant_event="all" 时）
        all_events_ctx = ""
        if relevant_event == "all":
            try:
                from src.db.repositories.event_index_repo import (
                    EventIndexRepository,
                )
                from src.utils.memory_format import format_event_index_for_injection

                session = (
                    self.memory_repo.session if self.memory_repo else self.message_repo.session
                )
                ei_repo = EventIndexRepository(session)
                ei_entries = await ei_repo.list_by_world(uuid.UUID(world_id))
                if ei_entries:
                    all_events_ctx = format_event_index_for_injection(ei_entries)
            except Exception:
                logger.debug("Failed to load full event list for 'all' mode")

        # 背景板角色
        background_profiles = ""
        if background:
            bg_chars = [c for c in characters if c.name in set(background)]
            if bg_chars:
                background_profiles = "\n".join(
                    f"- {c.name}（{c.profile.get('brief', '')}），在场但不参与对话"
                    for c in bg_chars
                )

        # 2. 读取当前 session 的消息历史（隔离上下文，排除 event 卡片）
        history = await self.message_repo.list_by_session(session_id) if session_id else []
        history = [
            m for m in history if m.type != "event" and getattr(m, "status", "normal") != "failed"
        ][-20:]
        _char_id_to_name = {c.id: c.name for c in characters}

        def _sender_label(msg):
            return _char_id_to_name.get(msg.sender_id, "") or _SENDER_TYPE_DISPLAY_NAMES.get(
                msg.sender_type, msg.sender_type
            )

        history_desc = "\n".join(f"[{_sender_label(msg)}] {msg.content}" for msg in history)

        # 元素详细介绍（Step 6） — retrieval-augmented
        elements_detail_ctx = ""

        # Path D: manual element injection — skip LLM selection entirely
        if manual_elements:
            element_map = {e.name: e for e in (world_doc.elements or [])}
            detail_parts = []
            used = 0
            for eid in manual_elements:
                elem = element_map.get(eid)
                if not elem:
                    continue
                detail_text = elem.detail or elem.brief
                prefix = f'<element category="{elem.category}" name="{elem.name}">'
                suffix = "</element>"
                line = f"{prefix}{detail_text}{suffix}"
                if used + len(line) > ELEMENT_DETAIL_BUDGET:
                    remaining = ELEMENT_DETAIL_BUDGET - used - len(prefix) - len(suffix) - 1
                    if remaining > 20:
                        detail_parts.append(f"{prefix}{detail_text[:remaining]}…{suffix}")
                    break
                detail_parts.append(line)
                used += len(line)
            elements_detail_ctx = "\n".join(detail_parts)
        elif relevant_elements and world_doc:
            element_map = {e.name: e for e in (world_doc.elements or [])}
            detail_parts = []
            used = 0
            for name in relevant_elements:
                elem = element_map.get(name)
                if not elem:
                    continue
                detail_text = elem.detail or elem.brief
                prefix = f'<element category="{elem.category}" name="{elem.name}">'
                suffix = "</element>"
                line = f"{prefix}{detail_text}{suffix}"
                if used + len(line) > ELEMENT_DETAIL_BUDGET:
                    remaining = ELEMENT_DETAIL_BUDGET - used - len(prefix) - len(suffix) - 1
                    if remaining > 20:
                        detail_parts.append(f"{prefix}{detail_text[:remaining]}…{suffix}")
                    break
                detail_parts.append(line)
                used += len(line)
            elements_detail_ctx = "\n".join(detail_parts)

        # Retrieval-augmented: replace hard-capped elements with retrieved ones
        if self.element_retrieval_service and not elements_detail_ctx:
            try:
                # Build context from recent messages for better retrieval
                recent_ctx = "\n".join(
                    m.content for m in history[-3:] if m.type not in ("event", "narration")
                )
                context_query = f"{user_message}\n{recent_ctx}".strip()
                if context_query:
                    # 精排开启时放宽召回，再由副模型重排筛选；否则按原 cap 召回
                    recall_k = RERANK_RECALL_TOP_K if element_rerank else ELEMENT_CAP_FALLBACK
                    retrieved = await self.element_retrieval_service.retrieve(
                        world_id=world_id,
                        query=context_query,
                        top_k=recall_k,
                        element_types=["element"],
                    )
                    if retrieved and element_rerank:
                        # Try AI rerank first
                        try:
                            retrieved = await self._rerank_elements(context_query, retrieved)
                        except Exception:
                            pass
                        # Fall back to model-based rerank if rerank_provider is available
                        if self.rerank_provider and element_rerank:
                            try:
                                doc_texts = [r.brief for r in retrieved]
                                rerank_results = await self.rerank_provider.rerank(
                                    context_query, doc_texts, top_n=RERANK_KEEP_N
                                )
                                if rerank_results:
                                    retrieved = [
                                        retrieved[r.index]
                                        for r in rerank_results
                                        if r.index < len(retrieved)
                                    ][:RERANK_KEEP_N]
                            except Exception:
                                pass
                    if retrieved:
                        detail_parts = []
                        used = 0
                        for r in retrieved:
                            line = f"  {r.name}：{r.brief}"
                            if used + len(line) > ELEMENT_DETAIL_BUDGET:
                                remaining = ELEMENT_DETAIL_BUDGET - used
                                if remaining > 20:
                                    detail_parts.append(line[:remaining] + "…")
                                break
                            detail_parts.append(line)
                            used += len(line)
                        elements_detail_ctx = "\n".join(detail_parts)
            except Exception:
                logger.warning(
                    "[generate_response] retrieval failed, using empty elements",
                    exc_info=True,
                )

        # 兜底：无检索服务（或检索为空）且仍未注入任何元素时，按硬截断全量注入世界元素。
        # select_participants 已不再选元素，若无此兜底，未配 embedding 的部署聊天会完全
        # 丢失世界元素上下文——此处沿用 CLAUDE.md「检索不可用降级为全量加载」的既定哲学。
        if not elements_detail_ctx and world_doc and world_doc.elements:
            detail_parts = []
            used = 0
            # 排除角色类元素（与向量检索 element_types=["element"] 的过滤口径一致）
            non_char_elems = [
                e
                for e in world_doc.elements
                if not (e.category and ("人物" in e.category or "角色" in e.category))
            ]
            for elem in non_char_elems[:SELECT_PARTICIPANTS_ELEMENT_CAP]:
                detail_text = elem.detail or elem.brief
                prefix = f'<element category="{elem.category}" name="{elem.name}">'
                suffix = "</element>"
                line = f"{prefix}{detail_text}{suffix}"
                if used + len(line) > ELEMENT_DETAIL_BUDGET:
                    remaining = ELEMENT_DETAIL_BUDGET - used - len(prefix) - len(suffix) - 1
                    if remaining > 20:
                        detail_parts.append(f"{prefix}{detail_text[:remaining]}…{suffix}")
                    break
                detail_parts.append(line)
                used += len(line)
            elements_detail_ctx = "\n".join(detail_parts)

        # 3. 构建 prompt 并调用 LLM
        # 从发言角色中排除用户扮演的角色（该角色由用户发言，AI不应生成其台词）
        ai_speaker_names = [n for n in participant_names if n != exclude_role_name]
        if ai_speaker_names:
            names = ", ".join(ai_speaker_names)
            target_rule = (
                f"1. **强制**：本轮只允许以下角色发言：{names}。其他角色不得出现在输出中。\n"
            )
        elif participant_names:
            # 所有参与者都是用户扮演的角色，让LLM根据上下文决定
            target_rule = "1. 根据对话上下文决定哪些角色会回应，不要让所有角色都说话\n"
        else:
            target_rule = "1. 根据对话上下文决定哪些角色会回应，不要让所有角色都说话\n"
        other_rules_start = 2

        user_identity_rule = (
            f"{other_rules_start}. 对话中存在一位用户参与者："
            f"若其身份为时空旅行者，{_EXPLORER_PERSONA}"
            "不要让角色过度提及时空等元概念，自然交谈即可\n"
        )

        # 全量角色名+brief
        chars_brief = "\n".join(f"- {c.name}: {c.profile.get('brief', '')}" for c in characters)
        cacheable_prefix = _build_cacheable_prefix(world_doc, "对话引擎")

        # 上下文补充指令（仅首次调用时注入，重试时跳过）
        need_more_ctx_instruction = ""
        if not _is_retry:
            need_more_ctx_instruction = (
                "## 上下文补充机制\n\n"
                "- 如果当前上下文中完全没有用户输入中提到的具体事件，"
                '返回 `{"need_more_context": "yes"}`\n'
                "- 如果用户问题涉及全局性事件回顾或多事件关联讨论，"
                '返回 `{"need_more_context": "all"}`\n'
                "- 否则不需要返回此字段\n"
                "- **注意**：返回 need_more_context 时不要同时输出 messages 字段\n\n"
            )

        system_prompt = (
            f"\n\n## 候选角色列表\n{chars_brief}\n\n"
            + (f"## 相关元素详细信息\n{elements_detail_ctx}\n\n" if elements_detail_ctx else "")
            + (f"## 参与角色详细档案\n{participant_profiles}\n\n" if participant_profiles else "")
            + (f"## 参与角色记忆\n{participant_memories}\n\n" if participant_memories else "")
            + (f"## 事件相关记忆\n{event_memories_ctx}\n\n" if event_memories_ctx else "")
            + (f"## 已有事件列表\n{all_events_ctx}\n\n" if all_events_ctx else "")
            + (
                f"## 背景板角色（在场但不发言）\n{background_profiles}\n\n"
                if background_profiles
                else ""
            )
            + need_more_ctx_instruction
            + "## 规则\n\n"
            + target_rule
            + user_identity_rule
            + f"{other_rules_start + 1}. 严格按照角色档案中的性格和说话风格生成对话\n"
            + (
                f"{other_rules_start + 2}. 根据需要在角色 content 中穿插动作/神情描写，用 *星号* 包裹，例如：*她放下书抬起头* 啊，你好！；不要每轮都强制加，加了要自然\n"  # noqa: E501
                if action_descriptions
                else f"{other_rules_start + 2}. 不要添加任何动作描写或神情描写（星号格式），只输出对白文本\n"  # noqa: E501
            )
            + f"{other_rules_start + 3}. 时间由系统自动分配，你不需要输出时间字段\n"
            + f"{other_rules_start + 4}. 输出 JSON 格式\n"
            + f"{other_rules_start + 5}. **关键**：所有字符串值必须用英文双引号包裹，"
            "包括 content 字段。例如正确格式："
            '`"content": "*她笑了* 你好呀"`，'
            '错误格式：`"content": *她笑了* 你好呀`\n\n'
            "## 输出格式（正常回复）\n\n"
            "```json\n"
            "{\n"
            '  "messages": [\n'
            "    {\n"
            '      "type": "dialogue",\n'
            '      "sender_type": "character",\n'
            '      "sender_name": "角色名",\n'
            '      "content": "*动作描写* 对白内容（动作用*包裹，对白直接写）"\n'
            "    }\n"
            "  ]\n"
            "}\n```" + get_lang_hint()
        )

        # 用户扮演角色的身份说明：优先使用 user_role（当前扮演），
        # 否则用 world_user_char_id（世界默认）
        effective_user_role = user_role or world_user_char_id
        if effective_user_role:
            user_char = char_id_to_char.get(effective_user_role)
            name = user_char.name if user_char else "用户"
            user_identity_ctx = (
                f"当前用户身份：扮演角色【{name}】"
                "（来自这个世界之外，以自己身份参与），"
                "不要生成该角色的台词\n\n"
            )
        else:
            user_identity_ctx = "当前用户身份：时空旅行者\n\n"

        user_prompt = (
            user_identity_ctx + f"## 最近对话历史\n{history_desc}\n\n"
            f"用户刚刚说：\n{user_message}\n\n"
            "请生成回复。"
            + (f"\n\n【约束】{constraint}" if constraint else "")
        )

        result = await self.llm.complete_json(
            system_prompt,
            user_prompt,
            cacheable_system_prefix=cacheable_prefix,
            priority=LLMPriority.CHAT,
        )

        logger.info(
            "[generate_response] LLM result type=%s, keys=%s, session=%s, is_retry=%s",
            type(result).__name__,
            list(result.keys())
            if isinstance(result, dict)
            else f"list(len={len(result)})"
            if isinstance(result, list)
            else "N/A",
            session_id,
            _is_retry,
        )

        # ── 上下文补充机制：检测 need_more_context ──────────────────────
        nmc_value = None
        if not _is_retry and isinstance(result, dict):
            nmc_raw = result.get("need_more_context")
            if nmc_raw is True:
                nmc_value = "yes"  # 向后兼容旧布尔值
            elif nmc_raw == "yes":
                nmc_value = "yes"
            elif nmc_raw == "all":
                nmc_value = "all"
            if nmc_value:
                logger.info(
                    "[generate_response] need_more_context=%s detected, session=%s",
                    nmc_value,
                    session_id,
                )

        if nmc_value == "all":
            logger.info(
                "[generate_response] LLM requested all events context, injecting full event list"
            )
            return await self.generate_response(
                world_id=world_id,
                user_message=user_message,
                participants=participants,
                session_id=session_id,
                background=background,
                relevant_elements=relevant_elements,
                relevant_event="all",
                action_descriptions=action_descriptions,
                element_rerank=element_rerank,
                next_sequence=next_sequence,
                _is_retry=True,
            )

        if nmc_value == "yes":
            logger.info(
                "[generate_response] LLM requested more context, triggering supplement call"
            )
            # 加载事件索引用于补充调用
            event_map: dict[str, str] = {}
            try:
                from src.db.repositories.event_index_repo import EventIndexRepository

                session = (
                    self.memory_repo.session if self.memory_repo else self.message_repo.session
                )
                ei_repo = EventIndexRepository(session)
                ei_entries = await ei_repo.list_by_world(uuid.UUID(world_id))
                event_map = {str(e.id): f"{e.event_name}：{e.brief}" for e in ei_entries}
            except Exception:
                pass

            try:
                supplement = await self._supplement_context(
                    world_id=world_id,
                    user_message=user_message,
                    session_id=session_id,
                    event_map=event_map,
                    world_doc=world_doc,
                )
                new_event = supplement.get("relevant_event")
                new_elements = supplement.get("relevant_elements") or []
                if new_event or new_elements:
                    logger.info(
                        "[generate_response] supplement found: event=%s, elements=%s",
                        new_event,
                        new_elements,
                    )
                    # 合并：补充的元素追加到已有列表（去重）
                    merged_elements = list(relevant_elements or [])
                    for elem_name in new_elements:
                        if elem_name not in merged_elements:
                            merged_elements.append(elem_name)
                    # 补充的事件覆盖（如果原来没有）
                    merged_event = relevant_event or new_event
                    # 重试，标记 _is_retry=True 防止循环
                    return await self.generate_response(
                        world_id=world_id,
                        user_message=user_message,
                        participants=participants,
                        session_id=session_id,
                        background=background,
                        relevant_elements=merged_elements,
                        relevant_event=merged_event,
                        action_descriptions=action_descriptions,
                        element_rerank=element_rerank,
                        next_sequence=next_sequence,
                        _is_retry=True,
                    )
                else:
                    # 补充未找到新上下文，但仍需重试（原始 result 无 messages）
                    logger.info(
                        "[generate_response] supplement found nothing, "
                        "retrying LLM with original context"
                    )
                    return await self.generate_response(
                        world_id=world_id,
                        user_message=user_message,
                        participants=participants,
                        session_id=session_id,
                        background=background,
                        relevant_elements=relevant_elements,
                        relevant_event=relevant_event,
                        action_descriptions=action_descriptions,
                        element_rerank=element_rerank,
                        next_sequence=next_sequence,
                        _is_retry=True,
                    )
            except Exception:
                logger.warning(
                    "[generate_response] supplement call failed, retrying LLM without supplement",
                    exc_info=True,
                )
                # 补充失败：原始 result 含 need_more_context 无 messages，必须重新调用 LLM
                return await self.generate_response(
                    world_id=world_id,
                    user_message=user_message,
                    participants=participants,
                    session_id=session_id,
                    background=background,
                    relevant_elements=relevant_elements,
                    relevant_event=relevant_event,
                    action_descriptions=action_descriptions,
                    element_rerank=element_rerank,
                    next_sequence=next_sequence,
                    _is_retry=True,
                )

        # 4. 解析 LLM 响应为 Message 列表
        if isinstance(result, list):
            raw_messages = result
        elif isinstance(result, dict):
            raw_messages = result.get("messages", [])
        else:
            raw_messages = []

        logger.info(
            "[generate_response] parsed raw_messages count=%d, known chars=%s, session=%s",
            len(raw_messages),
            list(char_name_to_id.keys()),
            session_id,
        )

        responses: list[Message] = []
        skipped_count = 0
        # sequence 从 next_sequence 开始递增（None 时默认从 1 开始）
        seq_counter = next_sequence if next_sequence is not None else 1

        for i, raw in enumerate(raw_messages):
            if not isinstance(raw, dict):
                skipped_count += 1
                continue
            sender_name = raw.get("sender_name", "")
            sender_type = raw.get("sender_type", "character")
            msg_type = raw.get("type", "dialogue")

            # 角色消息需要匹配到已有角色
            sender_id = None
            if sender_type == "character":
                if sender_name not in char_name_to_id:
                    skipped_count += 1
                    logger.warning(
                        "[dialogue] skipping message %d: sender_name=%r not in known chars %s",
                        i,
                        sender_name,
                        list(char_name_to_id.keys()),
                    )
                    continue
                sender_id = char_name_to_id[sender_name]

            # 分配 sequence
            msg_seq = seq_counter
            seq_counter += 1

            responses.append(
                Message(
                    id=str(uuid.uuid4()),
                    world_id=world_id,
                    session_id=session_id,
                    type=msg_type,
                    sender_type=sender_type,
                    sender_id=sender_id,
                    content=raw.get("content") or "",
                    user_participated=False,
                    sequence=msg_seq,
                )
            )

        logger.info(
            "[generate_response] final: %d responses, %d skipped, session=%s",
            len(responses),
            skipped_count,
            session_id,
        )

        # 5. 写入回复消息
        await self.message_repo.create_batch(responses)

        # 时钟推进由调用方（MessageService）负责
        return responses
