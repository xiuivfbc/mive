"""Memory formatting helpers for prompt injection.

Shared between event_dialogue_service and dialogue_generation_service.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.models import M2CharacterMemory, M26EventIndex


# Constants
_FORCE_RECENT_COUNT = 2
_RECENT_HINT = "（以下为最近发生的事件，仅供参考，不必然与当前话题相关）"
_LONG_TERM_TOKEN_BUDGET = 2500  # midpoint of 2000-3000


def format_short_term_for_injection(
    memories: list[M2CharacterMemory],
) -> str:
    """Format short-term memories for prompt injection.

    Strategy: force inject the most recent 1-2 non-hearsay memories,
    then the rest via vector search (handled by caller).

    This function formats ALL provided memories, with the most recent
    1-2 flagged with a hint. The caller is responsible for ensuring
    the first N entries are the most recent.
    """
    if not memories:
        return "暂无"

    lines: list[str] = []
    for i, m in enumerate(memories):
        if i < _FORCE_RECENT_COUNT:
            if i == 0:
                lines.append(_RECENT_HINT)
        reflection = getattr(m, "short_term_reflection", None)
        if isinstance(reflection, str) and reflection:
            lines.append(f'<memory type="short_term">{m.content}（感悟：{reflection}）</memory>')
        else:
            lines.append(f'<memory type="short_term">{m.content}</memory>')

    return "\n".join(lines)


def format_event_index_for_injection(events: list[M26EventIndex]) -> str:
    """Format event index entries for prompt injection.

    Output format:
        已有事件：
        E001 - 叛军攻入王城，公主在护卫下出逃
        E002 - 黑森林中发现古代遗迹的仪式痕迹
    """
    if not events:
        return "暂无事件索引"

    lines = ["已有事件："]
    for i, e in enumerate(events, start=1):
        lines.append(f"E{i:03d} - {e.brief}")
    return "\n".join(lines)


def format_long_term_for_injection(
    memories: list[M2CharacterMemory],
    event_index: dict[str, str] | None = None,
) -> str:
    """Format long-term memories for prompt injection.

    Structured memories (with event_name) are formatted as:
    [事件名] 视角详情 | 感悟：xxx

    When event_index is provided (key=UUID string, value=event_name),
    event_name that matches a UUID in the index is replaced with the
    human-readable event name.

    Legacy memories (without event_name) fall back to content field.

    Token budget: ~2500 chars (roughly 2500 tokens for Chinese text).
    When over budget, oldest memories are dropped.
    """
    if not memories:
        return "暂无"

    # Format each memory
    formatted: list[str] = []
    for m in memories:
        event_name = getattr(m, "event_name", None)
        perspective_detail = getattr(m, "perspective_detail", None)
        reflection = getattr(m, "reflection", None)
        # Only use structured fields if they are actual strings
        if isinstance(event_name, str) and event_name:
            # Resolve event ID to human-readable name via event_index
            display_name = event_name
            if event_index and event_name in event_index:
                display_name = event_index[event_name]
            parts = [f"[{display_name}]"]
            if isinstance(perspective_detail, str) and perspective_detail:
                parts.append(perspective_detail)
            if isinstance(reflection, str) and reflection:
                parts.append(f"感悟：{reflection}")
            formatted.append(f'<memory type="long_term">{" ".join(parts)}</memory>')
        else:
            formatted.append(f'<memory type="long_term">{m.content}</memory>')

    # Apply token budget (rough: 1 Chinese char ~ 1 token)
    total_chars = sum(len(line) for line in formatted)
    if total_chars > _LONG_TERM_TOKEN_BUDGET:
        # Drop oldest (first in list, since list is chronological)
        while total_chars > _LONG_TERM_TOKEN_BUDGET and len(formatted) > 1:
            removed = formatted.pop(0)
            total_chars -= len(removed)

    return "\n".join(formatted) or "暂无"


def get_persona_fields(profile: dict) -> list[tuple[str, str]]:
    """Return (label, value) pairs for optional persona fields that are non-empty."""
    fields: list[tuple[str, str]] = []
    personality = profile.get("personality", "")
    if personality:
        fields.append(("性格特点", personality))
    speech_style = profile.get("speech_style", "")
    if speech_style:
        fields.append(("说话风格", speech_style))
    return fields
