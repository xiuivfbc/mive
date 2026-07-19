import re

from src.models.scale import DEFAULT_SCALE
from src.services.wiki_cleaner import clean_wiki_text

# ── 按档位分配的 wiki 正文截断预算（字符数） ──────────────────────────────────
WIKI_SECTION_BUDGETS: dict[str, dict[str, int]] = {
    "standard": {"characters": 15000, "plot": 8000, "world_setting": 9000},
    "detailed": {"characters": 50000, "plot": 8000, "world_setting": 9000},
    "deep": {"characters": 100000, "plot": 8000, "world_setting": 9000},
    "all": {"characters": 300000, "plot": 8000, "world_setting": 9000},
}
_DEFAULT_BUDGET = WIKI_SECTION_BUDGETS[DEFAULT_SCALE]

# ── 三组白名单关键词 ────────────────────────────────────────────────────────

_PATTERNS_CHARACTERS = [
    r"角色",
    r"人物",
    r"登场",  # 简体
    r"登場",  # 繁体/日文
    r"Characters",
    r"Cast",
    r"출연진",  # 韩文：出演阵容（影视）
    r"등장인물",  # 韩文：登场人物
    r"主要角色",
    r"配角",
    r"反派",
    r"主人公",
    r"Main",
]

_PATTERNS_PLOT = [
    r"剧情",  # 简体
    r"劇情",  # 繁体
    r"情节",  # 简体
    r"情節",  # 繁体
    r"故事",
    r"簡介",  # 故事簡介/作品簡介/劇情簡介
    r"简介",  # 简体同上
    r"Synopsis",
    r"Plot",
    r"Premise",  # 英文剧集常用
    r"あらすじ",
    r"ストーリー",  # 日文片假名
    r"줄거리",  # 韩文：剧情
    r"概要",
    r"Overview",
    r"Summary",
    r"结局",  # 简体
    r"結局",  # 繁体
    r"主线",  # 简体
    r"主線",  # 繁体
]

_PATTERNS_WORLD_SETTING = [
    r"设定",  # 简体
    r"設定",  # 繁体/日文
    r"世界观",  # 简体
    r"世界觀",  # 繁体
    r"세계관",  # 韩文：世界观
    r"用语",  # 简体
    r"用語",  # 繁体/日文
    r"用字",  # 繁中（火影忍者等）
    r"World",
    r"Setting",
    r"舞台",
    r"背景",
    r"Background",
    r"势力",
    r"Factions",
    r"组织",
    r"种族",  # 简体
    r"種族",  # 繁体
    r"地理",
]


def _build_whitelist_re(
    characters: bool = True,
    plot: bool = True,
    world_setting: bool = True,
) -> re.Pattern[str] | None:
    """根据三组布尔参数动态拼接正则，无任何组启用时返回 None。"""
    parts: list[str] = []
    if characters:
        parts.extend(_PATTERNS_CHARACTERS)
    if plot:
        parts.extend(_PATTERNS_PLOT)
    if world_setting:
        parts.extend(_PATTERNS_WORLD_SETTING)
    if not parts:
        return None
    return re.compile("|".join(parts), re.IGNORECASE)


# 设定组黑名单：匹配白名单但属于现实维度的标题（如「創作背景」）
_SETTING_BLACKLIST_RE = re.compile(r"创作|創作|制作|製作|幕后|幕後|Staff|Production", re.IGNORECASE)

# 角色/情节组黑名单：匹配白名单但属于真人身份介绍的标题（如「作者简介」）
_REAL_PERSON_BLACKLIST_RE = re.compile(
    r"作者|编剧|編劇|导演|導演|演员|演員|声优|聲優|主创|主創|原著|监制|監製",
    re.IGNORECASE,
)

# 向后兼容：全量正则（所有三组）
_WHITELIST_RE = _build_whitelist_re(True, True, True)

# 匹配 markdown 标题: ## 标题 或 ### 子标题（萌娘百科等用三级标题存放角色/剧情）
_HEADING_RE = re.compile(r"^## (.+)$", re.MULTILINE)
_ALL_HEADINGS_RE = re.compile(r"^(#{1,6}) (.+)$", re.MULTILINE)


