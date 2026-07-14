from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass

from src.debug_logger import wcd
from src.llm.base import LLMProvider, get_lang_hint, llm_operation
from src.models.scale import DEFAULT_SCALE, SCALES
from src.models.world import Element

FIXED_TABS = ["场所", "势力", "规则", "事件", "物品", "文化", "其他"]

logger = logging.getLogger(__name__)


@dataclass
class WikiSegment:
    """A chunk of wiki_characters text from a specific content source."""

    text: str
    source: str
    index: int


# ── prompts ────────────────────────────────────────────────────────────────────

_EXTRACT_CHARACTERS_PROMPT = """\
你是一个角色识别与分级专家。基于以上作品 wiki 中的角色相关资料，提取角色并按重要性分级。

目标作品：{title}
{target_desc}

## 要求

- 只列出真实存在于作品中的有名有姓角色，不得虚构
- 角色名必须与 wiki 原文中出现的名称完全一致（即 wiki 段落标题中的名字），不得翻译、缩写或改写
- 严格按照 wiki 中的出场顺序提取角色——wiki 惯例是先介绍主角和核心角色，越靠前越重要
- 按重要性分为三级，同时参考 wiki 介绍顺序判断：
  wiki 最前面出现的角色最可能是 core，其次是 supporting，再其次是 extra
  - **core**：贯穿作品始终、对剧情有决定性影响的角色，通常只有主角和少数关键人物，占总数的 10-20%
  - **supporting**：有独立支线或重要戏份的配角，通常占总数的 20-30%
  - **extra**：有名字但戏份有限的角色，通常占总数的 50-60%。包括：只在特定 arc 出场、
    没有独立支线、主要作为背景或工具人出现的角色。规模较小时百分比仅供参考，按实际重要性判断即可
- 数量要求：如实提取 wiki 中存在的角色即可，不要为了凑数而虚构或遗漏角色。{overflow_hint}
- **重要** 去重规则：每个角色只返回一个名称。如果同一角色有多个称呼，
  去掉称号/前缀（如"百兽""炎灾""旱灾""怪僧""女帝"等），保留角色的完整本名。

只返回 JSON 数组，格式：
```json
[{{"name": "wiki中的角色原名", "tier": "core"}},
 {{"name": "wiki中的角色原名2", "tier": "supporting"}}, ...]
```"""

_EXTRACT_CHARACTERS_SEGMENT_PROMPT = """\
你是一个角色识别与分级专家。基于以上作品 wiki 中的角色相关资料，提取角色并按重要性分级。

目标作品：{title}
{target_desc}

当前处理的是第 {segment_index}/{segment_total} 个内容片段，来源：{segment_source}

## 要求

- 只列出真实存在于作品中的有名有姓角色，不得虚构
- 角色名必须与 wiki 原文中出现的名称完全一致（即 wiki 段落标题中的名字），不得翻译、缩写或改写
- 严格按照 wiki 中的出场顺序提取角色——wiki 惯例是先介绍主角和核心角色，越靠前越重要
- **重要** 本片段仅包含作品的部分角色资料，请仅提取当前片段中明确描述的角色
- 按重要性分为三级，同时参考 wiki 介绍顺序判断：
  - **core**：贯穿作品始终、对剧情有决定性影响的角色
  - **supporting**：有独立支线或重要戏份的配角
  - **extra**：有名字但戏份有限的角色
- 数量要求：如实提取当前片段中存在的角色即可，不要虚构或遗漏。{overflow_hint}
- **重要** 去重规则：每个角色只返回一个名称。如果同一角色有多个称呼，
  去掉称号/前缀，保留角色的完整本名。

只返回 JSON 数组，格式：
```json
[{{"name": "wiki中的角色原名", "tier": "core"}},
 {{"name": "wiki中的角色原名2", "tier": "supporting"}}, ...]
```"""

_EXTRACT_ELEMENTS_PROMPT = """\
你是一个世界观元素提取专家。基于以上作品 wiki 中的设定和情节资料，提取非角色的世界观元素。

目标作品：{title}

## 要求

- 只提取真实存在于作品中的元素，不得虚构
- 不要列出任何角色（角色由单独流程处理）
- 按以下 7 个固定分类分层返回：**场所**、**势力**、**规则**、**事件**、**物品**、**文化**、**其他**
- 每个元素只需名称和一句话简介（50字以内）
- 各分类按实际内容填写，无相关内容时返回空数组
- 本次规模：{element_desc}

只返回 JSON 对象，7 个固定 key，每个 value 是对象数组：
```json
{{"场所": [{{"name": "名称", "brief": "简介"}}],
  "势力": [...], "规则": [...], "事件": [...],
  "物品": [...], "文化": [...], "其他": [...]}}
```"""

_DEDUP_CHARACTERS_SYSTEM = (
    "你是**作品角色分析专家**。你的任务是识别角色列表中的重复角色"
    "——同一角色可能有多个不同的称呼（全名、简称、绰号、称号等）。只返回合法的 JSON 对象。"
)

_DEDUP_CHARACTERS_PROMPT = """\
目标作品：{title}

以下是作品中提取的角色列表（代号 → 角色名）：
{code_list}

请识别其中指代同一角色的不同称呼。

## 筛选原则

1. 如果同一角色有全名和简称/绰号，保留全名（最完整的那个）
2. 如果无法确定哪个是全名，保留最常用、最广为人知的称呼
3. 只删除确实与另一角色重复的条目，不确定的宁可保留

## 返回格式

严格 JSON 对象：

```json
{{"duplicates": ["C3", "C5"]}}
```

其中 **duplicates** 数组列出应删除的角色代号。如果没有重复角色，返回 {{"duplicates": []}}。"""

