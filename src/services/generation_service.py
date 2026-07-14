import asyncio
import logging
import re
import uuid
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from src.services.character_service import CharacterService

from src.db.repositories.character_repo import CharacterRepository
from src.db.repositories.relation_repo import RelationRepository
from src.llm.base import LLMProvider, get_lang_hint, llm_operation
from src.models.scale import DEFAULT_SCALE, SCALES
from src.models.templates import list_templates
from src.models.world import Element
from src.services.material_service import MaterialService
from src.services.search_service import SearchService
from src.services.snapshot_sync_service import bump_generation_sql
from src.services.version_service import VersionService
from src.services.wiki_filter import filter_wiki_content  # fallback for old worlds
from src.services.world_service import WorldService

logger = logging.getLogger(__name__)
from src.debug_logger import wcd  # noqa: E402

# ── 关系生成常量 ──────────────────────────────────────────────────────────────
PAIR_BUDGET = 1000  # Stage 3 每批最大配对数
RELATION_TOKENS_PER_PAIR = 150  # 每条关系估算 token 数
RELATION_MAX_TOKENS_CEILING = 12288  # max_tokens 上限
RELATION_MAX_TOKENS_FLOOR = 4096  # max_tokens 下限


def _estimate_relation_max_tokens(batch_size: int, scope_size: int, pair_budget: int) -> int:
    """根据批次参数估算所需的 max_tokens。

    Args:
        batch_size: 本批角色数
        scope_size: 可选范围角色数
        pair_budget: 配对预算

    Returns:
        估算的 max_tokens 值，限制在 [FLOOR, CEILING] 范围内
    """
    # 潜在配对数受限于配对预算
    potential_pairs = min(batch_size * scope_size, pair_budget)
    # 计算所需 token 数（使用潜在配对数作为安全上限）
    estimated_tokens = potential_pairs * RELATION_TOKENS_PER_PAIR
    # 限制在合理范围内
    return min(max(RELATION_MAX_TOKENS_FLOOR, estimated_tokens), RELATION_MAX_TOKENS_CEILING)


def _extract_wiki_canonical_name(section: str) -> str | None:
    """从 wiki 段落首行提取角色原文名。

    wiki 段落格式示例（clean_wiki_text 已剥离 #）：
      奧村正宗（奥村 正宗（おくむら まさむね），聲：榎木淳彌7）
    返回：奧村正宗
    """
    first_line = section.split("\n", 1)[0].strip()
    if not first_line:
        return None
    # 去掉括号及其后面的内容（中英文括号）
    title = re.split(r"[（(]", first_line, maxsplit=1)[0].strip()
    return title if title else None


def _extract_wiki_sections(wiki_text: str, names: list[str]) -> dict[str, tuple[str, str]]:
    """从 wiki 角色文本中按角色名截取对应段落。

    返回 {llm_name: (section_text, wiki_canonical_name)}。
    wiki_canonical_name 是从段落首行提取的 wiki 原文角色名，
    用于覆盖 LLM 输出的名字，确保呈现忠于 wiki 原文。

    匹配策略：按空行分段，子串匹配 + 繁简归一化兜底。
    """
    if not wiki_text or not names:
        return {}

    from opencc import OpenCC

    t2s = OpenCC("t2s")

    sections = re.split(r"\n\n+", wiki_text)
    results: dict[str, tuple[str, str]] = {}

    # 预计算所有 section 的简体版本（只算一次）
    sections_simplified: list[str] = [t2s.convert(s) for s in sections]

    for name in names:
        name_s = t2s.convert(name).strip()
        fallback: tuple[str, str] | None = None
        matched = False
        for idx, section in enumerate(sections):
            stripped = section.strip()
            stripped_s = sections_simplified[idx].strip()
            if name not in stripped and name_s not in stripped_s:
                continue
            canonical = _extract_wiki_canonical_name(stripped)
            canon_s = t2s.convert(canonical).strip() if canonical else ""
            if canon_s and canon_s == name_s:
                # 理想专属段落：首行即该角色名 → canonical 可信，用于保真显示名
                assert canonical is not None  # canon_s 非空隐含 canonical 非空（见上方推导）
                results[name] = (stripped, canonical)
                matched = True
                break
            if fallback is None:
                # 名单/关系/混合段落（如水浒 108 将名单、"X與Y" 关系表、
                # "張氏：林冲妻子…" 混合描述）：仅留作参考资料，canonical 置空，
                # 交由调用方回退候选名，避免多个角色共享同一首行名而被去重塌缩
                fallback = (stripped, "")
        if not matched and fallback is not None:
            results[name] = fallback
    return results


def _format_evidence(relation: dict) -> str:
    """Extract evidence_type from a relation dict, defaulting to 'inferred'.

    Args:
        relation: A relation dict that may contain an 'evidence_type' key.

    Returns:
        The evidence type string, either 'explicit' or 'inferred'.
    """
    return relation.get("evidence_type") or "inferred"


# ---------------------------------------------------------------------------
# Three-stage relation generation helpers
# ---------------------------------------------------------------------------


def assign_code_names(
    characters: list[dict],
) -> dict[str, str]:
    """Assign global code names C1, C2, ... to characters in list order.

    Returns:
        code_to_id dict mapping code names (C1..) to character UUIDs.
    """
    code_to_id: dict[str, str] = {}
    for i, char in enumerate(characters, 1):
        code = f"C{i}"
        cid = char.get("id", "")
        code_to_id[code] = cid
    return code_to_id


def _char_with_code(char: dict, code: str) -> str:
    """Format a character block with code name for prompts.

    XML-wrapped so multiple adjacent character blocks (e.g. core-tier
    characters with long structured Markdown `detail`) have unambiguous
    open/close boundaries and don't bleed into each other for the LLM.
    """
    name = char.get("name", "?")
    brief = char.get("profile", {}).get("brief", "")
    detail = char.get("profile", {}).get("detail", "")
    return (
        f'<character code="{code}" name="{name}">\n'
        f"<brief>{brief}</brief>\n"
        f"<detail>{detail}</detail>\n"
        "</character>"
    )


def _unwrap_relation_list(res: dict | list) -> dict | list:
    """Unwrap common LLM wrapper shapes to find the relations list.

    Tries known wrapper keys, then any list-valued key, then digs one
    level into a nested dict. Gives up after 2 layers and returns
    whatever was last seen (may still be a dict).
    """
    for _depth in range(2):
        if not isinstance(res, dict):
            break
        found = False
        for wrap_key in ("results", "relations", "pairs", "items", "data"):
            if isinstance(res.get(wrap_key), list):
                res = res[wrap_key]
                found = True
                break
        if found:
            break
        # 走到这里说明上面的 wrap_key 循环未命中，res 仍是进入本轮循环时的 dict
        assert isinstance(res, dict)
        for v in res.values():
            if isinstance(v, list):
                res = v
                found = True
                break
        if found:
            break
        # 同理：未命中列表值，res 仍是 dict
        assert isinstance(res, dict)
        for v in res.values():
            if isinstance(v, dict):
                res = v
                found = True
                break
        if not found:
            break
    return res