def filter_wiki_content(
    raw_wiki: str,
    *,
    characters: bool = True,
    plot: bool = True,
    world_setting: bool = True,
) -> str:
    """
    按 markdown ## 标题白名单过滤，只保留匹配指定分组的 section。
    三组全 True 时行为与旧版完全一致（向后兼容）。
    三组全 False 时返回空字符串。
    导言（第一个 ## 前的内容）始终保留。
    """
    if not (characters or plot or world_setting):
        return ""

    whitelist_re = _build_whitelist_re(characters, plot, world_setting)
    if whitelist_re is None:
        return ""

    # 找到所有 ## 标题的位置和标题文本
    headings = list(_HEADING_RE.finditer(raw_wiki))
    if not headings:
        return raw_wiki

    result: list[str] = []

    for i, m in enumerate(headings):
        heading_text = m.group(1)
        if not whitelist_re.search(heading_text):
            continue
        # 黑名单：排除匹配设定白名单但属于现实维度的标题（如「創作背景」）
        if (
            _WORLD_SETTING_RE is not None
            and _WORLD_SETTING_RE.search(heading_text)
            and _SETTING_BLACKLIST_RE.search(heading_text)
            and not (_CHARACTERS_RE is not None and _CHARACTERS_RE.search(heading_text))
            and not (_PLOT_RE is not None and _PLOT_RE.search(heading_text))
        ):
            continue
        # 黑名单：排除匹配角色白名单但属于真人身份介绍的标题（如「演员表」）
        if (
            _CHARACTERS_RE is not None
            and _CHARACTERS_RE.search(heading_text)
            and _REAL_PERSON_BLACKLIST_RE.search(heading_text)
            and not (_WORLD_SETTING_RE is not None and _WORLD_SETTING_RE.search(heading_text))
            and not (_PLOT_RE is not None and _PLOT_RE.search(heading_text))
        ):
            continue
        # 黑名单：排除匹配情节白名单但属于真人身份介绍的标题（如「作者简介」）
        if (
            _PLOT_RE is not None
            and _PLOT_RE.search(heading_text)
            and _REAL_PERSON_BLACKLIST_RE.search(heading_text)
            and not (_CHARACTERS_RE is not None and _CHARACTERS_RE.search(heading_text))
            and not (_WORLD_SETTING_RE is not None and _WORLD_SETTING_RE.search(heading_text))
        ):
            continue
        # 截取当前标题到下一个同级标题之间的内容
        start = m.start()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(raw_wiki)
        result.append(raw_wiki[start:end])

    filtered = "".join(result)
    return clean_wiki_text(filtered)


# 各分组的标题匹配正则（用于 _split_wiki_headings 的优先级判定）
_CHARACTERS_RE = _build_whitelist_re(True, False, False)
_WORLD_SETTING_RE = _build_whitelist_re(False, False, True)
_PLOT_RE = _build_whitelist_re(False, True, False)


# 百度百科等非维基页面末尾的页脚噪音锚点：相关搜索推荐词条 / 新手上路帮助链接 /
# 版权行。三者取匹配到的最靠前位置，之后的内容整体截断。
# 注：「相关搜索」在真实样本中以 `###### 相关搜索`（六个井号）形式出现，不满足
# _HEADING_RE 只认严格 `## ` 的标题格式，因此单独用正则定位，不复用标题匹配机制。
# 维基百科正文几乎不会出现这几个锚点文本，故对现有维基流程是无操作（no-op）。
_FOOTER_ANCHOR_RE = re.compile(
    r"^#{0,6}\s*相关搜索\s*$"  # 相关搜索（可能带 markdown 标题前缀）
    r"|^新手上路\s*$"  # 页脚"新手上路"帮助链接
    r"|^©\s*\d{4}[^\n]*Baidu",  # 版权行，如 "©2024 Baidu"
    re.MULTILINE,
)


def _truncate_trailing_footer(raw_wiki: str) -> str:
    """截断百度百科等页面末尾的页脚噪音（相关搜索/新手上路/版权行）。

    依次匹配 _FOOTER_ANCHOR_RE 里的几个锚点，取最靠前的匹配位置整体截断；
    一个都没匹配到就原样返回，不做任何改动。
    """
    match = _FOOTER_ANCHOR_RE.search(raw_wiki)
    if match is None:
        return raw_wiki
    return raw_wiki[: match.start()]


