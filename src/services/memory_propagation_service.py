"""Memory Propagation Service — memory-to-relation bidirectional channel.

Handles:
- Event path: propagate hearsay after event memories are written
- Chat path: propagate hearsay after chat memories are flushed
- Relation evaluation: check accumulated memories for relationship updates
"""

from __future__ import annotations

import logging
import os
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.db.repositories.character_memory_repo import CharacterMemoryRepository
from src.db.repositories.character_repo import CharacterRepository
from src.db.repositories.event_index_repo import EventIndexRepository
from src.db.repositories.relation_repo import RelationRepository
from src.db.repositories.world_repo import WorldRepository
from src.utils.character_name_cache import get_character_names

if TYPE_CHECKING:
    from src.llm.base import LLMProvider

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# Propagation budget (max propagations per event)
PROPAGATION_BUDGET: dict[str, int] = {
    "standard": 4,
    "detailed": 8,
    "deep": 12,
    "all": 16,
}

# Chat propagation budget (smaller, independent of event path)
CHAT_PROPAGATION_BUDGET: dict[str, int] = {
    "standard": 2,
    "detailed": 3,
    "deep": 4,
    "all": 5,
}

# Severity threshold per scale (event path only)
PROPAGATION_SEVERITY_THRESHOLD: dict[str, str] = {
    "standard": "high",
    "detailed": "medium",
    "deep": "medium",
    "all": "medium",
}

# Relation evaluation thresholds
RELATION_EVAL_MIN_MEMORIES = 5
RELATION_EVAL_MIN_UNIQUE_EVENTS = 3
RELATION_EVAL_COOLDOWN_DAYS = 7
MAX_RELATION_EVAL_PER_PROPAGATION = 3

# Propagation delay by relation weight (virtual time)
PROPAGATION_DELAY: dict[int, timedelta] = {
    3: timedelta(hours=1),  # family/lover
    2: timedelta(hours=4),  # friend/colleague
    1: timedelta(hours=12),  # acquaintance
    0: timedelta(days=1),  # other
}

# Severity order for comparison
_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# ── Event Element Constants ──────────────────────────────────────────────────

# Base delay days per world scale (dissemination=1 → delay=0)
EVENT_NEWS_BASE_DELAY: dict[str, int] = {
    "standard": 1,
    "detailed": 2,
    "deep": 3,
    "all": 3,
}


# ── Multi-hop Hearsay Constants ─────────────────────────────────────────────

# Max propagation hop count
MAX_HOP_COUNT = 2

# Parameter 1: will they tell? (probability by relation weight)
HEARSAY_SPREAD_PROBABILITY: dict[int, float] = {
    3: 0.8,  # family/lover
    2: 0.6,  # friend/colleague
    1: 0.4,  # acquaintance
    0: 0.2,  # other
}

# Parameter 2: relation coefficient (base info retention, hop-1 only)
HEARSAY_RELATION_COEFF: dict[int, float] = {
    3: 0.95,  # family/lover: nearly complete
    2: 0.8,  # friend/colleague: retain most
    1: 0.65,  # acquaintance: core only
    0: 0.5,  # other: minimum propagable
}

# Parameter 3: random retention range (both hops)
HEARSAY_RETENTION_RANGE: dict[int, tuple[float, float]] = {
    3: (0.75, 0.9),
    2: (0.65, 0.85),
    1: (0.6, 0.75),
    0: (0.6, 0.7),
}

# Info amount threshold — stop propagation below this
HEARSAY_INFO_THRESHOLD = 0.5

# Source authority coefficient
AUTHORITY_COEFFICIENT: dict[str, float] = {
    "official": 1.0,
    "folk_org": 0.7,
    "hearsay": 0.4,
}

# Chat inactivity trigger timeout (minutes)
CHAT_INACTIVITY_TIMEOUT_MINUTES = 30