def _is_single_relation_dict(res: dict | list) -> bool:
    """True if res looks like one relation object (not wrapped in a list)."""
    return isinstance(res, dict) and "character_a" in res and "character_b" in res


def _resolve_relation_codes(
    rel: dict,
    code_to_id: dict[str, str],
) -> dict | None:
    """Resolve code names in a relation dict to UUIDs.

    Returns a new dict with character_a/character_b resolved to UUIDs,
    or None if either code is missing from code_to_id.
    """
    code_a = rel.get("character_a")
    code_b = rel.get("character_b")
    if not code_a or not code_b:
        return None
    uuid_a = code_to_id.get(code_a)
    uuid_b = code_to_id.get(code_b)
    if uuid_a is None or uuid_b is None:
        return None
    return {
        "character_a": uuid_a,
        "character_b": uuid_b,
        "type": rel.get("type", ""),
        "description": rel.get("description", ""),
        "direction": rel.get("direction", "bidirectional"),
        "evidence_type": _format_evidence(rel),
    }


def compute_batches(n: int, p: int) -> list[int]:
    """Compute dynamic batch sizes for non-core x non-core relation generation.

    Uses a pair-budget algorithm to keep each batch's pair count manageable.

    Args:
        n: Total number of non-core characters.
        p: Pair budget (max pairs per batch = batch_size * remaining).

    Returns:
        List of batch sizes that sum to n.
    """
    if n <= 0:
        return []

    result: list[int] = []
    remaining = n
    while remaining > 0:
        if remaining * remaining <= p:
            b = remaining
        else:
            b = max(1, p // remaining)
        result.append(b)
        remaining -= b
    return result


def _validate_character(char: dict) -> bool:
    """Validate that a character dict has required fields with valid content."""
    if not isinstance(char, dict):
        return False
    name = char.get("name")
    profile = char.get("profile") or {}
    brief = profile.get("brief")
    detail = profile.get("detail")
    if not name:
        return False
    if not isinstance(brief, str) or not brief.strip():
        return False
    if not isinstance(detail, str) or not detail.strip():
        return False
    return True


class GenerationService:
    def __init__(
        self,
        llm: LLMProvider,
        material_service: MaterialService,
        world_service: WorldService,
        character_repo: CharacterRepository,
        relation_repo: RelationRepository,
        version_service: VersionService,
        session: AsyncSession,
        search_service: SearchService | None = None,
        redis: Redis | None = None,
        character_service: "CharacterService | None" = None,
    ):
        self.llm = llm
        self.material_service = material_service
        self.world_service = world_service
        self.character_repo = character_repo
        self.relation_repo = relation_repo
        self.version_service = version_service
        self.session = session
        self.search_service = search_service
        self.redis = redis
        self._character_service = character_service

    # ── Stage helpers ─────────────────────────────────────────────────────

    async def _resolve_world_and_config(self, world_id: str, scale: str) -> tuple:
        """Load world, resolve scale config, get material pack and wiki content.

        Returns:
            (world, config, material, wiki_chars_raw)
        """
        world = await self.world_service.get_world(world_id)
        if world is None:
            raise ValueError(f"World not found: {world_id}")

        config = SCALES.get(scale, SCALES[DEFAULT_SCALE])

        # 提取 wiki 角色+剧情内容（供缓存前缀使用）
        # Prefer new dedicated fields; fallback to wiki_text for old worlds
        _wc = world.source.wiki_characters
        wiki_chars_raw = _wc if isinstance(_wc, str) else ""
        # fallback: 老世界可能没有 wiki_characters 字段
        if (
            not wiki_chars_raw
            and isinstance(world.source.wiki_text, str)
            and world.source.wiki_text
        ):
            wiki_chars_raw = filter_wiki_content(world.source.wiki_text, characters=True)

        material = self.material_service.generate(world)

        return world, config, material, wiki_chars_raw

    async def _resolve_char_candidates(
        self,
        material,
        char_candidates: list[dict] | None,
        char_min: int,
    ) -> tuple[list[dict], int, int, int]:
        """Resolve character candidates from various sources and compute tier counts.

        Returns:
            (char_candidates, actual_count, core_count, supporting_count)
        """
        # 确定角色候选来源：优先使用传入的 char_candidates
        if char_candidates:
            # 使用 extraction 阶段产出的角色候选（含 name + tier）
            actual_count = len(char_candidates)
            wcd(f"[角色生成] 使用传入的角色候选: {actual_count} 个")
        else:
            # 向后兼容：从 material.world_elements 筛选角色类元素
            char_elements: list[Element] = [
                e for e in material.world_elements if "人物" in e.category or "角色" in e.category
            ]
            if char_elements:
                if char_min > 0:
                    char_elements = char_elements[:char_min]
                actual_count = len(char_elements)
                char_candidates = [
                    {"name": e.name, "tier": "extra", "brief": e.brief, "detail": e.detail}
                    for e in char_elements
                ]
                wcd(f"[角色生成] 从 elements 筛选角色候选: {actual_count} 个")
            else:
                # 无角色候选、也无角色类元素：不再凭空编造角色，直接判定 0 角色
                char_candidates = []
                actual_count = 0
                wcd("[角色生成] 无角色候选可用，跳过角色生成")

        # tier 分配：优先使用 char_candidates 中已有的 tier
        _has_preset_tiers = any(
            c.get("tier") in ("core", "supporting", "extra") for c in char_candidates
        )

        if _has_preset_tiers:
            # 使用 extraction 阶段 extract_characters 的分级结果
            core_count = sum(1 for c in char_candidates if c.get("tier") == "core")
            supporting_count = sum(1 for c in char_candidates if c.get("tier") == "supporting")
        else:
            core_count = max(1, round(actual_count * 0.2))
            supporting_count = max(1, round(actual_count * 0.3))

        def _assign_tier(idx: int) -> str:
            if _has_preset_tiers:
                return char_candidates[idx].get("tier", "extra")
            if idx < core_count:
                return "core"
            if idx < core_count + supporting_count:
                return "supporting"
            return "extra"

        # _assign_tier preserved for potential future use
        _ = _assign_tier  # noqa: F841

        return char_candidates, actual_count, core_count, supporting_count

    async def _generate_character_profiles(
        self,
        char_candidates: list[dict],
        wiki_chars_raw: str,
        config,
        world_id: str,
        scale: str,
        actual_count: int,
        core_count: int,
        supporting_count: int,
    ) -> list[dict]:
        """Generate character profiles via batched concurrent LLM calls.

        Returns:
            Deduplicated list of character dicts.
        """
        tier_detail_map = {
            "core": (
                "完整描写，用结构化 Markdown 呈现：按「背景/性格/外貌/心理」等简短标签分点撰写"
                "（标签可按角色实际情况调整），去掉过渡句和啰嗦连接词，直接罗列事实。"
                "detail 120-240字。"
                "detail 是 JSON 字符串字段，内部换行（分点/分段）必须使用 JSON 转义的 "
                "\\n 字符序列（反斜杠+n），禁止输出真实换行符，否则返回内容将无法解析。"
            ),
            "supporting": (
                "简要描写，去掉过渡句和啰嗦连接词，直接罗列关键特征，一段话概括，"
                "不加任何 Markdown 符号。detail 40-90字。"
            ),
            "extra": "仅姓名+身份/绰号+一句话。detail 10-24字。",
        }

        # ── Step 1：并发生成角色档案 ─────────────────────────────────────────
        wcd(
            f"[角色生成] Step 1: 并发生成角色档案 | 目标={actual_count} | "
            f"core={core_count} supporting={supporting_count} "
            f"extra={actual_count - core_count - supporting_count}"
        )
        step1_system_batch = (
            "你是一个角色档案批量生成器，根据世界观素材为多个角色批量生成档案。\n\n"
            "## 输出格式\n\n"
            "严格 JSON 数组，每个元素对应输入的一个角色，顺序与输入完全一致。\n\n"
            "每个元素结构（字段层级不可更改）：\n\n"
            "```json\n"
            '{"name":"角色原名","profile":{"brief":"一句话简介","detail":"详细描写"}}\n'
            "```\n\n"
            "⚠️ ## 严格要求\n\n"
            "1. 数组元素数量必须与输入角色数量完全相等，不多不少\n"
            "2. 每个角色的 **name** 必须与输入指定的名字完全一致，不可更改或翻译\n"
            "3. 直接输出 `[ ... ]`，不要 Markdown 代码块，不要包装对象\n"
            "4. detail 是 JSON 字符串字段，内部如需换行（结构化 Markdown 的分点/分段），"
            "必须使用 JSON 转义的 \\n 字符序列（反斜杠+n），"
            "禁止在字符串里直接输出真实换行符，否则返回内容将无法解析\n\n"
            "✅ ## 正确输出示例（3个角色，含 core 档多行结构化 detail 的正确转义）\n\n"
            "```json\n"
            "[\n"
            '  {"name":"角色A","profile":{"brief":"执着于复仇的流浪剑士",'
            '"detail":"因父亲被杀而立誓报仇，剑术精湛但性格孤僻，习惯以摸耳垂排解焦虑。"}},\n'
            '  {"name":"角色B","profile":{"brief":"刚入学的精灵族见习魔法师",'
            '"detail":"来自北境部落，对人类文明充满好奇。"}},\n'
            '  {"name":"角色C","profile":{"brief":"流亡的前王国将领",'
            '"detail":"**背景**：王国覆灭后隐姓埋名，靠佣兵生涯维生。\\n'
            "**性格**：外表冷硬，对旧部下极重情义。\\n"
            "**外貌**：左颊有一道剑疤，常年披深色斗篷。\\n"
            '**心理**：既悔恨未能守住王国，又恐惧再次背负责任。"}}\n'
            "]\n"
            "```\n\n"
            "上例中 角色C 的 detail 演示了多行结构化 Markdown 如何编码进一个 JSON 字符串："
            "每个换行处都是 \\n 转义字符，而不是真实换行符。\n\n"
            "❌ ## 错误格式（绝对禁止）\n\n"
            '- `{"characters": [...]}`  ← 禁止：不要包装对象，直接输出数组\n'
            "- ` ```json [...]``` `  ← 禁止：不要 Markdown 代码块\n"
            "- detail 内部出现真实换行符（按下回车产生的换行）← 禁止：必须写成 \\n 转义"
            + get_lang_hint()
        )

        characters: list[dict] = []
        char_lock = asyncio.Lock()

        # ── 批量角色生成（core/supporting/extra 均走批量路径）─────────────────
        # 预先从 wiki 角色文本中提取所有角色的段落
        # value = (section_text, wiki_canonical_name)
        wiki_sections: dict[str, tuple[str, str]] = {}
        if wiki_chars_raw:
            _all_names = [c["name"] for c in char_candidates]
            wiki_sections = _extract_wiki_sections(wiki_chars_raw, _all_names)
            wcd(
                f"[角色生成] wiki 段落匹配: "
                f"{len(wiki_sections)}/{len(_all_names)} 个角色找到对应段落"
            )

        async def _gen_chars_batch(batch_idx: int, batch: list[tuple[int, dict, str]]) -> None:
            n = len(batch)
            generated_names: set[str] = set()

            # 有效名：wiki 专属段落的原文名（保真）> LLM 候选名。
            # wm[1] 仅在该角色有专属段落（理想格式：首行即角色名）时才非空，
            # 名单/混合段落返回空 → 回退候选名，避免 100+ 角色共享同一首行名
            # 而被去重塌缩（判断见 _extract_wiki_sections）。
            effective_names: dict[str, str] = {}
            for _, cand, _ in batch:
                orig = cand["name"]
                wm = wiki_sections.get(orig)
                effective_names[orig] = wm[1] if wm and wm[1] else orig

            max_attempts = 2
            for attempt in range(max_attempts):
                char_descs = []
                for i, (_orig_idx, cand, tier) in enumerate(batch):
                    cname = effective_names[cand["name"]]
                    cbrief = cand.get("brief", "")
                    cdetail = cand.get("detail", "")
                    # 从 wiki 中截取的角色段落作为参考资料
                    wiki_match = wiki_sections.get(cand["name"])
                    wiki_ref_block = ""
                    if wiki_match:
                        wiki_ref_block = f"\n<wiki_reference>\n{wiki_match[0]}\n</wiki_reference>"
                    generation_requirement = (
                        f"{tier_detail_map[tier]}\n"
                        f"• name 必须固定为「{cname}」，不可更改或翻译\n"
                        "• brief 和 detail 体现该角色独有特征，禁止通用套话"
                    )
                    char_descs.append(
                        f'<character index="{i + 1}" name="{cname}" tier="{tier}">\n'
                        f"<known_info>"
                        f"<brief>{cbrief or '无'}</brief>"
                        f"<detail>{cdetail[:200] or '无'}</detail>"
                        f"</known_info>\n"
                        f"<generation_requirement>\n{generation_requirement}\n"
                        "</generation_requirement>"
                        f"{wiki_ref_block}\n"
                        "</character>"
                    )
                # 先列出角色名单（使用有效名，与 prompt body 一致）
                name_list = "、".join([effective_names[cand["name"]] for _, cand, _ in batch])
                prompt = (
                    f"请为以下 {n} 个角色分别生成档案："
                    f"{name_list}\n"
                    f"按顺序输出 JSON 数组（恰好 {n} 个元素）。\n\n"
                    + "\n\n".join(char_descs)
                    + f"\n\n⚠️ 重要提醒：你必须为以上全部 {n} 个角色生成档案，"
                    f"输出恰好 {n} 个元素的 JSON 数组。"
                )
                try:
                    res = await self.llm.complete_json(
                        step1_system_batch,
                        prompt,
                        max_tokens=config.max_tokens,
                        prefill="[",
                    )
                    # Unwrap nested dict wrappers (max 3 layers)
                    for _ in range(3):
                        if isinstance(res, dict):
                            # Try known wrapper keys first
                            found = False
                            for wrap_key in ("characters", "results", "items", "data"):
                                if isinstance(res.get(wrap_key), list):
                                    res = res[wrap_key]
                                    found = True
                                    break
                            if found:
                                break
                            # Fallback: find first list value
                            for v in res.values():
                                if isinstance(v, list):
                                    res = v
                                    found = True
                                    break
                            if found:
                                break
                        else:
                            break
                    if not isinstance(res, list):
                        # 如果返回的是单个角色对象，包装成数组
                        if isinstance(res, dict) and "name" in res and "profile" in res:
                            logger.info(
                                "[批量角色 b%d] attempt=%d 返回单个角色对象，"
                                "自动包装为数组 world=%s",
                                batch_idx,
                                attempt + 1,
                                world_id,
                            )
                            res = [res]
                        else:
                            logger.warning(
                                "[批量角色 b%d] attempt=%d 返回非list: %s, keys=%s world=%s",
                                batch_idx,
                                attempt + 1,
                                type(res).__name__,
                                list(res.keys())[:5] if isinstance(res, dict) else "N/A",
                                world_id,
                            )
                            continue
                    # 按名字匹配（防止 LLM 乱序输出）
                    name_to_item: dict[str, dict] = {}
                    for item in res:
                        if isinstance(item, dict):
                            n_key = (item.get("name") or "").strip()
                            if n_key:
                                name_to_item[n_key] = item
                    for orig_idx, cand, tier in batch:
                        cname = effective_names[cand["name"]]
                        if cname in generated_names:
                            continue
                        item = name_to_item.get(cname) or name_to_item.get(cname.strip())
                        if item and _validate_character(item):
                            item.setdefault("id", str(uuid.uuid4()))
                            item["tier"] = tier
                            async with char_lock:
                                characters.append(item)
                            generated_names.add(cname)
                            logger.info(
                                "[%d/%d] 角色生成成功(批量b%d): %s world=%s",
                                orig_idx + 1,
                                actual_count,
                                batch_idx,
                                cname,
                                world_id,
                            )
                        elif attempt + 1 < max_attempts:
                            # 非最后一次尝试的缺失：大概率下一轮重试补齐，
                            # 降级 DEBUG，避免"显示失败但其实成功了"的误报
                            logger.debug(
                                "[%d/%d] 批量b%d attempt=%d 缺失(待重试): %s world=%s",
                                orig_idx + 1,
                                actual_count,
                                batch_idx,
                                attempt + 1,
                                cname,
                                world_id,
                            )
                        else:
                            # 所有尝试用尽仍缺失：直接丢弃，不生成 fallback
                            logger.warning(
                                "[%d/%d] 批量b%d 最终缺失/验证失败(丢弃): %s world=%s",
                                orig_idx + 1,
                                actual_count,
                                batch_idx,
                                cname,
                                world_id,
                            )
                    if len(generated_names) == n:
                        return
                except Exception as e:
                    logger.warning(
                        "[批量角色 b%d] attempt=%d 异常: %s world=%s",
                        batch_idx,
                        attempt + 1,
                        e,
                        world_id,
                    )

            # 记录本批次丢弃的角色数
            discarded = n - len(generated_names)
            if discarded > 0:
                logger.warning(
                    "批量b%d 完成: 生成 %d/%d, 丢弃 %d 个角色 world=%s",
                    batch_idx,
                    len(generated_names),
                    n,
                    discarded,
                    world_id,
                )

        # ── 构建并发任务：core/supporting/extra 均分批 ────────────────────────
        _CHAR_BATCH_CORE = 15  # noqa: N806
        _CHAR_BATCH_SUPPORTING = 30  # noqa: N806
        _CHAR_BATCH_EXTRA = 40  # noqa: N806

        core_range = [(i, char_candidates[i], "core") for i in range(min(core_count, actual_count))]
        supporting_range = [
            (i, char_candidates[i], "supporting")
            for i in range(core_count, min(core_count + supporting_count, actual_count))
        ]
        extra_range = [
            (i, char_candidates[i], "extra")
            for i in range(core_count + supporting_count, actual_count)
        ]

        def _chunk(items: list, size: int) -> list[list]:
            return [items[i : i + size] for i in range(0, len(items), size)]

        core_batches_char = _chunk(core_range, _CHAR_BATCH_CORE)
        supporting_batches_char = _chunk(supporting_range, _CHAR_BATCH_SUPPORTING)
        extra_batches_char = _chunk(extra_range, _CHAR_BATCH_EXTRA)
        batch_char_tasks = [
            _gen_chars_batch(bi + 1, batch)
            for bi, batch in enumerate(
                core_batches_char + supporting_batches_char + extra_batches_char
            )
        ]

        logger.info(
            "开始并发生成角色: world=%s scale=%s target=%d (core批=%d, sup批=%d, extra批=%d)",
            world_id,
            scale,
            actual_count,
            len(core_batches_char),
            len(supporting_batches_char),
            len(extra_batches_char),
        )
        await asyncio.gather(*batch_char_tasks, return_exceptions=True)

        # 去重（并发时 LLM 可能生成同名角色）
        seen_names: set[str] = set()
        deduped: list[dict] = []
        for char in characters:
            norm = char.get("name", "").strip().lower()
            if norm not in seen_names:
                seen_names.add(norm)
                deduped.append(char)
        characters = deduped

        wcd(f"[角色生成] Step 1 完成 ✓ 生成={len(characters)} 个角色 (去重后)")
        logger.info("角色生成完毕: %d 个 world=%s", len(characters), world_id)

        return characters

    async def _generate_relations(
        self,
        characters: list[dict],
        world_id: str,
    ) -> tuple[list[dict], int]:
        """Three-stage relation generation (core x core, core x noncore, noncore x noncore).

        Returns:
            (relations, failed_rel_batches)
        """
        lang_hint = get_lang_hint()

        def _tier(c: dict) -> str:
            return c.get("tier") or ""

        core_chars = [c for c in characters if _tier(c) == "core"]
        # 非核心排序：supporting 在前（原序）+ extra 在后（原序）
        supporting_chars = [c for c in characters if _tier(c) == "supporting"]
        extra_chars = [c for c in characters if _tier(c) == "extra"]
        noncore_chars = supporting_chars + extra_chars

        # 分配全局代号 C1..Cn（所有角色统一，避免代号冲突）
        code_to_id = assign_code_names(characters)
        # 构建 id->code 反查表
        id_to_code: dict[str, str] = {v: k for k, v in code_to_id.items()}

        relations: list[dict] = []
        rel_lock = asyncio.Lock()
        failed_rel_batches = 0

        # 关系系统 prompt（三段共用）
        total_chars = len(characters)
        target_relations = total_chars * 2  # 目标：角色数量的 2 倍关系
        rel_system = (
            "你是作品角色关系判断器。根据角色档案，找出角色之间有意义的关系。\n\n"
            "## 判断依据（满足任一即可认为有关系）\n\n"
            "1. 角色档案中明确提到两人之间的互动、情感或关联\n"
            "2. 两人同属一个具体组织/社团，且档案中描述了该组织内成员的互动场景\n"
            '3. 一方的经历或动机明确涉及另一方（如"为了接近他""受她影响"）\n\n'
            "## 判为无关系的条件\n\n"
            "- 仅凭同校/同圈子，档案中完全没有两人交集的描述\n"
            "- 无任何依据，纯属推断\n\n"
            "## evidence_type 说明\n\n"
            "- **explicit**：依据来自档案对两人关系的直接描述\n"
            "- **inferred**：依据来自组织归属或情节推断\n\n"
            "**type** 必须体现真实关系性质（如：青梅竹马/单恋/社团伙伴/对手/师生），"
            "禁止写「同学」等零信息量词。\n\n"
            f"## 数量参考\n\n"
            f"本作品共 {total_chars} 个角色，建议找出约 {target_relations} 条关系"
            "（每个角色平均 2 条关系）。这是参考值，以实际内容为准，不要虚构关系。\n\n"
            "## 输出格式\n\n"
            "严格 JSON 数组，每个元素是一条关系。\n\n"
            "```json\n"
            '{"character_a": "代号(如C1)", "character_b": "代号(如C2)", '
            '"type": "关系类型(2-8字)", "description": "描述", '
            '"direction": "bidirectional或a_to_b或b_to_a", '
            '"evidence_type": "explicit或inferred"}\n'
            "```\n\n"
            "⚠️ ## 输出要求\n\n"
            "输出必须是 JSON 数组 `[ ... ]`，无论找到多少条关系：\n\n"
            "- 0 条关系 → `[]`\n"
            "- 1 条关系 → `[{...}]`\n"
            "- 多条关系 → `[{...}, {...}, ...]`\n\n"
            "绝对不要单独输出一个对象 `{}`，必须用数组包裹。\n"
            "直接输出 `[ ... ]`，不要 Markdown 代码块，不要包装对象。"
        ) + lang_hint

        # 构建非核心角色的 cacheable prefix（全局代号+档案，所有调用共享）
        noncore_blocks: list[str] = []
        noncore_code_set: set[str] = set()
        for char in noncore_chars:
            char_id = char.get("id", "")
            code = id_to_code.get(char_id, "")
            if not code:
                continue
            noncore_blocks.append(_char_with_code(char, code))
            noncore_code_set.add(code)
        noncore_block_str = "\n".join(noncore_blocks) if noncore_blocks else ""

        async def _exec_stage(
            stage_label: str,
            system: str,
            prompt: str,
            cacheable_prefix: str | None,
            valid_codes: set[str],
            max_tokens: int = 8192,
        ) -> None:
            """Execute one LLM call for a relation stage, resolve codes, append to relations."""
            nonlocal failed_rel_batches
            try:
                res = await self.llm.complete_json(
                    system=system,
                    prompt=prompt,
                    cacheable_system_prefix=cacheable_prefix,
                    max_tokens=max_tokens,
                    prefill="[",
                )
                # Unwrap common wrappers (max 2 layers of nested dicts)
                res = _unwrap_relation_list(res)
                if not isinstance(res, list):
                    if _is_single_relation_dict(res):
                        # 单条关系对象，无需重试，直接包装为数组
                        logger.info(
                            "[%s] 首次返回单个关系对象，自动包装为数组 world=%s",
                            stage_label,
                            world_id,
                        )
                        res = [res]
                    else:
                        logger.warning(
                            "[%s] 首次返回非list: %s, keys=%s, 重试 world=%s",
                            stage_label,
                            type(res).__name__,
                            list(res.keys())[:5] if isinstance(res, dict) else "N/A",
                            world_id,
                        )
                        # Retry with explicit "output array only" instruction
                        retry_system = (
                            system + "\n\n⚠️ 上次你输出了非数组格式。"
                            "这次必须直接输出 JSON 数组 [ ... ]，绝对不要单独输出对象 {}。"
                            "即使只有 1 条关系也要用数组包裹：[{...}]。"
                            "没有关系就输出 []。"
                        )
                        res = await self.llm.complete_json(
                            system=retry_system,
                            prompt=prompt,
                            cacheable_system_prefix=cacheable_prefix,
                            max_tokens=max_tokens,
                            prefill="[",
                        )
                        res = _unwrap_relation_list(res)
                        if not isinstance(res, list):
                            # 兜底：如果 dict 本身是合法关系对象，自动包装成数组
                            if _is_single_relation_dict(res):
                                logger.info(
                                    "[%s] 重试后返回单个关系对象，自动包装为数组 world=%s",
                                    stage_label,
                                    world_id,
                                )
                                res = [res]
                            else:
                                logger.warning(
                                    "[%s] 重试后仍非list: %s, keys=%s → 当作空列表 world=%s",
                                    stage_label,
                                    type(res).__name__,
                                    list(res.keys())[:5] if isinstance(res, dict) else "N/A",
                                    world_id,
                                )
                                return

                added = 0
                skipped = 0
                for item in res:
                    if not isinstance(item, dict):
                        continue
                    # Skip has_relation=false style entries
                    if item.get("has_relation") is False:
                        continue
                    rel = item.get("relation") if "relation" in item else item
                    if not isinstance(rel, dict):
                        continue
                    # Validate codes are in valid set
                    ca_code = rel.get("character_a", "")
                    cb_code = rel.get("character_b", "")
                    if ca_code not in valid_codes or cb_code not in valid_codes:
                        logger.warning(
                            "[%s] 丢弃无效代号关系: %s ↔ %s world=%s",
                            stage_label,
                            ca_code,
                            cb_code,
                            world_id,
                        )
                        skipped += 1
                        continue
                    # 丢弃自指关系（LLM 偶尔生成角色与自身的关系）
                    if ca_code == cb_code:
                        skipped += 1
                        continue
                    resolved = _resolve_relation_codes(rel, code_to_id)
                    if resolved is None:
                        logger.warning(
                            "[%s] 代号解析失败: %s ↔ %s world=%s",
                            stage_label,
                            ca_code,
                            cb_code,
                            world_id,
                        )
                        skipped += 1
                        continue
                    resolved.setdefault("id", str(uuid.uuid4()))
                    async with rel_lock:
                        relations.append(resolved)
                    added += 1

                logger.info(
                    "[%s] ✓ %d 条关系 (跳过 %d) world=%s",
                    stage_label,
                    added,
                    skipped,
                    world_id,
                )
            except Exception as e:
                failed_rel_batches += 1
                logger.warning("[%s] 调用失败: %s world=%s", stage_label, e, world_id)

        # 三个阶段互不依赖（各自的 prompt/valid_codes 不读取其他阶段的产出，
        # 写入 relations 由 rel_lock 保护），全部收集后一次性并行执行。
        stage_tasks: list[Coroutine[Any, Any, None]] = []

        # ── Stage 1: 核心角色内部 ──────────────────────────────────────────
        if len(core_chars) >= 2:
            wcd(f"[角色生成] Stage 1: 核心角色内部关系 | {len(core_chars)} 个核心角色")
            # Build prompt with global codes for core chars
            stage1_target = len(core_chars) * 2  # 核心角色之间通常关系更紧密
            stage1_lines = [
                f"以下 {len(core_chars)} 个核心角色，请找出它们之间所有有意义的关系。\n",
                f"💡 参考：核心角色之间通常关系紧密，建议找出约 {stage1_target} 条关系。\n",
            ]
            valid_codes_s1: set[str] = set()
            for char in core_chars:
                code = id_to_code.get(char.get("id", ""), "")
                if not code:
                    continue
                stage1_lines.append(_char_with_code(char, code))
                valid_codes_s1.add(code)
            stage1_prompt = "\n".join(stage1_lines)
            # Append output format hint
            stage1_prompt += (
                "\n\n请输出严格 JSON 数组。\n直接输出 [ ... ]，不要 Markdown 代码块，不要包装对象。"
            )
            stage_tasks.append(
                _exec_stage(
                    "Stage1-核心内部",
                    rel_system,
                    stage1_prompt,
                    None,
                    valid_codes_s1,
                    max_tokens=RELATION_MAX_TOKENS_CEILING,
                )
            )
        else:
            wcd(f"[角色生成] Stage 1 跳过 (核心角色数={len(core_chars)})")

        # ── Stage 2: 核心 × 非核心 ──────────────────────────────────────────
        if core_chars and noncore_chars:
            wcd(
                f"[角色生成] Stage 2: 核心×非核心 | "
                f"{len(core_chars)} 个核心 × {len(noncore_chars)} 个非核心"
            )

            async def _stage2_for_core(core_char: dict) -> None:
                core_code = id_to_code.get(core_char.get("id", ""), "")
                if not core_code:
                    return
                valid_codes = {core_code} | noncore_code_set
                stage2_target = max(2, len(noncore_chars) // len(core_chars))
                prompt_lines = [
                    f"以下是 1 个核心角色和 {len(noncore_chars)} 个非核心角色，"
                    "请找出核心角色与非核心角色之间所有有意义的关系。\n",
                    f"💡 参考：每个核心角色通常与 {stage2_target} 个非核心角色有关联。\n",
                    "【核心角色】",
                    _char_with_code(core_char, core_code),
                    "\n【非核心角色】",
                    noncore_block_str,
                    "\n请输出严格 JSON 数组。\n"
                    "直接输出 [ ... ]，不要 Markdown 代码块，不要包装对象。",
                ]
                prompt = "\n".join(prompt_lines)
                await _exec_stage(
                    f"Stage2-{core_char.get('name', '?')}",
                    rel_system,
                    prompt,
                    noncore_block_str,
                    valid_codes,
                    max_tokens=RELATION_MAX_TOKENS_CEILING,
                )

            stage_tasks.extend(_stage2_for_core(c) for c in core_chars)
        else:
            wcd(f"[角色生成] Stage 2 跳过 (core={len(core_chars)}, noncore={len(noncore_chars)})")

        # ── Stage 3: 非核心 × 非核心（动态批次）─────────────────────────────
        if len(noncore_chars) >= 2:
            batch_sizes = compute_batches(len(noncore_chars), PAIR_BUDGET)
            wcd(
                f"[角色生成] Stage 3: 非核心×非核心 | {len(noncore_chars)} 个角色, "
                f"{len(batch_sizes)} 批, P={PAIR_BUDGET}"
            )

            # Build non-core char→code mapping (global codes)
            noncore_code_map: dict[str, str] = {}  # char id → global code
            for char in noncore_chars:
                char_id = char.get("id", "")
                code = id_to_code.get(char_id, "")
                if code:
                    noncore_code_map[char_id] = code

            # Compute batch boundaries
            batches_info: list[tuple[int, int]] = []  # (start, end) indices
            offset = 0
            for bs in batch_sizes:
                batches_info.append((offset, offset + bs))
                offset += bs

            async def _stage3_for_batch(batch_start: int, batch_end: int, batch_index: int) -> None:
                batch_chars = noncore_chars[batch_start:batch_end]
                # Scope = all non-core − already processed (chars before batch_start)
                scope_chars = noncore_chars[batch_start:]  # not yet processed

                # Build prompt with global codes
                batch_lines: list[str] = []
                scope_lines: list[str] = []
                batch_codes: set[str] = set()
                scope_codes: set[str] = set()
                for char in batch_chars:
                    code = noncore_code_map.get(char.get("id", ""), "?")
                    batch_codes.add(code)
                    batch_lines.append(_char_with_code(char, code))
                for char in scope_chars:
                    code = noncore_code_map.get(char.get("id", ""), "?")
                    scope_codes.add(code)
                    scope_lines.append(_char_with_code(char, code))

                prompt = (
                    f"以下是 {len(batch_chars)} 个本批角色和 {len(scope_chars)} 个可选范围角色，"
                    "请找出本批角色与可选范围角色之间所有有意义的关系。\n\n"
                    f"💡 参考：{len(batch_chars)} 个本批角色通常能找出 "
                    f"{len(batch_chars)}-{len(batch_chars) * 2} 条关系"
                    "（每个角色至少 1 条，除非确实无交集）。"
                    "请尽量充分挖掘，不要遗漏明显的关系。\n\n"
                    "【本批角色（关系一端）】\n"
                    + "\n".join(batch_lines)
                    + "\n\n【可选范围角色（关系另一端）】\n"
                    + "\n".join(scope_lines)
                    + "\n\n⚠️ 重要：character_a 和 character_b 只能使用上述代号"
                    "（如 C1、C2），不要使用其他代号。\n\n"
                    "请输出严格 JSON 数组。\n"
                    "直接输出 [ ... ]，不要 Markdown 代码块，不要包装对象。"
                )
                valid_codes = batch_codes | scope_codes
                batch_label = ",".join(sorted(batch_codes))
                # 根据批次参数动态计算 max_tokens
                batch_max_tokens = _estimate_relation_max_tokens(
                    len(batch_chars), len(scope_chars), PAIR_BUDGET
                )
                await _exec_stage(
                    f"Stage3-batch[{batch_label}]",
                    rel_system,
                    prompt,
                    None,  # Stage3 不用 cacheable_prefix，避免泄露所有代号
                    valid_codes,
                    max_tokens=batch_max_tokens,
                )

            stage_tasks.extend(_stage3_for_batch(s, e, i) for i, (s, e) in enumerate(batches_info))
        else:
            wcd(f"[角色生成] Stage 3 跳过 (非核心角色数={len(noncore_chars)})")

        # 三个阶段的所有 LLM 调用一次性并行发出
        if stage_tasks:
            await asyncio.gather(*stage_tasks)
        if failed_rel_batches > 0:
            logger.warning(
                "关系生成: %d 批因 429/异常失败，部分关系可能缺失 world=%s",
                failed_rel_batches,
                world_id,
            )
        wcd(f"[角色生成] 关系生成阶段完成 ✓ {len(relations)} 条关系（去重前）")

        # 去重：双向关系用 frozenset（顺序无关），单向关系用 tuple（保留方向语义）
        dedup_seen: set[frozenset[str] | tuple[str, str, str]] = set()
        deduped_rels: list[dict] = []
        for rel in relations:
            ca, cb, direction = (
                rel.get("character_a"),
                rel.get("character_b"),
                rel.get("direction", "bidirectional"),
            )
            if not ca or not cb:
                logger.warning("关系生成: 跳过缺少角色的关系 %s", rel)
                continue
            if direction == "bidirectional":
                key: frozenset[str] | tuple[str, str, str] = frozenset((ca, cb))
            else:
                key = (ca, cb, direction)
            if key not in dedup_seen:
                dedup_seen.add(key)
                deduped_rels.append(rel)
        relations = deduped_rels

        for rel in relations:
            rel.setdefault("id", str(uuid.uuid4()))

        wcd(f"[角色生成] 关系生成完毕: {len(relations)} 条")
        logger.info("关系生成完毕: %d 条 world=%s", len(relations), world_id)

        return relations, failed_rel_batches

    async def _persist_results(
        self,
        world,
        world_id: str,
        characters: list[dict],
        relations: list[dict],
    ) -> None:
        """Persist generated characters and relations to DB.

        Handles: user character preservation, relation reconnection,
        snapshot bumping, and version creation.
        """
        wcd("[角色生成] 写入数据库...")
        async with self.session.begin_nested():
            # 0. 查询用户角色
            user_char_id: str | None = world.user_character_id
            user_char_row = (
                await self.character_repo.get_by_id(user_char_id) if user_char_id else None
            )

            # 1. 快照用户角色当前参与的关系（记录对端名字，不记录 UUID）
            user_relation_snapshots: list[dict] = []
            if user_char_row is not None:
                existing_rels = await self.relation_repo.list_by_world(
                    world_id, character_id=user_char_id
                )

                # 同时构建当前角色名映射（查询现有角色）
                existing_chars = await self.character_repo.list_by_world(world_id)
                id_to_name: dict[str, str] = {c.id: c.name for c in existing_chars}

                for rel in existing_rels:
                    other_id = (
                        rel.character_b if rel.character_a == user_char_id else rel.character_a
                    )
                    other_name = id_to_name.get(other_id)
                    if other_name:
                        user_relation_snapshots.append(
                            {
                                "other_name": other_name,
                                "type": rel.type,
                                "description": rel.description,
                                "direction": rel.direction,
                                # whether user char was character_a or character_b
                                "user_is_a": rel.character_a == user_char_id,
                            }
                        )
            else:
                existing_chars = await self.character_repo.list_by_world(world_id)

            portrait_by_name = {c.name: c.portrait_url for c in existing_chars if c.portrait_url}

            # 2. 全删关系（外键约束：必须先于角色删除）
            await self.relation_repo.delete_all_by_world(world_id)

            # 3. 删非用户角色（用户角色 UUID 保持不变）
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
                if user_char_id:
                    await self.character_repo.delete_non_user_characters(world_id, user_char_id)
                else:
                    await self.character_repo.delete_all_by_world(world_id)

            # 4. 写入新 NPC（不含用户角色，用户角色已原地保留）
            for char_data in characters:
                if not char_data.get("portrait_url") and char_data.get("name") in portrait_by_name:
                    char_data["portrait_url"] = portrait_by_name[char_data["name"]]

            name_to_id: dict[str, str] = {}
            if characters:
                created = await self.character_repo.bulk_create(world_id, characters)
                for char in created:
                    name_to_id[char.name] = char.id

            # 用户角色 UUID 保持不变，直接加入 name_to_id 映射
            if user_char_row is not None:
                name_to_id[user_char_row.name] = user_char_id  # type: ignore[assignment]

            # 5. 创建 NPC 关系（UUID 映射）
            if relations:
                resolved = []
                for rel in relations:
                    r = dict(rel)
                    a, b = r.get("character_a"), r.get("character_b")
                    if isinstance(a, str) and a in name_to_id:
                        r["character_a"] = name_to_id[a]
                    if isinstance(b, str) and b in name_to_id:
                        r["character_b"] = name_to_id[b]
                    try:
                        uuid.UUID(r.get("character_a", ""))
                        uuid.UUID(r.get("character_b", ""))
                    except (ValueError, AttributeError):
                        continue
                    resolved.append(r)
                if resolved:
                    await self.relation_repo.bulk_create(world_id, resolved)

            # 6. 重连用户角色的旧关系（按名字匹配对端 NPC）
            if user_char_row is not None and user_relation_snapshots:
                reconnected = 0
                for snap in user_relation_snapshots:
                    other_name = snap["other_name"]
                    other_new_id = name_to_id.get(other_name)
                    if other_new_id is None:
                        logger.info(
                            "[角色生成] 用户关系重连: 对端 '%s' 在新 NPC 中未找到，丢弃 world=%s",
                            other_name,
                            world_id,
                        )
                        continue
                    # Restore with correct a/b orientation
                    if snap["user_is_a"]:
                        char_a_id = user_char_id
                        char_b_id = other_new_id
                    else:
                        char_a_id = other_new_id
                        char_b_id = user_char_id
                    await self.relation_repo.bulk_create(
                        world_id,
                        [
                            {
                                "character_a": char_a_id,
                                "character_b": char_b_id,
                                "type": snap["type"],
                                "description": snap["description"],
                                "direction": snap["direction"],
                            }
                        ],
                    )
                    reconnected += 1
                logger.info(
                    "[角色生成] 用户关系重连: %d/%d 条 world=%s",
                    reconnected,
                    len(user_relation_snapshots),
                    world_id,
                )

            # 7. 标记快照 generation 脏位（事务内，commit 后外层调 publish_snapshot_dirty）
            #    必须在 create_snapshot 之前：create_snapshot 读取 snapshot_generation
            #    写入 synced_generation，若顺序颠倒会导致 synced_generation 落后一代，
            #    同步服务触发冗余重建。
            await bump_generation_sql(world_id, self.session)

            # 8. 创建版本快照（读取已 bump 的 snapshot_generation 写入 synced_generation）
            await self.version_service.create_snapshot(
                world_id,
                created_by="ai",
                summary=f"基于世界观生成 {len(characters)} 个角色及 {len(relations)} 条关系",
            )

            # 9. 更新角色/关系计数到 m1_worlds summary 字段
            from sqlalchemy import func, select

            from src.db.models import M1World, M2Character, M2Relation

            char_count_q = await self.session.execute(
                select(func.count())
                .select_from(M2Character)
                .where(M2Character.world_id == uuid.UUID(world_id))
            )
            rel_count_q = await self.session.execute(
                select(func.count())
                .select_from(M2Relation)
                .where(M2Relation.world_id == uuid.UUID(world_id))
            )
            world_row = await self.session.get(M1World, uuid.UUID(world_id))
            if world_row:
                world_row.character_summary = {"count": char_count_q.scalar() or 0}
                world_row.relationship_summary = {"count": rel_count_q.scalar() or 0}

    async def _persist_template_scale(self, world, world_id: str, scale: str) -> dict | None:
        """模板世界重新生成角色：直接套用模板对应档位的预设角色/关系。

        返回 None 时表示没有匹配到模板或该档位没有预设角色，调用方应回退到
        常规的 LLM 候选解析流程。
        """
        tpl = next((t for t in list_templates() if t.title == world.source.title), None)
        if tpl is None:
            return None
        scale_data = tpl.scales.get(scale)
        if not scale_data or not scale_data.characters:
            return None

        characters = [
            {
                "name": tc.name,
                "tier": tc.tier,
                "profile": {
                    "basic": {
                        "name": tc.name,
                        "gender": tc.gender,
                        "age": tc.age,
                        "occupation": tc.occupation,
                        "race": tc.race,
                        "tier": tc.tier,
                    },
                    "brief": tc.brief,
                    "detail": tc.detail,
                    "personality": tc.personality,
                    "speech_style": tc.speech_style,
                },
            }
            for tc in scale_data.characters
        ]
        relations = [
            {
                "character_a": tr.character_a,
                "character_b": tr.character_b,
                "type": tr.type,
                "direction": tr.direction,
                "description": tr.description,
            }
            for tr in scale_data.relations
        ]

        await self._persist_results(world, world_id, characters, relations)

        logger.info(
            "角色生成使用模板预设: template=%s scale=%s 角色=%d 关系=%d world=%s",
            tpl.id,
            scale,
            len(characters),
            len(relations),
            world_id,
        )
        return {
            "characters": len(characters),
            "relations": len(relations),
            "failed_rel_batches": 0,
        }

    async def generate(
        self,
        world_id: str,
        scale: str = DEFAULT_SCALE,
        char_candidates: list[dict] | None = None,
    ):
        llm_operation.set("角色生成")
        wcd(f"[角色生成] ═══ 开始 ═══ world_id={world_id} | scale={scale}")

        # Phase 1: Resolve world, config, material
        world, config, material, wiki_chars_raw = await self._resolve_world_and_config(
            world_id, scale
        )
        char_min, _ = config.char_range

        wcd(
            f"[角色生成] 素材包就绪 | "
            f"world_elements={len(material.world_elements)} | "
            f"char_min={char_min}"
        )
        # 调试日志
        logger.info(
            "DEBUG: world.elements=%d, material.world_elements=%d world=%s",
            len(world.elements),
            len(material.world_elements),
            world_id,
        )

        # 模板世界：直接复用模板该档位的预设角色/关系，不走 LLM 候选解析
        # （模板世界没有 wiki_characters，也没有"人物/角色"类元素，候选解析
        # 永远会失败；应该按档位取模板自带的角色，而不是尝试凭空生成）
        if world.source.type == "template":
            template_result = await self._persist_template_scale(world, world_id, scale)
            if template_result is not None:
                return template_result

        # Phase 2: Resolve character candidates and tier counts
        (
            char_candidates,
            actual_count,
            core_count,
            supporting_count,
        ) = await self._resolve_char_candidates(material, char_candidates, char_min)

        if actual_count == 0:
            # 无候选可用：直接跳过，不触碰数据库。_persist_results 会无条件删除
            # 现有角色/关系再写入新结果，如果这里继续往下走，0 个新角色会把已有的
            # （比如模板预置的）角色和关系全部清空且无法恢复。
            logger.warning(
                "角色生成跳过（无候选）: world=%s scale=%s，保留现有角色/关系不变",
                world_id,
                scale,
            )
            wcd(f"[角色生成] 无候选可用，跳过写库，保留现有数据 world_id={world_id}")
            return {"characters": 0, "relations": 0, "failed_rel_batches": 0}

        # Phase 3: Generate character profiles via batched LLM calls
        characters = await self._generate_character_profiles(
            char_candidates,
            wiki_chars_raw,
            config,
            world_id,
            scale,
            actual_count,
            core_count,
            supporting_count,
        )

        # Phase 4: Generate relations via three-stage LLM calls
        relations, failed_rel_batches = await self._generate_relations(characters, world_id)

        # Phase 5: Persist to DB (delete old, create new, reconnect user)
        await self._persist_results(world, world_id, characters, relations)

        wcd(f"[角色生成] 数据库写入完成 ✓ {len(characters)} 个角色, {len(relations)} 条关系")
        wcd(f"[角色生成] ═══ 完成 ═══ world_id={world_id}")
        logger.info(
            "角色直接写库完毕: %d 个角色, %d 条关系 world=%s",
            len(characters),
            len(relations),
            world_id,
        )
        return {
            "characters": len(characters),
            "relations": len(relations),
            "failed_rel_batches": failed_rel_batches,
        }