def _split_wiki_headings(raw_wiki: str) -> dict[str, str]:
    """Pure split by ##/### headings into preamble / characters / world_setting / plot.

    No text transformation -- preserves all markup including links, images, templates.
    Recognizes both ## (level-2) and ### (level-3) headings.
    #### and deeper are ignored (too granular for grouping).

    Unmatched ### headings are treated as sub-sections of the preceding matched
    heading (e.g. ### 大好真真子 under ## 登場人物). Unmatched ## headings reset
    the current group boundary.

    Priority: characters > world_setting > plot.
    If no ## or ### headings exist, entire content goes to characters group.
    """
    raw_wiki = _truncate_trailing_footer(raw_wiki)
    headings = list(_ALL_HEADINGS_RE.finditer(raw_wiki))

    if not headings:
        return {
            "preamble": "",
            "characters": raw_wiki,
            "world_setting": "",
            "plot": "",
        }

    preamble = raw_wiki[: headings[0].start()]

    # First pass: classify each heading (match_obj, group_key_or_None, level)
    classified: list[tuple[re.Match[str], str | None, int]] = []
    for m in headings:
        level = len(m.group(1))
        heading_text = m.group(2)
        if level > 3:
            classified.append((m, None, level))
            continue

        key: str | None = None
        if (
            _CHARACTERS_RE is not None
            and _CHARACTERS_RE.search(heading_text)
            and not _REAL_PERSON_BLACKLIST_RE.search(heading_text)
        ):
            key = "characters"
        elif (
            _WORLD_SETTING_RE is not None
            and _WORLD_SETTING_RE.search(heading_text)
            and not _SETTING_BLACKLIST_RE.search(heading_text)
        ):
            key = "world_setting"
        elif (
            _PLOT_RE is not None
            and _PLOT_RE.search(heading_text)
            and not _REAL_PERSON_BLACKLIST_RE.search(heading_text)
        ):
            key = "plot"
        classified.append((m, key, level))

    characters_parts: list[str] = []
    world_setting_parts: list[str] = []
    plot_parts: list[str] = []
    current_key: str | None = None

    for idx, (m, key, level) in enumerate(classified):
        start = m.start()
        end = headings[idx + 1].start() if idx + 1 < len(headings) else len(raw_wiki)
        section = raw_wiki[start:end]

        if key is not None:
            current_key = key
            if key == "characters":
                characters_parts.append(section)
            elif key == "world_setting":
                world_setting_parts.append(section)
            elif key == "plot":
                plot_parts.append(section)
        else:
            if level == 2:
                current_key = None
            elif level == 3:
                if current_key == "characters":
                    characters_parts.append(section)
                elif current_key == "world_setting":
                    world_setting_parts.append(section)
                elif current_key == "plot":
                    plot_parts.append(section)

    return {
        "preamble": preamble,
        "characters": "".join(characters_parts),
        "world_setting": "".join(world_setting_parts),
        "plot": "".join(plot_parts),
    }


def split_wiki_grouped_raw(raw_wiki: str) -> dict[str, str]:
    """Public API: pure split by ## headings, zero text transformation.

    Returns dict with keys: preamble, characters, world_setting, plot.
    Content retains all markdown/wiki markup (links, images, templates, etc.).
    Used for link scanning before cleaning.
    """
    return _split_wiki_headings(raw_wiki)


def filter_wiki_content_grouped(raw_wiki: str) -> dict[str, str]:
    """Split by ## headings + unified clean via clean_wiki_text.

    Returns dict with keys: preamble, characters, world_setting, plot.
    Content is cleaned (markup removed, plain text).
    """
    groups = _split_wiki_headings(raw_wiki)
    return {k: clean_wiki_text(v) for k, v in groups.items()}


# 句末标点：中英文句号/感叹号/问号
_SENTENCE_END_RE = re.compile(r"[。！？.!?]")