_GENERATE_TAB_PROMPT = """请为以下元素生成详细介绍。
参考下方 wiki 资料，为每个元素撰写基于原作的介绍（不得虚构 wiki 中不存在的设定）。
detail 去掉过渡句和多余的连接词，直接罗列事实，不加 Markdown 符号。

## 本批次目标元素

{names}

对每个元素返回：**name**（原名）、**detail**（详细描述，50-150字）、**category**（固定为元素对应的类别）
只返回 JSON 数组。"""


def _format_element_with_tab(name: str, tab: str) -> str:
    """格式化元素名+类别标签，用于 prompt 中展示。"""
    return f"- {name}（类别：{tab}）"


_NON_CHAR_BATCH_SIZE = 20

REQUIRED_FIELDS = {"name", "detail"}

# 字段名映射：LLM 可能使用中文或变体字段名
# TODO(submodel): 字段名归一化的 LLM 兜底（判断类调用）可切到副模型（线 A 阶段二）。
#   本轮先只切 select_participants 验证回退链，此处暂不切。
_FIELD_ALIASES: dict[str, set[str]] = {
    "name": {"name", "名称", "名字", "title"},
    "brief": {"brief", "简介", "摘要", "summary", "description"},
    "detail": {"detail", "详细", "描述", "details", "content", "详细描述"},
    "category": {"category", "分类", "类别", "type"},
}