# Relation weight keywords — exact match sets
_HIGH_WEIGHT_EXACT = {
    "家人",
    "父子",
    "母子",
    "兄弟",
    "姐妹",
    "夫妻",
    "恋人",
    "family",
    "parent",
    "sibling",
    "spouse",
    "lover",
}
_MEDIUM_WEIGHT_EXACT = {
    "朋友",
    "同僚",
    "同学",
    "战友",
    "搭档",
    "friend",
    "colleague",
    "classmate",
    "partner",
}
_LOW_WEIGHT_EXACT = {
    "认识",
    "邻居",
    "上下级",
    "acquaintance",
    "neighbor",
    "superior",
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _is_enabled() -> bool:
    """Check feature flag MEMORY_PROPAGATION_ENABLED."""
    return os.environ.get("MEMORY_PROPAGATION_ENABLED", "false").lower() in ("true", "1", "yes")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _infer_severity(event_impacts: list[dict]) -> str:
    """Get the highest severity from event impact dicts."""
    max_severity = "low"
    for impact in event_impacts:
        s = impact.get("severity", "low")
        if _SEVERITY_ORDER.get(s, 0) > _SEVERITY_ORDER.get(max_severity, 0):
            max_severity = s
    return max_severity


def _get_relation_priority_weight(relation_type: str | None) -> int:
    """Relation type weight for candidate sorting.

    Exact match first, then substring fallback.
    """
    if not relation_type:
        return 0
    type_lower = relation_type.lower().strip()

    # Exact match first
    if type_lower in _HIGH_WEIGHT_EXACT:
        return 3
    if type_lower in _MEDIUM_WEIGHT_EXACT:
        return 2
    if type_lower in _LOW_WEIGHT_EXACT:
        return 1

    # Substring fallback (reuse exact sets)
    for kw in _HIGH_WEIGHT_EXACT:
        if kw in type_lower:
            return 3
    for kw in _MEDIUM_WEIGHT_EXACT:
        if kw in type_lower:
            return 2
    for kw in _LOW_WEIGHT_EXACT:
        if kw in type_lower:
            return 1
    return 0


def world_day(virtual_time: datetime, world_created_at: datetime) -> int:
    """Day count since world creation. World creation day = day 1."""
    delta = virtual_time - world_created_at
    return max(1, delta.days + 1)


# ── Service ───────────────────────────────────────────────────────────────────


class MemoryPropagationService:
    def __init__(
        self,
        llm: LLMProvider,
        session_factory: async_sessionmaker[AsyncSession],
        redis=None,  # redis.asyncio.Redis, optional for character name cache
    ):
        self.llm = llm
        self.session_factory = session_factory
        self._redis = redis

    # ── Public API ─────────────────────────────────────────────────────────

    async def propagate_after_event_memories(
        self,
        world_id: str,
        event_id: str,
        participant_names: list[str],
        newly_written_memories: list,
        virtual_time: datetime,
        event_impacts: list[dict],
    ) -> dict:
        """Event SSE: propagate hearsay after memories are written.

        Returns:
            {"propagated": int, "skipped": str | None}
        """
        if not _is_enabled():
            return {"propagated": 0, "skipped": "disabled"}

        try:
            return await self._propagate_event_inner(
                world_id=world_id,
                event_id=event_id,
                participant_names=participant_names,
                newly_written_memories=newly_written_memories,
                virtual_time=virtual_time,
                event_impacts=event_impacts,
            )
        except Exception:
            logger.exception("propagate_after_event_memories failed")
            return {"propagated": 0, "skipped": "error"}

    async def propagate_after_chat_flush(
        self,
        world_id: str,
        session_id: str,
        participant_names: list[str],
        newly_written_memories: list,
        virtual_time: datetime,
    ) -> dict:
        """Chat flush: propagate hearsay after memories are written.

        No severity threshold check — flush success means trigger.
        Uses CHAT_PROPAGATION_BUDGET (smaller budget).
        """
        if not _is_enabled():
            return {"propagated": 0, "skipped": "disabled"}

        try:
            return await self._propagate_chat_inner(
                world_id=world_id,
                session_id=session_id,
                participant_names=participant_names,
                newly_written_memories=newly_written_memories,
                virtual_time=virtual_time,
            )
        except Exception:
            logger.exception("propagate_after_chat_flush failed")
            return {"propagated": 0, "skipped": "error"}

    async def evaluate_relation_changes(self, world_id: str) -> dict:
        """Check accumulated memories for relationship updates.

        Called after propagation writes (Step 7).
        """
        # v1: Stub implementation — relation evaluation is Phase 2
        return {"evaluated": 0, "updated": 0}

    # ── Event path inner ───────────────────────────────────────────────────

    async def _propagate_event_inner(
        self,
        world_id: str,
        event_id: str,
        participant_names: list[str],
        newly_written_memories: list,
        virtual_time: datetime,
        event_impacts: list[dict],
    ) -> dict:
        # Create independent session and repos for this propagation
        async with self.session_factory() as session:
            character_repo = CharacterRepository(session)
            memory_repo = CharacterMemoryRepository(session)
            relation_repo = RelationRepository(session)
            world_repo = WorldRepository(session)

            world_doc = await world_repo.get(world_id)
            world_scale = self._get_world_scale(world_doc)
            max_severity = _infer_severity(event_impacts)
            if not self._meets_severity_threshold(max_severity, world_scale):
                return {"propagated": 0, "skipped": "severity_below_threshold"}

            # Filter to real memories, excluding trivial/private
            propagable = [
                m
                for m in newly_written_memories
                if self._should_propagate(m)
                and getattr(m, "memory_category", None) not in ("trivial", "private", None)
            ]
            if not propagable:
                return {"propagated": 0, "skipped": "no_propagable_memories"}

            # Build candidate pool (exclude user character)
            user_char_id = getattr(world_doc, "user_character_id", None) if world_doc else None
            exclude_user = {uuid.UUID(user_char_id)} if user_char_id else set()

            candidates = await self._build_candidate_pool(
                world_id=world_id,
                participant_names=participant_names,
                exclude_ids=exclude_user,
                character_repo=character_repo,
                relation_repo=relation_repo,
            )
            if not candidates:
                return {"propagated": 0, "skipped": "no_candidates"}

            # Budget trimming
            budget = self._get_budget(world_scale, is_event=True)
            candidates = candidates[:budget]

            # Merge involved_characters from all propagable memories
            merged_involved: list[uuid.UUID] = []
            seen_ids: set[uuid.UUID] = set()
            for m in propagable:
                for ic in m.involved_characters or []:
                    ic_uuid = ic if isinstance(ic, uuid.UUID) else uuid.UUID(ic)
                    if ic_uuid not in seen_ids:
                        seen_ids.add(ic_uuid)
                        merged_involved.append(ic_uuid)

            # ── Phase A: Event element write ──
            await self._write_event_element(
                world_id=world_id,
                event_id=event_id,
                participant_names=participant_names,
                newly_written_memories=newly_written_memories,
                virtual_time=virtual_time,
                event_impacts=event_impacts,
                max_severity=max_severity,
                world_scale=world_scale,
                world_doc=world_doc,
                memory_repo=memory_repo,
            )

            # ── Phase B: Multi-hop hearsay ──
            source_character_id = propagable[0].character_id if propagable else None
            propagated = await self._multi_hop_hearsay(
                world_id=world_id,
                event_id=uuid.UUID(event_id),
                candidates=candidates,
                source_memories=propagable,
                virtual_time=virtual_time,
                source_character_id=source_character_id,
                involved_characters=merged_involved,
                source="event_flush",
                severity=max_severity,
                world_scale=world_scale,
                character_repo=character_repo,
                memory_repo=memory_repo,
                relation_repo=relation_repo,
                exclude_user=exclude_user,
                session_id=None,
            )

            await session.commit()

            return {"propagated": propagated, "skipped": None}

    # ── Chat path inner ────────────────────────────────────────────────────

    async def _propagate_chat_inner(
        self,
        world_id: str,
        session_id: str,
        participant_names: list[str],
        newly_written_memories: list,
        virtual_time: datetime,
    ) -> dict:
        # No severity threshold check — flush success = trigger
        async with self.session_factory() as session:
            character_repo = CharacterRepository(session)
            memory_repo = CharacterMemoryRepository(session)
            relation_repo = RelationRepository(session)
            world_repo = WorldRepository(session)

            world_doc = await world_repo.get(world_id)
            world_scale = self._get_world_scale(world_doc)

            # Filter out trivial, private, and hearsay memories from propagation
            propagable = [
                m
                for m in newly_written_memories
                if not getattr(m, "is_hearsay", False)
                and getattr(m, "memory_category", None) not in ("trivial", "private", None)
            ]
            if not propagable:
                return {"propagated": 0, "skipped": "no_propagable_memories"}

            # Build candidate pool (exclude user character)
            user_char_id = getattr(world_doc, "user_character_id", None) if world_doc else None
            exclude_user = {uuid.UUID(user_char_id)} if user_char_id else set()

            candidates = await self._build_candidate_pool(
                world_id=world_id,
                participant_names=participant_names,
                exclude_ids=exclude_user,
                character_repo=character_repo,
                relation_repo=relation_repo,
            )
            if not candidates:
                return {"propagated": 0, "skipped": "no_candidates"}

            # Budget trimming (chat path uses smaller budget)
            budget = self._get_budget(world_scale, is_event=False)
            candidates = candidates[:budget]

            # Chat path: multi-hop hearsay only (no event element write)
            source_character_id = propagable[0].character_id if propagable else None
            propagated = await self._multi_hop_hearsay(
                world_id=world_id,
                event_id=None,
                candidates=candidates,
                source_memories=propagable,
                virtual_time=virtual_time,
                source_character_id=source_character_id,
                involved_characters=None,
                source="chat_flush",
                severity=None,
                world_scale=world_scale,
                character_repo=character_repo,
                memory_repo=memory_repo,
                relation_repo=relation_repo,
                exclude_user=exclude_user,
                session_id=uuid.UUID(session_id) if isinstance(session_id, str) else session_id,
            )

            await session.commit()

            return {"propagated": propagated, "skipped": None}

    # ── Internal helpers ───────────────────────────────────────────────────

    def _should_propagate(self, memory) -> bool:
        """Check if a memory should trigger propagation."""
        if memory.is_hearsay:
            return False
        if not memory.origin_event_id:
            return False
        return True

    def _meets_severity_threshold(self, severity: str, world_scale: str) -> bool:
        """Check if severity meets the threshold for the given world scale."""
        threshold = PROPAGATION_SEVERITY_THRESHOLD.get(world_scale, "high")
        return _SEVERITY_ORDER.get(severity, 0) >= _SEVERITY_ORDER.get(threshold, 0)

    def _get_budget(self, world_scale: str, is_event: bool) -> int:
        """Get propagation budget for the given scale and path."""
        if is_event:
            return PROPAGATION_BUDGET.get(world_scale, 4)
        return CHAT_PROPAGATION_BUDGET.get(world_scale, 2)

    def _get_world_scale(self, world_doc) -> str:
        """Get world scale from world_doc."""
        if not world_doc:
            return "standard"
        return getattr(world_doc, "scale", "standard") or "standard"

    async def _build_candidate_pool(
        self,
        world_id: str,
        participant_names: list[str],
        exclude_ids: set[uuid.UUID],
        character_repo,
        relation_repo,
    ) -> list[dict]:
        """Build propagation candidates: characters related to participants.

        Returns list of dicts sorted by relation weight (descending):
        [{"character_id": UUID, "name": str, "profile": dict, "weight": int, "rel_type": str}]
        """
        if not participant_names:
            return []

        # Resolve participant names to UUIDs
        participant_ids: set[uuid.UUID] = set()
        for name in participant_names:
            char = await character_repo.find_by_name(world_id, name)
            if char:
                participant_ids.add(char.id)

        if not participant_ids:
            return []

        # Get all relations in the world
        all_relations = await relation_repo.list_by_world(world_id)

        # Build candidate map: related_char_id -> (weight, rel_type)
        candidate_map: dict[uuid.UUID, tuple[int, str]] = {}
        for rel in all_relations:
            rel_a = (
                rel.character_a
                if isinstance(rel.character_a, uuid.UUID)
                else uuid.UUID(rel.character_a)
            )
            rel_b = (
                rel.character_b
                if isinstance(rel.character_b, uuid.UUID)
                else uuid.UUID(rel.character_b)
            )

            other_id = None
            if rel_a in participant_ids and rel_b not in participant_ids:
                other_id = rel_b
            elif rel_b in participant_ids and rel_a not in participant_ids:
                other_id = rel_a

            if other_id is None:
                continue
            if other_id in exclude_ids:
                continue

            weight = _get_relation_priority_weight(rel.type)
            # Keep highest weight if multiple relations exist
            if other_id not in candidate_map or weight > candidate_map[other_id][0]:
                candidate_map[other_id] = (weight, rel.type or "")

        # Sort by weight descending
        candidates = [
            {
                "character_id": cid,
                "weight": w,
                "rel_type": rt,
            }
            for cid, (w, rt) in candidate_map.items()
        ]
        candidates.sort(key=lambda c: c["weight"], reverse=True)
        return candidates

    # ── Event element write ────────────────────────────────────────────────

    def _should_write_event_element(
        self,
        memories: list,
        max_severity: str,
    ) -> bool:
        """Decide whether to write an event element (event map entry).

        Trivial → skip (unless critical severity).
        Private-only (no major) → skip.
        Major → always write.
        Mixed → write if severity high/critical.
        """
        if not memories:
            return False

        categories = [getattr(m, "memory_category", None) for m in memories]

        if "major" in categories:
            return True

        if all(c == "trivial" for c in categories):
            return max_severity in ("critical",)

        if all(c == "private" for c in categories):
            return False

        return max_severity in ("high", "critical")

    async def _write_event_element(
        self,
        world_id: str,
        event_id: str,
        participant_names: list[str],
        newly_written_memories: list,
        virtual_time: datetime,
        event_impacts: list[dict],
        max_severity: str,
        world_scale: str,
        world_doc,
        memory_repo,
    ) -> None:
        """Write event element to event index.

        Private events get dissemination=0, effective_day=NULL.
        """
        if not self._should_write_event_element(newly_written_memories, max_severity):
            return

        # Count major memories
        major_count = sum(
            1 for m in newly_written_memories if getattr(m, "memory_category", None) == "major"
        )

        # LLM judge dissemination + source type
        event_description = "\n".join(f"- {m.content}" for m in newly_written_memories)
        try:
            base_dissemination, source_type = await self._judge_dissemination(
                world_id=world_id,
                event_description=event_description,
                event_impacts=event_impacts,
            )
        except Exception:
            logger.warning("Dissemination judgment failed, defaulting to 0.5/official")
            base_dissemination, source_type = 0.5, "official"

        authority_coeff = AUTHORITY_COEFFICIENT.get(source_type, 0.7)
        dissemination = base_dissemination * authority_coeff

        # Pure private memories (all private, no major) → force dissemination = 0
        categories = [getattr(m, "memory_category", None) for m in newly_written_memories]
        if all(c == "private" for c in categories) and major_count == 0:
            dissemination = 0.0

        # Calculate effective day (private events → NULL)
        if dissemination > 0:
            world_created_at = self._get_world_created_at(world_doc)
            base_delay = EVENT_NEWS_BASE_DELAY.get(world_scale, 1)
            effective_delay_days = round(base_delay * (1 - dissemination))
            event_day = world_day(virtual_time, world_created_at)
            effective_day = event_day + effective_delay_days
        else:
            effective_day = None

        # Write to event index
        event_index_repo = EventIndexRepository(memory_repo.session)

        # Derive event_name from first major memory or first memory
        event_name = ""
        for m in newly_written_memories:
            if getattr(m, "memory_category", None) == "major":
                event_name = m.content[:80]
                break
        if not event_name and newly_written_memories:
            event_name = newly_written_memories[0].content[:80]

        event_brief = event_description[:200]

        try:
            existing = await event_index_repo.get_by_id(event_id)
            if existing:
                existing.dissemination = dissemination
                existing.effective_day = effective_day
            else:
                await event_index_repo.add(
                    id=uuid.UUID(event_id),
                    world_id=uuid.UUID(world_id),
                    event_name=event_name,
                    brief=event_brief,
                    dissemination=dissemination,
                    effective_day=effective_day,
                )
        except Exception:
            logger.warning("Failed to write event element for %s", event_id)

    async def _judge_dissemination(
        self,
        world_id: str,
        event_description: str,
        event_impacts: list[dict],
    ) -> tuple[float, str]:
        """LLM judge: base_dissemination (0-1) + source_type (official/folk_org/hearsay).

        Returns: (base_dissemination, source_type)
        """
        from src.llm.base import get_lang_hint

        lang_hint = get_lang_hint()

        impacts_text = (
            "\n".join(
                f"- severity={imp.get('severity', '?')}, target={imp.get('target_character', '?')}"
                for imp in event_impacts
            )
            or "（无影响数据）"
        )

        system_prompt = (
            "你是新闻传播分析器。根据事件描述和影响，判断两个维度。\n\n"
            "## 维度 1：基础传播度（0-1）\n\n"
            "- 0.0：完全私密，只有参与者知道\n"
            "- 0.3：小范围传播（社区八卦、行业内部消息）\n"
            "- 0.5：中等传播（地方新闻、某群体共同经历）\n"
            "- 0.7：大范围传播（全国性新闻、重大社会事件）\n"
            "- 1.0：人尽皆知（天灾、战争、国王驾崩）\n\n"
            "## 维度 2：最可能的信息来源类型\n\n"
            '- "official"：官方公告、正式声明\n'
            '- "folk_org"：民间组织、行会、商会\n'
            '- "hearsay"：小道消息、口口相传\n\n'
            "## 输出格式\n\n"
            "```json\n"
            '{"base_dissemination": 0.0~1.0, "source_type": "official"/"folk_org"/"hearsay", '
            '"reasoning": "一句话说明"}\n'
            "```" + lang_hint
        )
        user_prompt = f"## 事件描述\n{event_description}\n\n## 事件影响\n{impacts_text}"

        try:
            result = await self.llm.complete_json(
                system_prompt,
                user_prompt,
                prefill="{",
            )
        except Exception:
            logger.warning("Dissemination LLM call failed, using defaults")
            return 0.5, "official"

        if isinstance(result, list) and result:
            result = result[0]
        if not isinstance(result, dict):
            return 0.5, "official"

        base = float(result.get("base_dissemination", 0.5))
        base = max(0.0, min(1.0, base))

        source_type = result.get("source_type", "hearsay")
        if source_type not in AUTHORITY_COEFFICIENT:
            source_type = "hearsay"

        return base, source_type

    def _get_world_created_at(self, world_doc) -> datetime:
        """Get world created_at timestamp from world_doc."""
        if world_doc:
            created_at = getattr(world_doc, "created_at", None)
            if created_at:
                return created_at
        return _utcnow()

    # ── Multi-hop hearsay ─────────────────────────────────────────────────

    async def _multi_hop_hearsay(
        self,
        world_id: str,
        event_id: uuid.UUID | None,
        candidates: list[dict],
        source_memories: list,
        virtual_time: datetime,
        source_character_id: uuid.UUID | None,
        involved_characters: list[uuid.UUID] | None,
        source: str,
        severity: str | None,
        world_scale: str,
        character_repo,
        memory_repo,
        relation_repo,
        exclude_user: set[uuid.UUID] | None = None,
        session_id: uuid.UUID | None = None,
    ) -> int:
        """Two-hop hearsay propagation. Returns total count of written hearsay."""
        if not candidates or not source_memories:
            return 0

        # Resolve candidate names and profiles
        candidate_ids = [str(cand["character_id"]) for cand in candidates]
        name_map = await get_character_names(
            candidate_ids, redis=self._redis, character_repo=character_repo
        )

        # Batch resolve cache misses to avoid N+1 queries
        cache_miss_ids = [
            str(cand["character_id"])
            for cand in candidates
            if str(cand["character_id"]) not in name_map
        ]
        miss_names: dict[str, str] = {}
        for mid in cache_miss_ids:
            char = await character_repo.get_by_id(mid)
            miss_names[mid] = char.name if char else mid

        for cand in candidates:
            cid = str(cand["character_id"])
            cand["name"] = name_map.get(cid) or miss_names.get(cid, cid)

        # ── Hop 1: Three-parameter filtering ──
        hop1_passed = []
        for cand in candidates:
            weight = cand.get("weight", 0)

            # Parameter 1: will they tell?
            spread_prob = HEARSAY_SPREAD_PROBABILITY.get(weight, 0.2)
            if random.random() >= spread_prob:
                continue

            # Parameter 2: relation coefficient (hop-1 only)
            relation_coeff = HEARSAY_RELATION_COEFF.get(weight, 0.5)

            # Parameter 3: random retention
            retention_range = HEARSAY_RETENTION_RANGE.get(weight, (0.6, 0.7))
            retention_coeff = random.uniform(*retention_range)

            info_amount = relation_coeff * retention_coeff

            if info_amount < HEARSAY_INFO_THRESHOLD:
                continue

            hop1_passed.append(
                {
                    "character_id": cand["character_id"],
                    "name": cand["name"],
                    "weight": weight,
                    "rel_type": cand.get("rel_type", ""),
                    "info_amount": info_amount,
                    "spread_prob": spread_prob,
                    "retention_coeff": retention_coeff,
                }
            )

        if not hop1_passed:
            return 0

        # ── Hop 1 LLM generation ──
        hop1_hearsay_map = await self._generate_hearsay_batch(
            source_memories=source_memories,
            candidates=hop1_passed,
            hop_count=1,
        )

        # ── Write hop-1 hearsay ──
        world_id_uuid = uuid.UUID(world_id) if isinstance(world_id, str) else world_id
        hop1_results = []
        propagated = 0
        for cand in hop1_passed:
            hearsay_content = hop1_hearsay_map.get(str(cand["character_id"]))
            if not hearsay_content:
                continue

            delay = self._calculate_hearsay_delay(cand["weight"], hop_count=1)
            visible_at = virtual_time + delay

            try:
                await self._write_hearsay_memory(
                    character_id=cand["character_id"],
                    world_id=world_id_uuid,
                    content=hearsay_content,
                    visible_at=visible_at,
                    origin_event_id=event_id,
                    propagated_from=source_character_id,
                    source_character_id=source_character_id,
                    hop_count=1,
                    info_amount=cand["info_amount"],
                    spread_prob=cand.get("spread_prob"),
                    retention_coeff=cand.get("retention_coeff"),
                    involved_characters=involved_characters,
                    session_id=session_id,
                    source=source,
                    severity=severity,
                    memory_repo=memory_repo,
                )
                propagated += 1
                hop1_results.append(cand)
            except Exception:
                logger.debug("Failed to write hop-1 hearsay for %s", cand["name"])
                continue

        # ── Hop 2 (if MAX_HOP_COUNT >= 2 and hop-1 had results) ──
        if hop1_results and MAX_HOP_COUNT >= 2:
            hop2_propagated = await self._propagate_hop2(
                world_id=world_id_uuid,
                event_id=event_id,
                hop1_results=hop1_results,
                hop1_hearsay_map=hop1_hearsay_map,
                source_character_id=source_character_id,
                participant_ids=set(involved_characters) if involved_characters else set(),
                virtual_time=virtual_time,
                involved_characters=involved_characters,
                source=source,
                severity=severity,
                world_scale=world_scale,
                character_repo=character_repo,
                memory_repo=memory_repo,
                relation_repo=relation_repo,
                exclude_user=exclude_user,
                session_id=session_id,
            )
            propagated += hop2_propagated

        return propagated

    async def _propagate_hop2(
        self,
        world_id: uuid.UUID,
        event_id: uuid.UUID | None,
        hop1_results: list[dict],
        hop1_hearsay_map: dict,
        source_character_id: uuid.UUID | None,
        participant_ids: set[uuid.UUID],
        virtual_time: datetime,
        involved_characters: list[uuid.UUID] | None,
        source: str,
        severity: str | None,
        world_scale: str,
        character_repo,
        memory_repo,
        relation_repo,
        exclude_user: set[uuid.UUID] | None = None,
        session_id: uuid.UUID | None = None,
    ) -> int:
        """Second-hop propagation: hop-1 receivers become sources."""
        # Build hop-2 candidate pool from hop-1 receivers' relations
        hop1_char_ids = {r["character_id"] for r in hop1_results}

        all_relations = await relation_repo.list_by_world(str(world_id))

        exclude_ids = hop1_char_ids | participant_ids | (exclude_user or set())
        candidate_map: dict[uuid.UUID, tuple[int, str, uuid.UUID]] = {}

        for rel in all_relations:
            rel_a = (
                rel.character_a
                if isinstance(rel.character_a, uuid.UUID)
                else uuid.UUID(rel.character_a)
            )
            rel_b = (
                rel.character_b
                if isinstance(rel.character_b, uuid.UUID)
                else uuid.UUID(rel.character_b)
            )

            source_id = None
            other_id = None
            if rel_a in hop1_char_ids and rel_b not in hop1_char_ids:
                source_id, other_id = rel_a, rel_b
            elif rel_b in hop1_char_ids and rel_a not in hop1_char_ids:
                source_id, other_id = rel_b, rel_a

            if other_id is None or other_id in exclude_ids:
                continue
            assert source_id is not None  # source_id/other_id are always assigned together above

            weight = _get_relation_priority_weight(rel.type)
            if other_id not in candidate_map or weight > candidate_map[other_id][0]:
                candidate_map[other_id] = (weight, rel.type or "", source_id)

        if not candidate_map:
            return 0

        hop2_candidates = [
            {"character_id": cid, "weight": w, "rel_type": rt, "related_to": src}
            for cid, (w, rt, src) in candidate_map.items()
        ]
        hop2_candidates.sort(key=lambda c: c["weight"], reverse=True)

        # Hop-2 budget = half of hop-1
        budget = self._get_budget(world_scale, is_event=(event_id is not None))
        hop2_budget = max(1, budget // 2)
        hop2_candidates = hop2_candidates[:hop2_budget]

        # Resolve names
        hop2_ids = [str(c["character_id"]) for c in hop2_candidates]
        name_map = await get_character_names(
            hop2_ids, redis=self._redis, character_repo=character_repo
        )
        # Batch resolve cache misses
        hop2_miss_ids = [
            str(c["character_id"])
            for c in hop2_candidates
            if str(c["character_id"]) not in name_map
        ]
        hop2_miss_names: dict[str, str] = {}
        for mid in hop2_miss_ids:
            char = await character_repo.get_by_id(mid)
            hop2_miss_names[mid] = char.name if char else mid

        for cand in hop2_candidates:
            cid = str(cand["character_id"])
            cand["name"] = name_map.get(cid) or hop2_miss_names.get(cid, cid)

        # Fixed info amount = average of hop-1 info amounts
        fixed_hop1_info = sum(r["info_amount"] for r in hop1_results) / len(hop1_results)

        # Hop-2 three-parameter filtering (no relation_coeff)
        hop2_passed = []
        for cand in hop2_candidates:
            weight = cand.get("weight", 0)

            spread_prob = HEARSAY_SPREAD_PROBABILITY.get(weight, 0.2)
            if random.random() >= spread_prob:
                continue

            retention_range = HEARSAY_RETENTION_RANGE.get(weight, (0.6, 0.7))
            retention_coeff = random.uniform(*retention_range)

            info_amount = fixed_hop1_info * retention_coeff

            if info_amount < HEARSAY_INFO_THRESHOLD:
                continue

            hop2_passed.append(
                {
                    **cand,
                    "info_amount": info_amount,
                    "spread_prob": spread_prob,
                    "retention_coeff": retention_coeff,
                }
            )

        if not hop2_passed:
            return 0

        # Build source_memories_by_receiver for hop-2 (each receiver has different source)
        hop2_source_map: dict[str, str] = {}
        for cand in hop2_passed:
            source_char_id = cand["related_to"]
            hearsay = hop1_hearsay_map.get(str(source_char_id))
            if hearsay:
                hop2_source_map[str(cand["character_id"])] = hearsay

        # Hop-2 LLM generation
        hop2_hearsay_map = await self._generate_hearsay_batch(
            source_memories=None,
            candidates=hop2_passed,
            hop_count=2,
            source_memories_by_receiver=hop2_source_map,
            fixed_info_amount=fixed_hop1_info,
        )

        # Write hop-2 hearsay
        propagated = 0
        for cand in hop2_passed:
            hearsay_content = hop2_hearsay_map.get(str(cand["character_id"]))
            if not hearsay_content:
                continue

            delay = self._calculate_hearsay_delay(cand["weight"], hop_count=2)
            visible_at = virtual_time + delay

            try:
                await self._write_hearsay_memory(
                    character_id=cand["character_id"],
                    world_id=world_id,
                    content=hearsay_content,
                    visible_at=visible_at,
                    origin_event_id=event_id,
                    propagated_from=cand["related_to"],
                    source_character_id=cand["related_to"],
                    hop_count=2,
                    info_amount=cand["info_amount"],
                    spread_prob=cand.get("spread_prob"),
                    retention_coeff=cand.get("retention_coeff"),
                    involved_characters=involved_characters,
                    session_id=session_id,
                    source=source,
                    severity=severity,
                    memory_repo=memory_repo,
                )
                propagated += 1
            except Exception:
                logger.debug("Failed to write hop-2 hearsay for %s", cand.get("name", "?"))
                continue

        return propagated

    async def _generate_hearsay_batch(
        self,
        source_memories: list | None,
        candidates: list[dict],
        hop_count: int = 1,
        source_memories_by_receiver: dict[str, str] | None = None,
        fixed_info_amount: float | None = None,
    ) -> dict[str, str | None]:
        """Batch LLM hearsay generation. Returns {character_id_str: hearsay_content}."""
        from src.llm.base import get_lang_hint

        lang_hint = get_lang_hint()

        # Build candidate input for prompt
        candidate_inputs = []
        for c in candidates:
            if hop_count == 1:
                info = c["info_amount"]
            else:
                info = fixed_info_amount or c["info_amount"]

            if info >= 0.8:
                reduction = "轻度删减：保留核心事实 + 关键细节 + 部分对话"
            elif info >= 0.6:
                reduction = "中度删减：保留核心事实 + 主要结果，删除具体措辞和次要人物"
            else:
                reduction = "重度删减：仅保留'谁做了什么'和最终结果，删除所有细节"

            hop_label = "我听说" if hop_count == 1 else "我听人说起"
            candidate_inputs.append(
                {
                    "character_id": str(c["character_id"]),
                    "character_name": c.get("name", "未知"),
                    "info_amount": round(info, 2),
                    "reduction_level": reduction,
                    "hop_label": hop_label,
                }
            )

        # Build source content
        if hop_count == 1 and source_memories:
            source_content = "\n".join(f"- {m.content}" for m in source_memories)
        else:
            source_content = ""

        # XML-wrapped so each recipient's info_amount/reduction_level stays
        # unambiguously scoped to them — misattributing these to another
        # recipient means a character "knows" something they shouldn't.
        candidate_list_text = "\n".join(
            f'<recipient character="{ci["character_name"]}" '
            f'info_amount="{ci["info_amount"]}" '
            f'reduction="{ci["reduction_level"]}"/>'
            for ci in candidate_inputs
        )

        system_prompt = (
            "你是信息传播模拟器。根据原始记忆内容，为多个角色分别生成传闻版本。\n\n"
            "## 删减规则\n\n"
            "每个角色的删减程度由其 info_amount 决定。\n\n"
            "1. 不得添加原始记忆中没有的内容\n"
            "2. 不得编造对话、情感反应或内心活动\n"
            "3. 视角转换为对应角色的 hop_label\n"
            "4. 每条传闻控制在 50 字以内\n"
            "5. info_amount 越低，删减越多\n\n"
            "## 输出格式\n\n"
            "```json\n"
            '{"hearsays": [{"character": "角色名", "content": "传闻内容" 或 null}, ...]}\n'
            "```" + lang_hint
        )

        # Build user prompt with source text per receiver (for hop-2 different sources)
        if hop_count == 2 and source_memories_by_receiver:
            parts = []
            for ci in candidate_inputs:
                cname = ci["character_name"]
                cid = ci["character_id"]
                src = source_memories_by_receiver.get(cid, source_content)
                parts.append(f'<source character="{cname}">\n{src}\n</source>')
            source_text = "\n\n".join(parts)
        else:
            source_text = source_content

        user_prompt = (
            f"## 原始记忆内容\n{source_text}\n\n"
            f"## 接收角色（共 {len(candidate_inputs)} 人）\n{candidate_list_text}"
        )

        try:
            result = await self.llm.complete_json(
                system_prompt,
                user_prompt,
                prefill="{",
            )
        except Exception:
            logger.warning("Hearsay batch LLM call failed, returning empty")
            return {}

        if isinstance(result, list) and result:
            result = result[0]
        if not isinstance(result, dict):
            return {}

        hearsays = result.get("hearsays", [])
        if not isinstance(hearsays, list):
            return {}

        out: dict[str, str | None] = {}
        # Build normalized name lookup: normalized_name -> candidate
        name_lookup: dict[str, dict] = {}
        for c in candidates:
            name = c.get("name", "")
            if name:
                name_lookup[name.strip().lower()] = c

        for item in hearsays:
            if not isinstance(item, dict):
                continue
            char_name = item.get("character", "")
            content = item.get("content")
            if not char_name:
                continue
            # Map name back to character_id (normalized match)
            matched = name_lookup.get(char_name.strip().lower())
            if matched:
                out[str(matched["character_id"])] = content

        return out

    async def _write_hearsay_memory(
        self,
        character_id: uuid.UUID,
        world_id: uuid.UUID,
        content: str,
        visible_at: datetime,
        origin_event_id: uuid.UUID | None,
        propagated_from: uuid.UUID | None,
        source_character_id: uuid.UUID | None,
        hop_count: int,
        info_amount: float,
        memory_repo: CharacterMemoryRepository,
        spread_prob: float | None = None,
        retention_coeff: float | None = None,
        involved_characters: list[uuid.UUID] | None = None,
        session_id: uuid.UUID | None = None,
        source: str = "event_flush",
        severity: str | None = None,
    ) -> None:
        """Write hearsay memory with dedup: keep higher info_amount if conflict.

        Event path (has origin_event_id): uses upsert — try INSERT first,
        catch IntegrityError from the unique index, then read the existing
        row and keep the one with higher info_amount.  This avoids the
        read-check-write race window.

        Chat path (session_id, no origin_event_id): read-check-write with
        explicit flush after update (no unique index available).
        """
        # Build propagation meta
        prop_meta: dict = {
            "source": source,
            "hop_count": hop_count,
            "info_amount": round(info_amount, 4),
        }
        if spread_prob is not None:
            prop_meta["spread_probability"] = round(spread_prob, 4)
        if retention_coeff is not None:
            prop_meta["retention_coefficient"] = round(retention_coeff, 4)
        if severity:
            prop_meta["severity"] = severity

        # Get next sequence for this character
        max_seq = await memory_repo.get_max_sequence(character_id)
        sequence = (max_seq or 0) + 1

        if origin_event_id:
            # Event path: upsert to avoid race condition
            # Unique index: (character_id, origin_event_id) WHERE is_hearsay
            try:
                await memory_repo.add_hearsay(
                    character_id=character_id,
                    world_id=world_id,
                    session_id=session_id,
                    content=content,
                    visible_at=visible_at,
                    origin_event_id=origin_event_id,
                    propagated_from=propagated_from,
                    involved_characters=involved_characters,
                    propagation_meta=prop_meta,
                    hop_count=hop_count,
                    info_amount=info_amount,
                    source_character_id=source_character_id,
                    memory_sequence=sequence,
                )
            except IntegrityError:
                # Concurrent insert won — compare info_amount
                await memory_repo.session.flush()
                existing = await memory_repo.get_hearsay_by_event(
                    character_id=character_id,
                    origin_event_id=origin_event_id,
                )
                if existing and info_amount > (existing.info_amount or 0):
                    existing.content = content
                    existing.info_amount = info_amount
                    existing.hop_count = hop_count
                    existing.source_character_id = source_character_id
                    existing.propagation_meta = prop_meta
                    existing.visible_at = visible_at
                    await memory_repo.session.flush()
        elif session_id:
            # Chat path: read-check-write (no unique index for session dedup)
            existing = await memory_repo.get_hearsay_by_session(
                character_id=character_id,
                session_id=session_id,
                source_character_id=source_character_id,
            )
            if existing:
                if info_amount > (existing.info_amount or 0):
                    existing.content = content
                    existing.info_amount = info_amount
                    existing.hop_count = hop_count
                    existing.source_character_id = source_character_id
                    existing.propagation_meta = prop_meta
                    existing.visible_at = visible_at
                    await memory_repo.session.flush()
                return

            await memory_repo.add_hearsay(
                character_id=character_id,
                world_id=world_id,
                session_id=session_id,
                content=content,
                visible_at=visible_at,
                origin_event_id=origin_event_id,
                propagated_from=propagated_from,
                involved_characters=involved_characters,
                propagation_meta=prop_meta,
                hop_count=hop_count,
                info_amount=info_amount,
                source_character_id=source_character_id,
                memory_sequence=sequence,
            )

    def _calculate_hearsay_delay(self, relation_weight: int, hop_count: int) -> timedelta:
        """Calculate hearsay propagation delay. Higher hop_count = longer delay."""
        base = PROPAGATION_DELAY.get(relation_weight, timedelta(days=1))
        return base * hop_count