def _truncate_at_boundary(text: str, budget: int, window: int = 300) -> str:
    """在 budget 附近寻找自然边界（段落分隔或句末标点）截断文本。

    优先寻找最近的 \n\n（段落分隔），找不到则寻找最近的句末标点；
    都找不到时直接在 budget 处硬切，避免边界查找失败导致行为不可预测。
    """
    # 防御 budget < 0：Python 负数切片 text[:-5] 会从末尾保留内容而非清空，
    # 与"截断到预算"的语义相悖，统一夹紧到 0（预算表当前恒为正值，此分支为兜底）。
    budget = max(0, budget)

    if len(text) <= budget:
        return text

    win_start = max(0, budget - window)
    win_end = min(len(text), budget + window)
    window_text = text[win_start:win_end]

    # 优先找最近的段落分隔 \n\n
    best_para_pos = -1
    best_para_dist = None
    for idx in range(len(window_text) - 1):
        if window_text[idx] == "\n" and window_text[idx + 1] == "\n":
            abs_pos = win_start + idx + 2  # 在分隔符之后截断
            dist = abs(abs_pos - budget)
            if best_para_dist is None or dist < best_para_dist:
                best_para_dist = dist
                best_para_pos = abs_pos
    if best_para_pos >= 0:
        return text[:best_para_pos]

    # 找不到段落分隔，寻找最近的句末标点
    best_punct_pos = -1
    best_punct_dist = None
    for m in _SENTENCE_END_RE.finditer(window_text):
        abs_pos = win_start + m.end()  # 在标点之后截断
        dist = abs(abs_pos - budget)
        if best_punct_dist is None or dist < best_punct_dist:
            best_punct_dist = dist
            best_punct_pos = abs_pos
    if best_punct_pos >= 0:
        return text[:best_punct_pos]

    # fallback：窗口内既无段落分隔也无句末标点，直接在 budget 处硬切，
    # 否则边界查找失败时行为不可预测（可能返回原文或抛异常）
    return text[:budget]


# ── 子页面黑名单过滤 ─────────────────────────────────────────────────────────

_SUBPAGE_NOISE_PATTERNS = [
    r"创作背景",
    r"參考",
    r"参考",
    r"References",
    r"注释",
    r"註釋",
    r"Notes",
    r"Footnotes",
    r"外部链接",
    r"外部連結",
    r"External links",
    r"See also",
    r"相关项目",
    r"相關項目",
    r"参见",
    r"參見",
    r"延伸阅读",
    r"延伸閱讀",
    r"Further reading",
    r"Sources",
    r"资料来源",
    r"資料來源",
    r"Bibliography",
    r"序言",
    r"前言",
    r"Introduction",
    r"争议",
    r"爭議",
    r"Controversy",
    r"批评",
    r"批評",
    r"Criticism",
    r"评价",
    r"評價",
    r"Reception",
    r"获奖",
    r"獲獎",
    r"Awards",
    r"出版",
    r"发行",
    r"發行",
    r"Publication",
    r"改编",
    r"改編",
    r"衍生",
    r"Adaptation",
    r"周边",
    r"周邊",
    r"Merchandise",
    r"游戏",
    r"遊戲",
    r"Game",
    r"动画",
    r"動畫",
    r"Anime",
    r"电影",
    r"電影",
    r"Film",
    r"真人",
    r"Live action",
    r"列表",
    r"List",
    r"目录",
    r"目錄",
    r"活动",
    r"活動",
    r"Event",
    r"反响",
    r"迴響",
    r"Impact",
    r"Legacy",
    r"文化影响",
    r"文化影響",
]

_SUBPAGE_NOISE_RE = re.compile(
    r"^##\s*(?:" + "|".join(_SUBPAGE_NOISE_PATTERNS) + r")",
    re.IGNORECASE | re.MULTILINE,
)