class ExtractionService:
    _HEADING_RE = re.compile(r"^## (.+)$", re.MULTILINE)
    _SOURCE_BOUNDARY_RE = re.compile(r"---SOURCE_BOUNDARY:\s*(.+?)---")

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    # ── 公开 API ────────────────────────────────────────────────────────────────

    async def extract(
        self,
        title: str,
        author: str | None,
        description: str | None,
        scale: str = DEFAULT_SCALE,
        wiki_characters: str | None = None,
        wiki_plot: str | None = None,
        wiki_world_setting: str | None = None,
        ref_content: str | None = None,
        llm: LLMProvider | None = None,
    ) -> tuple[list[Element], list[dict]]:
        """元素提取主入口。返回 (elements, char_candidates)。

        elements 不含角色类型，角色候选作为独立中间结果传递给 generation 阶段。
        wiki_characters: 清洗后的角色 section。
        wiki_plot: 清洗后的剧情 section。
        wiki_world_setting: 清洗后的设定 section。
        llm: 可选 LLM 覆盖（BYOK 场景），为 None 时使用 self.llm。
        """
        t0 = time.monotonic()
        char_len = len(wiki_characters) if wiki_characters else 0
        plot_len = len(wiki_plot) if wiki_plot else 0
        setting_len = len(wiki_world_setting) if wiki_world_setting else 0
        ref_len = len(ref_content) if ref_content else 0
        wcd(
            f'[元素提取] ─── 开始 ─── title="{title}" | '
            f"author={author} | scale={scale} | "
            f"char={char_len} | plot={plot_len} | "
            f"setting={setting_len} | ref={ref_len}"
        )
        elements, char_candidates = await self._extract_pipeline(
            title,
            author,
            description,
            scale,
            ref_content,
            wiki_characters,
            wiki_plot,
            wiki_world_setting,
            llm=llm,
        )
        elapsed = time.monotonic() - t0
        wcd(
            f"[元素提取] ─── 完成 ─── {len(elements)} 个元素 + "
            f"{len(char_candidates)} 个角色候选 | 耗时={elapsed:.1f}s"
        )
        return elements, char_candidates

    async def extract_characters(
        self,
        wiki_characters: str | None,
        char_target: int,
        title: str,
        llm: LLMProvider | None = None,
        segments: list[WikiSegment] | None = None,
        max_tokens: int = 4096,
        char_max: int = 0,
    ) -> list[dict]:
        """从 wiki 角色资料中提取角色并分级。返回 [{"name": str, "tier": str}, ...]。"""
        t0 = time.monotonic()
        wcd(
            f'[extract_characters] 入口: title="{title}", char_target={char_target}, '
            f"wiki_len={len(wiki_characters) if wiki_characters else 0}, "
            f"segments={len(segments) if segments else 0}"
        )
        if not wiki_characters or len(wiki_characters) < 100:
            wcd("[extract_characters] 跳过: wiki_characters 为空或过短")
            return []

        effective_llm = llm or self.llm
        valid_tiers = {"core", "supporting", "extra"}

        if char_target == 0:
            target_desc = (
                "任务：提取 wiki 中所有有独立介绍段落的角色，不设数量上限。"
                "wiki 中每个以标题或独立段落介绍的角色都必须出现在结果中。"
            )
        else:
            target_desc = (
                f"目标数量：{char_target}-{char_max} 个角色（硬性要求，不得超过上限）"
                if char_max > 0
                else f"目标数量：{char_target} 个角色"
            )
            overflow_hint = "超出目标数量时，按出场顺序舍弃末尾角色。"

        if segments and len(segments) > 1:
            # Parallel segment extraction
            tasks = [
                self._extract_single_segment(
                    seg,
                    char_target,
                    title,
                    llm=effective_llm,
                    valid_tiers=valid_tiers,
                    segment_index=i,
                    segment_total=len(segments),
                    max_tokens=max_tokens,
                    char_max=char_max,
                )
                for i, seg in enumerate(segments)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            segment_results: list[list[dict]] = []
            for i, r in enumerate(results):
                if isinstance(r, BaseException):
                    logger.warning(f"Segment {i} extraction failed: {r}")
                    continue
                segment_results.append(r)
            validated = self._merge_segment_results(segment_results)
        else:
            # Original single-call logic
            prompt = _EXTRACT_CHARACTERS_PROMPT.format(
                title=title, target_desc=target_desc, overflow_hint=overflow_hint
            )
            validated = await self._do_extract_characters(
                prompt,
                llm=effective_llm,
                valid_tiers=valid_tiers,
                wiki_characters=wiki_characters,
                attempt=1,
                max_tokens=max_tokens,
            )
            # Retry if insufficient (char_target=0 means "all", retry if nothing returned)
            if (len(validated) < char_target) if char_target > 0 else (len(validated) == 0):
                wcd(f"[extract_characters] 角色不足: {len(validated)}/{char_target}，重试")
                retry_prompt = (
                    f"{prompt}\n\n"
                    f"⚠️ 重要提醒：你上次只提取了 {len(validated)} 个角色，"
                    f"但目标是 {char_target} 个。\n\n"
                    f"请再次仔细检查 wiki 资料，确保不遗漏任何有名有姓的角色"
                    f"（包括只在少数场景出现的配角）。"
                    f"如实返回你能找到的所有角色即可，不要为了凑数而虚构或提升角色等级。"
                )
                retry_result = await self._do_extract_characters(
                    retry_prompt,
                    llm=effective_llm,
                    valid_tiers=valid_tiers,
                    wiki_characters=wiki_characters,
                    attempt=2,
                    max_tokens=max_tokens,
                )
                if len(retry_result) > len(validated):
                    wcd(f"[extract_characters] 重试成功: {len(retry_result)} > {len(validated)}")
                    validated = retry_result

        # 角色去重：角色数量较多时，用 LLM 识别同一角色的不同称呼
        if len(validated) >= 50:
            validated = await self._deduplicate_characters(validated, title, llm=effective_llm)

        # Tier distribution enforcement (triggered by character count, not scale)
        if len(validated) > 20:
            validated = self._enforce_tier_distribution(validated)

        # Hard truncation to char_max
        if char_max > 0 and len(validated) > char_max:
            wcd(f"[extract_characters] 硬截断: {len(validated)} → {char_max}")
            validated = validated[:char_max]

        elapsed = time.monotonic() - t0
        tier_counts = {t: sum(1 for v in validated if v["tier"] == t) for t in valid_tiers}
        wcd(
            f"[extract_characters] 返回: {len(validated)} 个角色 "
            f"(core={tier_counts['core']} supporting={tier_counts['supporting']} "
            f"extra={tier_counts['extra']}) | 耗时={elapsed:.1f}s"
        )
        return validated

    # ── 角色提取辅助方法 ────────────────────────────────────────────────────────

    async def _do_extract_characters(
        self,
        prompt: str,
        *,
        llm: LLMProvider,
        valid_tiers: set[str],
        wiki_characters: str | None,
        attempt: int = 1,
        max_tokens: int = 4096,
    ) -> list[dict]:
        """Extract characters core logic. Extracted from extract_characters closure."""
        llm_operation.set("角色提取")
        system = (
            "你是**角色识别与分级专家**。只返回合法的 JSON 数组。"
            "角色名必须使用 wiki 原文，不得翻译；其他描述按用户语言输出。" + get_lang_hint()
        )
        kwargs: dict = dict(
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            prefill="[",
        )
        if wiki_characters:
            kwargs["cacheable_system_prefix"] = wiki_characters

        raw = await llm.complete_json(**kwargs)

        candidates: list[dict] = []
        if isinstance(raw, list):
            candidates = raw
        elif isinstance(raw, dict):
            for key in ("characters", "results", "items", "data"):
                if isinstance(raw.get(key), list):
                    candidates = raw[key]
                    break
            else:
                list_vals = [v for v in raw.values() if isinstance(v, list)]
                if list_vals:
                    candidates = list_vals[0]
        else:
            wcd(f"[extract_characters] attempt={attempt} LLM 返回非预期类型: {type(raw).__name__}")

        validated: list[dict] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("名称") or item.get("名字")
            tier = item.get("tier") or item.get("等级") or item.get("重要性")
            if not name or not isinstance(name, str):
                continue
            if tier not in valid_tiers:
                tier = "extra"
            validated.append({"name": name, "tier": tier})

        wcd(f"[extract_characters] attempt={attempt} 返回 {len(validated)} 个角色")
        return validated

    @staticmethod
    def _enforce_tier_distribution(chars: list[dict]) -> list[dict]:
        """根据位置强制修正层级分布。"""
        n = len(chars)
        if n <= 20:
            return chars
        valid_tiers = {"core", "supporting", "extra"}
        tier_counts = {t: sum(1 for c in chars if c["tier"] == t) for t in valid_tiers}
        extra_ratio = tier_counts["extra"] / n
        if extra_ratio >= 0.5:
            return chars
        target_extra = max(tier_counts["extra"], round(n * 0.6))
        need_demote = target_extra - tier_counts["extra"]
        if need_demote <= 0:
            return chars
        demoted = 0
        for i in range(n - 1, -1, -1):
            if demoted >= need_demote:
                break
            if chars[i]["tier"] == "supporting":
                chars[i]["tier"] = "extra"
                demoted += 1
        new_counts = {t: sum(1 for c in chars if c["tier"] == t) for t in valid_tiers}
        wcd(
            f"[extract_characters] 层级修正: 降级 {demoted} 个尾部 supporting→extra | "
            f"修正前 core={tier_counts['core']} "
            f"supporting={tier_counts['supporting']} "
            f"extra={tier_counts['extra']} → "
            f"修正后 core={new_counts['core']} "
            f"supporting={new_counts['supporting']} "
            f"extra={new_counts['extra']}"
        )
        return chars

    def _split_characters_segments(
        self, wiki_characters: str, source_label: str = "主链"
    ) -> list[WikiSegment]:
        """按 ---SOURCE_BOUNDARY--- 分隔符分割 wiki_characters 为多个 WikiSegment。

        每个 SOURCE_BOUNDARY 标记附带来源 URL，用于 segment.source 标识。
        主链（分隔符之前的内容）始终作为第一个 segment。
        """
        boundaries = list(self._SOURCE_BOUNDARY_RE.finditer(wiki_characters))
        if not boundaries:
            if len(wiki_characters.strip()) >= 100:
                return [WikiSegment(text=wiki_characters, source=source_label, index=0)]
            return []

        segments: list[WikiSegment] = []
        seg_idx = 0

        # 主链：分隔符之前的内容
        main_text = wiki_characters[: boundaries[0].start()].strip()
        if len(main_text) >= 100:
            segments.append(WikiSegment(text=main_text, source=source_label, index=seg_idx))
            seg_idx += 1

        # 子链：每个分隔符后到下一个分隔符之间的内容
        for i, m in enumerate(boundaries):
            source_url = m.group(1).strip()
            start = m.end()
            end = boundaries[i + 1].start() if i + 1 < len(boundaries) else len(wiki_characters)
            chunk = wiki_characters[start:end].strip()
            if len(chunk) < 100:
                continue
            # 从 URL 提取短标签（取最后的路径段或域名）
            source_label_text = self._url_to_short_label(source_url)
            segments.append(
                WikiSegment(
                    text=chunk,
                    source=source_label_text,
                    index=seg_idx,
                )
            )
            seg_idx += 1
        return segments

    @staticmethod
    def _url_to_short_label(url: str) -> str:
        """从 URL 提取短标签用于 segment.source 显示。"""
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            # 取路径最后一段作为标签
            path = parsed.path.rstrip("/")
            if path:
                last_segment = path.split("/")[-1]
                # 解码 URL 编码的字符
                from urllib.parse import unquote

                return unquote(last_segment)
            return parsed.netloc
        except Exception:
            return url[:50]

    async def _extract_single_segment(
        self,
        segment: WikiSegment,
        char_target: int,
        title: str,
        llm: LLMProvider,
        valid_tiers: set[str],
        segment_index: int,
        segment_total: int,
        max_tokens: int = 4096,
        char_max: int = 0,
    ) -> list[dict]:
        """从单个片段提取角色。"""
        target_desc = (
            f"目标角色数：约 {char_target}-{char_max} 个"
            if char_target > 0
            else "任务：提取当前片段中所有有独立介绍的角色，不设数量上限。"
        )
        overflow_hint = (
            f"（该片段角色可能较少，如实提取即可，总数不超过 {char_max} 个）"
            if char_target > 0
            else "逐一检查片段中的角色介绍，每个有独立介绍的角色都必须提取，不得遗漏。"
        )

        prompt = _EXTRACT_CHARACTERS_SEGMENT_PROMPT.format(
            title=title,
            target_desc=target_desc,
            segment_index=segment_index + 1,
            segment_total=segment_total,
            segment_source=segment.source,
            overflow_hint=overflow_hint,
        )

        return await self._do_extract_characters(
            prompt,
            llm=llm,
            valid_tiers=valid_tiers,
            wiki_characters=segment.text,
            attempt=1,
            max_tokens=max_tokens,
        )

    @staticmethod
    def _merge_segment_results(
        segment_results: list[list[dict]],
    ) -> list[dict]:
        """合并多个片段结果，按名去重，保留首次出现的 tier。"""
        seen_names: set[str] = set()
        merged: list[dict] = []
        for seg_result in segment_results:
            for char in seg_result:
                name = char["name"]
                if name not in seen_names:
                    seen_names.add(name)
                    merged.append(char)
        return merged

    async def _deduplicate_characters(
        self,
        chars: list[dict],
        title: str,
        *,
        llm: LLMProvider,
    ) -> list[dict]:
        """识别同一角色的不同称呼，删除重复条目。失败时返回原始列表。"""
        llm_operation.set("角色去重")
        t0 = time.monotonic()

        # 分配 C1..Cn 代号，构建 code→index 映射
        code_map: dict[str, int] = {}
        code_list_lines: list[str] = []
        for i, char in enumerate(chars):
            code = f"C{i + 1}"
            code_map[code] = i
            code_list_lines.append(f"{code}: {char['name']}")

        code_list = "\n".join(code_list_lines)
        prompt = _DEDUP_CHARACTERS_PROMPT.format(title=title, code_list=code_list)

        # LLM 调用，失败时重试一次
        raw = None
        for attempt in range(2):
            try:
                raw = await llm.complete_json(
                    system=_DEDUP_CHARACTERS_SYSTEM,
                    prompt=prompt,
                    max_tokens=1024,
                )
                break
            except Exception as e:
                if attempt == 0:
                    wcd(f"[角色去重] 第 1 次调用失败，重试 | error={e}")
                else:
                    elapsed = time.monotonic() - t0
                    wcd(f"[角色去重] LLM 调用失败，返回原始列表 | error={e} | 耗时={elapsed:.1f}s")
                    return chars

        # 解析返回值：兼容 dict 和 list
        duplicates_raw: list[str] = []
        if isinstance(raw, dict):
            dup_val = raw.get("duplicates")
            if isinstance(dup_val, list):
                duplicates_raw = [str(d) for d in dup_val]
            else:
                # 尝试其他 wrapper key
                for key in ("results", "items", "data"):
                    val = raw.get(key)
                    if isinstance(val, list):
                        duplicates_raw = [str(d) for d in val]
                        break
                else:
                    # 搜索值中的 list
                    list_vals = [v for v in raw.values() if isinstance(v, list)]
                    if list_vals:
                        duplicates_raw = [str(d) for d in list_vals[0]]
        elif isinstance(raw, list):
            duplicates_raw = [str(d) for d in raw]

        # 校验代号有效性
        valid_codes = [c for c in duplicates_raw if c in code_map]
        invalid_count = len(duplicates_raw) - len(valid_codes)
        if invalid_count > 0:
            wcd(f"[角色去重] 忽略 {invalid_count} 个无效代号")

        # 安全兜底：去重超过 50% 时返回原始列表
        if len(valid_codes) >= len(chars) * 0.5:
            elapsed = time.monotonic() - t0
            wcd(
                f"[角色去重] 去重比例过高 ({len(valid_codes)}/{len(chars)})，"
                f"返回原始列表 | 耗时={elapsed:.1f}s"
            )
            return chars

        if not valid_codes:
            elapsed = time.monotonic() - t0
            wcd(f"[角色去重] 无重复角色 | 耗时={elapsed:.1f}s")
            return chars

        # 过滤重复角色
        remove_indices = {code_map[c] for c in valid_codes}
        filtered = [char for i, char in enumerate(chars) if i not in remove_indices]
        removed_names = [chars[i]["name"] for i in sorted(remove_indices)]

        elapsed = time.monotonic() - t0
        wcd(
            f"[角色去重] 移除 {len(valid_codes)} 个重复角色: {removed_names} | "
            f"{len(chars)} → {len(filtered)} | 耗时={elapsed:.1f}s"
        )
        return filtered

    async def extract_elements(
        self,
        wiki_plot: str | None,
        wiki_world_setting: str | None,
        title: str,
        scale: str,
        llm: LLMProvider | None = None,
    ) -> dict[str, list[dict]]:
        """从 wiki 剧情+设定资料中提取非角色元素。"""
        t0 = time.monotonic()
        wiki_combined = "\n\n".join(filter(None, [wiki_world_setting, wiki_plot]))
        wcd(
            f'[extract_elements] 入口: title="{title}", scale={scale}, '
            f"wiki_combined_len={len(wiki_combined)}"
        )

        config = SCALES.get(scale, SCALES[DEFAULT_SCALE])
        llm_operation.set("元素提取")

        if scale == "all":
            element_desc = "全量提取，尽可能完整提取 wiki 中的所有元素，不设上限"
        else:
            element_min, element_max = config.element_range
            element_desc = (
                f"{config.label}，总共提取 {element_min}-{element_max} "
                f"个元素（硬性要求，不得超过上限）"
            )

        system = "你是**世界观元素提取专家**。只返回合法的 JSON 对象。" + get_lang_hint()
        prompt = _EXTRACT_ELEMENTS_PROMPT.format(title=title, element_desc=element_desc)
        kwargs: dict = dict(
            system=system,
            prompt=prompt,
            max_tokens=config.max_tokens,
        )
        if wiki_combined:
            kwargs["cacheable_system_prefix"] = wiki_combined

        effective_llm = llm or self.llm
        raw = await effective_llm.complete_json(**kwargs)

        # 处理返回值
        empty_result = {tab: [] for tab in FIXED_TABS}
        if isinstance(raw, dict):
            result: dict[str, list[dict]] = {}
            for tab in FIXED_TABS:
                items = raw.get(tab)
                if isinstance(items, list):
                    # 验证每项有 name 和 brief
                    validated = []
                    for item in items:
                        if isinstance(item, dict):
                            name = item.get("name") or item.get("名称") or item.get("名字")
                            brief = item.get("brief") or item.get("简介") or item.get("摘要")
                            if name and isinstance(name, str):
                                validated.append(
                                    {
                                        "name": name,
                                        "brief": brief if isinstance(brief, str) else "",
                                    }
                                )
                    result[tab] = validated
                else:
                    result[tab] = []
            # 硬截断：非 all 档位按 element_range[1] 上限截断
            if scale != "all":
                result = self._truncate_elements(result, config.element_range[1])
            elapsed = time.monotonic() - t0
            counts = ", ".join(f"{tab}={len(result[tab])}" for tab in FIXED_TABS)
            wcd(f"[extract_elements] 返回: {counts} | 耗时={elapsed:.1f}s")
            return result
        elif isinstance(raw, list):
            # 尝试按 FIXED_TABS 顺序映射
            wcd(f"[extract_elements] LLM 返回裸数组 (len={len(raw)})，尝试按顺序映射")
            if len(raw) == len(FIXED_TABS) and all(isinstance(item, list) for item in raw):
                result = {}
                for tab, items in zip(FIXED_TABS, raw, strict=True):
                    validated = []
                    for item in items:
                        if isinstance(item, dict):
                            name = item.get("name") or item.get("名称") or item.get("名字")
                            brief = item.get("brief") or item.get("简介") or item.get("摘要")
                            if name and isinstance(name, str):
                                validated.append(
                                    {
                                        "name": name,
                                        "brief": brief if isinstance(brief, str) else "",
                                    }
                                )
                    result[tab] = validated
                # 硬截断：非 all 档位按 element_range[1] 上限截断
                if scale != "all":
                    result = self._truncate_elements(result, config.element_range[1])
                elapsed = time.monotonic() - t0
                counts = ", ".join(f"{tab}={len(result[tab])}" for tab in FIXED_TABS)
                wcd(f"[extract_elements] 返回 (数组映射): {counts} | 耗时={elapsed:.1f}s")
                return result
            elapsed = time.monotonic() - t0
            wcd(f"[extract_elements] 无法映射裸数组，返回空 | 耗时={elapsed:.1f}s")
            return empty_result
        else:
            wcd(f"[extract_elements] LLM 返回非预期类型: {type(raw).__name__}")
            elapsed = time.monotonic() - t0
            wcd(f"[extract_elements] 返回全空 | 耗时={elapsed:.1f}s")
            return empty_result

    async def generate_details_batch(
        self,
        tab: str,
        names: list[str],
        wiki_content: str | None,
        brief_map: dict[str, str] | None = None,
        llm: LLMProvider | None = None,
    ) -> list[Element]:
        """分批并行生成 detail；wiki_content 作为可缓存前缀降低 token 成本。

        brief_map: 第一阶段产出的 {name: brief}，用于填充 Element.brief。
                   LLM 不再生成 brief，从 brief_map 中取。
        """
        wcd(
            f"[generate_details_batch] 入口: tab={tab}, names={len(names)}, "
            f"has_brief_map={brief_map is not None}"
        )
        if not names:
            wcd(f"[generate_details_batch] 跳过: tab={tab} 无元素")
            return []

        t0 = time.monotonic()
        llm_operation.set("分批生成")

        batches = [
            ("", names[i : i + _NON_CHAR_BATCH_SIZE])
            for i in range(0, len(names), _NON_CHAR_BATCH_SIZE)
        ]

        wcd(
            f"[generate_details_batch] tab={tab}, 批次数={len(batches)}, "
            f"批次明细={[f'{t}({len(b)})' for t, b in batches]}"
        )
        results = await asyncio.gather(
            *[
                self._run_batch(tab, tier, batch, wiki_content, brief_map, llm=llm)
                for tier, batch in batches
            ]
        )
        flat: list[Element] = []
        for r in results:
            flat.extend(r)
        elapsed = time.monotonic() - t0
        wcd(f"[generate_details_batch] 返回: tab={tab}, 元素数={len(flat)} (耗时 {elapsed:.1f}s)")
        return flat

    async def generate_details_unified(
        self,
        elements_with_tabs: list[tuple[str, str]],
        wiki_content: str | None,
        brief_map: dict[str, str] | None = None,
        llm: LLMProvider | None = None,
    ) -> list[Element]:
        """跨 tab 统一批量生成 detail。

        elements_with_tabs: [(name, tab), ...] 所有非角色元素合并列表。
        wiki_content: 作为可缓存前缀降低 token 成本。
        brief_map: 第一阶段产出的 {name: brief}，用于填充 Element.brief。
        """
        wcd(
            f"[generate_details_unified] 入口: 元素数={len(elements_with_tabs)}, "
            f"has_brief_map={brief_map is not None}"
        )
        if not elements_with_tabs:
            wcd("[generate_details_unified] 跳过: 无元素")
            return []

        t0 = time.monotonic()
        llm_operation.set("分批生成")

        # 统一分批，每批 _NON_CHAR_BATCH_SIZE 个
        batches = [
            elements_with_tabs[i : i + _NON_CHAR_BATCH_SIZE]
            for i in range(0, len(elements_with_tabs), _NON_CHAR_BATCH_SIZE)
        ]

        wcd(
            f"[generate_details_unified] 批次数={len(batches)}, "
            f"批次明细={[len(b) for b in batches]}"
        )
        results = await asyncio.gather(
            *[self._run_batch_unified(batch, wiki_content, brief_map, llm=llm) for batch in batches]
        )
        flat: list[Element] = []
        for r in results:
            flat.extend(r)
        elapsed = time.monotonic() - t0
        wcd(f"[generate_details_unified] 返回: 元素数={len(flat)} (耗时 {elapsed:.1f}s)")
        return flat

    # ── 私有实现 ────────────────────────────────────────────────────────────────

    @staticmethod
    def _truncate_elements(result: dict[str, list[dict]], max_total: int) -> dict[str, list[dict]]:
        """按 FIXED_TABS 顺序截断元素总数到 max_total。"""
        total = sum(len(result.get(tab, [])) for tab in FIXED_TABS)
        if total <= max_total:
            return result
        truncated: dict[str, list[dict]] = {}
        remaining = max_total
        for tab in FIXED_TABS:
            items = result.get(tab, [])
            if remaining <= 0:
                truncated[tab] = []
            elif len(items) <= remaining:
                truncated[tab] = items
                remaining -= len(items)
            else:
                truncated[tab] = items[:remaining]
                remaining = 0
        wcd(
            f"[_truncate_elements] 截断: {total} → {max_total} | "
            f"截断后={{{', '.join(f'{tab}={len(truncated[tab])}' for tab in FIXED_TABS)}}}"
        )
        return truncated

    async def _extract_pipeline(
        self,
        title: str,
        author: str | None,
        description: str | None,
        scale: str,
        ref_content: str | None,
        wiki_characters: str | None,
        wiki_plot: str | None,
        wiki_world_setting: str | None,
        llm: LLMProvider | None = None,
    ) -> tuple[list[Element], list[dict]]:
        """元素提取流水线。返回 (non_char_elements, char_candidates)。

        char_candidates 只包含 name + tier，不生成 brief/detail。
        流程：并行提取 → 串行生成详情（带 wiki 上下文，按档位截断）。
        """
        pipeline_start = time.monotonic()
        config = SCALES.get(scale, SCALES[DEFAULT_SCALE])

        # ── 阶段一：并行提取角色 + 元素（name+brief） ──
        wcd(f"[元素提取] 并行启动: 角色提取(char_target={config.char_target}) + 元素提取")
        t1 = time.monotonic()

        # 如果 wiki_characters 包含 ---SOURCE_BOUNDARY--- 分隔符（由子链接拼接产生），
        # 则按来源分段并行提取，不限档位
        boundaries = (
            list(self._SOURCE_BOUNDARY_RE.finditer(wiki_characters)) if wiki_characters else []
        )
        use_segments = len(boundaries) > 0
        if use_segments:
            # boundaries 非空隐含 wiki_characters 非空（见上方推导）
            assert wiki_characters is not None
            wcd(
                f"[元素提取] 分段提取: boundaries={len(boundaries)}, "
                f"wiki_chars={len(wiki_characters) if wiki_characters else 0}, "
                f"scale={scale}"
            )
            segments = self._split_characters_segments(wiki_characters)
            char_task = self.extract_characters(
                wiki_characters,
                config.char_target,
                title,
                llm=llm,
                segments=segments,
                max_tokens=config.max_tokens,
                char_max=config.char_range[1],
            )
        else:
            char_task = self.extract_characters(
                wiki_characters,
                config.char_target,
                title,
                llm=llm,
                max_tokens=config.max_tokens,
                char_max=config.char_range[1],
            )

        elem_task = self.extract_elements(wiki_plot, wiki_world_setting, title, scale, llm=llm)
        char_candidates, elem_plan = await asyncio.gather(char_task, elem_task)
        elem_counts = {t: len(elem_plan.get(t, [])) for t in FIXED_TABS}
        wcd(
            f"[元素提取] 并行完成 ✓ 角色={len(char_candidates)} | "
            f"元素={elem_counts} | "
            f"耗时={time.monotonic() - t1:.1f}s"
        )

        # ── 阶段二：串行生成详情（带 wiki 上下文） ──
        # 按档位阈值截断 wiki 内容（在段落边界截断）
        raw_wiki = "\n\n".join(filter(None, [wiki_world_setting, wiki_plot]))
        if raw_wiki and len(raw_wiki) > config.wiki_detail_threshold:
            cut = config.wiki_detail_threshold
            # 找截断点附近的段落边界（\n\n）
            boundary = raw_wiki.rfind("\n\n", 0, cut)
            if boundary > cut // 2:
                # 段落边界在阈值的后半段内，用它截断
                wiki_for_details = raw_wiki[:boundary]
            else:
                # 找不到合理段落边界，退回硬截断
                wiki_for_details = raw_wiki[:cut]
            wcd(
                f"[元素提取] wiki 截断: {len(raw_wiki)} → {len(wiki_for_details)} 字符 (阈值={cut})"
            )
        else:
            wiki_for_details = raw_wiki or None

        active_tabs = [t for t in FIXED_TABS if elem_plan.get(t)]
        wcd(f"[元素提取] 统一批量生成详情 | 参与tab={active_tabs}")

        # 合并所有 tab 的元素为统一列表，附带 tab 标签
        elements_with_tabs: list[tuple[str, str]] = []
        unified_brief_map: dict[str, str] = {}
        for tab in active_tabs:
            items = elem_plan[tab]
            for item in items:
                if isinstance(item, dict):
                    n = item.get("name", "")
                    b = item.get("brief", "")
                else:
                    n, b = str(item), ""
                if n:
                    elements_with_tabs.append((n, tab))
                    if b:
                        unified_brief_map[n] = b

        all_elements = await self.generate_details_unified(
            elements_with_tabs, wiki_for_details, unified_brief_map or None, llm=llm
        )
        elapsed = time.monotonic() - pipeline_start
        by_cat: dict[str, int] = {}
        for e in all_elements:
            by_cat[e.category] = by_cat.get(e.category, 0) + 1
        wcd(
            f"[元素提取] ─── 流水线完成 ─── 总元素={len(all_elements)} + "
            f"角色候选={len(char_candidates)} | 分布={by_cat} | 总耗时={elapsed:.1f}s"
        )
        return all_elements, char_candidates

    async def _run_batch(
        self,
        tab: str,
        tier: str,
        batch_names: list[str],
        wiki_content: str | None,
        brief_map: dict[str, str] | None = None,
        llm: LLMProvider | None = None,
    ) -> list[Element]:
        t0 = time.monotonic()
        wcd(f"[元素提取] _run_batch | tab={tab} tier={tier} names={batch_names}")
        names_str = "\n".join(f"- {n}" for n in batch_names)
        prompt = _GENERATE_TAB_PROMPT.format(names=names_str)

        # 批量大小 > 1 时需要更多 token 空间（3 角色 ≈ 6000-8000 tokens）
        effective_max = 8192 if len(batch_names) > 1 else 4096
        kwargs: dict = dict(
            system="你是**世界观元素生成专家**。只返回合法的 JSON 数组。" + get_lang_hint(),
            prompt=prompt,
            max_tokens=effective_max,
            prefill="[",
        )
        if wiki_content:
            kwargs["cacheable_system_prefix"] = wiki_content

        try:
            effective_llm = llm or self.llm
            raw = await effective_llm.complete_json(**kwargs)
        except Exception as e:
            elapsed = time.monotonic() - t0
            wcd(
                f"[元素提取] _run_batch LLM异常 ✗ tab={tab} tier={tier} "
                f"error={e} | 耗时={elapsed:.1f}s"
            )
            raise

        return self._parse_batch_result(raw, tab, brief_map, t0)

    async def _run_batch_unified(
        self,
        batch: list[tuple[str, str]],
        wiki_content: str | None,
        brief_map: dict[str, str] | None = None,
        llm: LLMProvider | None = None,
    ) -> list[Element]:
        """统一批次：batch 为 [(name, tab), ...]，prompt 中展示每个元素的类别标签。"""
        t0 = time.monotonic()
        names_str = "\n".join(_format_element_with_tab(name, tab) for name, tab in batch)
        wcd(f"[元素提取] _run_batch_unified | 大小={len(batch)} names={names_str[:200]}")
        prompt = _GENERATE_TAB_PROMPT.format(names=names_str)

        effective_max = 8192 if len(batch) > 1 else 4096
        kwargs: dict = dict(
            system="你是**世界观元素生成专家**。只返回合法的 JSON 数组。" + get_lang_hint(),
            prompt=prompt,
            max_tokens=effective_max,
            prefill="[",
        )
        if wiki_content:
            kwargs["cacheable_system_prefix"] = wiki_content

        try:
            effective_llm = llm or self.llm
            raw = await effective_llm.complete_json(**kwargs)
        except Exception as e:
            elapsed = time.monotonic() - t0
            wcd(f"[元素提取] _run_batch_unified LLM异常 ✗ error={e} | 耗时={elapsed:.1f}s")
            raise

        # 构建 name→tab 映射，用于 fallback category 赋值
        name_tab_map: dict[str, str] = {name: tab for name, tab in batch}
        return self._parse_batch_result(raw, None, brief_map, t0, name_tab_map)

    def _parse_batch_result(
        self,
        raw: dict | list,
        fallback_tab: str | None,
        brief_map: dict[str, str] | None,
        t0: float,
        name_tab_map: dict[str, str] | None = None,
    ) -> list[Element]:
        """解析 LLM 返回的批次结果为 Element 列表。

        fallback_tab: 单 tab 模式下的默认类别；统一模式下为 None。
        name_tab_map: 统一模式下 name→tab 映射，用于 fallback category。
        """
        if isinstance(raw, dict):
            wcd(f"[_parse_batch_result] LLM 返回 dict: keys={list(raw.keys())[:10]}")
            for key in ("elements", "items", "data", "results"):
                if isinstance(raw.get(key), list):
                    raw = raw[key]
                    break
            else:
                list_vals = [v for v in raw.values() if isinstance(v, list)]
                if list_vals:
                    raw = list_vals[0]
                elif raw:
                    first_val = list(raw.values())[0]
                    if isinstance(first_val, dict):
                        raw = list(raw.values())
                        wcd(f"[_parse_batch_result] dict-of-dicts 解包: 得到 {len(raw)} 项")
                    else:
                        raw = first_val if isinstance(first_val, list) else []
                else:
                    raw = []
        elif not isinstance(raw, list):
            wcd(f"[_parse_batch_result] LLM 返回非预期类型: type={type(raw).__name__}")

        def _normalize_item(item: dict) -> dict | None:
            result = {}
            for std_name, aliases in _FIELD_ALIASES.items():
                for alias in aliases:
                    if alias in item:
                        result[std_name] = item[alias]
                        break
            if not REQUIRED_FIELDS.issubset(result.keys()):
                return None
            return result

        elements: list[Element] = []
        skipped = 0
        _raw_type = type(raw).__name__
        _raw_len = len(raw) if isinstance(raw, (list, dict)) else 0
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                skipped += 1
                if skipped <= 3:
                    wcd(f"[_parse_batch_result] 跳过非 dict 项: type={type(item).__name__}")
                continue
            normalized = _normalize_item(item)
            if normalized is None:
                skipped += 1
                if skipped <= 3:
                    wcd(f"[_parse_batch_result] 跳过项(字段不全): keys={list(item.keys())[:8]}")
                continue
            elem_name = normalized["name"]
            # brief 优先从第一阶段的 brief_map 取
            elem_brief = ""
            if brief_map:
                elem_brief = brief_map.get(elem_name, "")
            if not elem_brief:
                elem_brief = normalized.get("brief", "")
            # category 解析：LLM 返回 > name_tab_map > fallback_tab
            elem_category = normalized.get("category", "")
            if not elem_category:
                if name_tab_map and elem_name in name_tab_map:
                    elem_category = name_tab_map[elem_name]
                elif fallback_tab:
                    elem_category = fallback_tab
            elements.append(
                Element(
                    id=f"elem_{uuid.uuid4().hex[:8]}",
                    category=elem_category,
                    name=elem_name,
                    brief=elem_brief,
                    detail=normalized["detail"],
                )
            )
        elapsed = time.monotonic() - t0
        wcd(
            f"[_parse_batch_result] 完成 | "
            f"生成={len(elements)} 跳过={skipped} | "
            f"raw_type={_raw_type} raw_len={_raw_len} | 耗时={elapsed:.1f}s"
        )
        return elements