def filter_page_header_noise(raw_text: str) -> str:
    """过滤页面开头的噪音链接区域。

    Wiki 页面开头常有演员表、制作人员、参考文献等噪音链接，
    这些内容对角色/设定提取无价值，需要过滤掉。

    策略：找到第一个有意义的 ## 标题，从那里开始保留。
    如果没有 ## 标题，返回原文（无法判断）。
    """
    # 找到第一个 ## 标题的位置
    first_heading = _HEADING_RE.search(raw_text)
    if not first_heading:
        return raw_text

    # 检查标题前的内容是否是噪音（通常是目录、演员表等）
    header_content = raw_text[: first_heading.start()].strip()

    # 如果标题前内容很少（< 200字符），可能是正常前言，保留
    if len(header_content) < 200:
        return raw_text

    # 标题前内容较多，检查是否包含噪音关键词
    noise_keywords = [
        "演员",
        "演員",
        "Cast",
        "配音",
        "制作",
        "製作",
        "Staff",
        "导演",
        "導演",
        "Director",
        "编剧",
        "編劇",
        "Writer",
        "参考",
        "參考",
        "References",
        "注释",
        "註釋",
        "Notes",
        "外部链接",
        "外部連結",
        "External",
        "See also",
    ]
    for keyword in noise_keywords:
        if keyword in header_content:
            # 从第一个 ## 标题开始保留
            return raw_text[first_heading.start() :]

    return raw_text


def filter_subpage_content(raw_text: str) -> str:
    """黑名单过滤子页面内容，排除明显无用的段落。

    按 ## 标题分割，丢弃黑名单匹配的段落，保留其余内容。
    无 ## 标题时返回空字符串（无法判断内容类型，直接丢弃）。
    """
    headings = list(_HEADING_RE.finditer(raw_text))
    if not headings:
        return ""

    result: list[str] = []
    for i, m in enumerate(headings):
        heading_text = m.group(1)
        if _SUBPAGE_NOISE_RE.search(f"## {heading_text}"):
            continue
        start = m.start()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(raw_text)
        result.append(raw_text[start:end])

    return "".join(result)


# 匹配 markdown 格式的 wiki 内部链接: [显示文本](/wiki/页面名)
# 路径可能带 title 属性如 /wiki/%E7%BB "标题"，只捕获路径部分
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(/wiki/([^)\s]+)(?:\s+\"[^\"]*\")?\)")

# 匹配 markdown 格式的 {{main|...}} 等模板（markdownify 保留了原始模板语法）
_MD_TEMPLATE_RE = re.compile(
    r"\{\{(?:main|see also|further|详细|参见|主条目)\s*\|([^}]+)\}\}",
    re.IGNORECASE,
)


def extract_md_links_with_context(
    text: str, context_chars: int = 120, max_links: int = 60
) -> list[dict]:
    """从 markdown 格式的 wiki 内容中提取链接及上下文。

    识别两种链接格式：
    1. [显示文本](/wiki/页面名) — markdownify 转换后的 wiki 内部链接
    2. {{main|页面1|页面2}} — 保留的 wiki 模板链接（高优先级）

    每条: {link_text, display_text, context}。
    """
    # 1. 先提取 {{main|...}} 等模板链接（优先级最高）
    priority_entries: list[dict] = []
    priority_seen: set[str] = set()
    for m in _MD_TEMPLATE_RE.finditer(text):
        idx = m.start()
        ctx_start = max(0, idx - context_chars)
        ctx_end = min(len(text), m.end() + context_chars)
        # 去掉上下文中的链接和模板标记
        context = re.sub(r"\[[^\]]*\]\([^)]*\)|\{\{[^}]*\}\}", "", text[ctx_start:ctx_end]).strip()
        for part in m.group(1).split("|"):
            page = part.strip()
            if not page or page in priority_seen:
                continue
            priority_seen.add(page)
            priority_entries.append({"link_text": page, "display_text": page, "context": context})

    # 2. 提取 [显示文本](/wiki/页面名) 格式的链接
    results: list[dict] = []
    seen: set[str] = set(priority_seen)
    for m in _MD_LINK_RE.finditer(text):
        display = m.group(1).strip()
        page = m.group(2).strip()
        # URL decode
        from urllib.parse import unquote

        page = unquote(page)

        if page in seen:
            continue
        # 过滤锚点链接和非内容命名空间
        if page.startswith("#") or ":" in page:
            continue
        seen.add(page)

        idx = m.start()
        ctx_start = max(0, idx - context_chars)
        ctx_end = min(len(text), m.end() + context_chars)
        context = re.sub(r"\[[^\]]*\]\([^)]*\)|\{\{[^}]*\}\}", "", text[ctx_start:ctx_end]).strip()

        if len(results) + len(priority_entries) >= max_links:
            break
        results.append({"link_text": page, "display_text": display, "context": context})

    # {{main}} 类模板结果前置
    return priority_entries + results
