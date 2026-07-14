"""网页抓取与提取上下文过滤工具。"""

import logging
import os
import re
from html.parser import HTMLParser

import httpx

logger = logging.getLogger(__name__)


def _web_write_log(filename: str, content: str) -> None:
    logs_dir = "logs"
    if not os.path.isdir(logs_dir):
        return
    try:
        with open(os.path.join(logs_dir, filename), "w", encoding="utf-8") as f:
            f.write(content)
    except OSError:
        pass


class _TextExtractor(HTMLParser):
    """剥离 HTML 标签，提取正文段落。"""

    _SKIP_TAGS = {"script", "style", "nav", "footer", "head", "header", "aside"}

    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            text = data.strip()
            if len(text) > 10:
                self._parts.append(text)

    def get_text(self) -> str:
        raw = "\n".join(self._parts)
        return re.sub(r"\n{3,}", "\n\n", raw)


async def fetch_wiki_api_text(
    url: str, max_chars: int = 2_000_000, variant: str | None = None
) -> str:
    """通过 Wikipedia parse HTML API 抓取词条正文（含表格内容）。

    使用 action=parse&prop=text 获取渲染后的 HTML，再提取纯文本，
    避免 extracts+explaintext=1 丢弃表格的问题。
    variant 仅对 zh.wikipedia.org 有效（如 "zh-cn"）。
    """
    from urllib.parse import unquote, urlparse

    parsed = urlparse(url)
    path = unquote(parsed.path)
    # 匹配 /wiki/Xxx 或 /zh、/zh-cn、/zh-tw、/zh-hans、/zh-hk 等任意中文变体路径
    m = re.match(r"^/(?:wiki|zh(?:-[a-z]+)?)/(.+)$", path)
    if not m:
        return ""
    title = m.group(1).split("#")[0]

    api_url = f"https://{parsed.netloc}/w/api.php"
    params: dict = {
        "action": "parse",
        "page": title,
        "prop": "text",
        "format": "json",
        "redirects": "1",
        "disableeditsection": "1",
    }
    if variant:
        params["uselang"] = variant
    headers = {"User-Agent": "MIVE/1.0 (https://github.com/xiuivfbc/mive; bot)"}
    try:
        async with httpx.AsyncClient(
            timeout=15, follow_redirects=True, http2=False, trust_env=True
        ) as client:
            resp = await client.get(api_url, params=params, headers=headers)
            if resp.status_code != 200:
                logger.warning("Wikipedia API 返回 %d: %s", resp.status_code, url)
                return ""
            data = resp.json()
            html = data.get("parse", {}).get("text", {}).get("*", "")
            if not html:
                return ""
            from markdownify import markdownify as _md

            text = _md(html, heading_style="ATX", strip=["script", "style"])
            _web_write_log("wiki_api_markdown.txt", f"# URL: {url}\n\n{text}")
            return text[:max_chars]
    except Exception as e:
        logger.warning("Wikipedia API 抓取失败 %s: %s(%s)", url, type(e).__name__, e)
    return ""


async def fetch_wiki_raw_wikitext(url: str) -> str:
    """通过 Wikipedia API 获取原始 wiki markup（保留 [[链接]] 格式）。"""
    from urllib.parse import unquote, urlparse

    parsed = urlparse(url)
    path = unquote(parsed.path)
    m = re.match(r"^/(?:wiki|zh(?:-[a-z]+)?)/(.+)$", path)
    if not m:
        return ""
    title = m.group(1).split("#")[0]

    api_url = f"https://{parsed.netloc}/w/api.php"
    params = {
        "action": "query",
        "titles": title,
        "prop": "revisions",
        "rvprop": "content",
        "rvlimit": "1",
        "format": "json",
        "redirects": "1",
    }
    headers = {"User-Agent": "MIVE/1.0 (https://github.com/xiuivfbc/mive; bot)"}
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(api_url, params=params, headers=headers)
            if resp.status_code != 200:
                logger.warning("Wikipedia 原文 API 返回 %d: %s", resp.status_code, url)
                return ""
            pages = resp.json().get("query", {}).get("pages", {})
            for page in pages.values():
                revisions = page.get("revisions", [])
                if revisions:
                    return revisions[0].get("*", "")
    except Exception as e:
        logger.warning("Wikipedia 原文 API 抓取失败 %s: %s", url, e)
    return ""


_LANG_TO_WIKI = {
    "zh-CN": "zh",
    "zh-TW": "zh",
    "zh": "zh",
    "ja": "ja",
    "ko": "ko",
    "en": "en",
    "fr": "fr",
    "de": "de",
    "es": "es",
}


async def fetch_wiki_langlink(url: str, target_lang: str) -> str | None:
    """查询 Wikipedia langlinks API，返回同一词条在 target_lang 语言版本的 URL，找不到返回 None。"""
    from urllib.parse import unquote, urlparse

    parsed = urlparse(url)
    path = unquote(parsed.path)
    m = re.match(r"^/(?:wiki|zh(?:-[a-z]+)?)/(.+)$", path)
    if not m:
        return None
    title = m.group(1).split("#")[0]
    api_url = f"https://{parsed.netloc}/w/api.php"
    params = {
        "action": "query",
        "titles": title,
        "prop": "langlinks",
        "lllang": target_lang,
        "lllimit": "1",
        "format": "json",
        "redirects": "1",
    }
    headers = {"User-Agent": "MIVE/1.0 (https://github.com/xiuivfbc/mive; bot)"}
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(api_url, params=params, headers=headers)
            if resp.status_code != 200:
                return None
            pages = resp.json().get("query", {}).get("pages", {})
            for page in pages.values():
                for ll in page.get("langlinks", []):
                    if ll.get("lang") == target_lang:
                        linked_title = ll["*"].replace(" ", "_")
                        return f"https://{target_lang}.wikipedia.org/wiki/{linked_title}"
    except Exception as e:
        logger.warning("Wikipedia langlinks 查询失败 %s → %s: %s", url, target_lang, e)
    return None


async def fetch_wiki_qids(urls: list[str]) -> dict[str, str]:
    """批量查询 Wikipedia 词条的 Wikidata QID。返回 {url: qid}，查不到的不包含。"""
    from urllib.parse import unquote, urlparse

    # 按 wiki 域名分组，MediaWiki API 批量查询要求同域
    by_host: dict[str, list[tuple[str, str]]] = {}  # host → [(url, title)]
    for url in urls:
        parsed = urlparse(url)
        path = unquote(parsed.path)
        m = re.match(r"^/(?:wiki|zh(?:-[a-z]+)?)/(.+)$", path)
        if not m:
            continue
        title = m.group(1).split("#")[0]
        by_host.setdefault(parsed.netloc, []).append((url, title))

    result: dict[str, str] = {}
    headers = {"User-Agent": "MIVE/1.0 (https://github.com/xiuivfbc/mive; bot)"}
    for host, pairs in by_host.items():
        titles = "|".join(t for _, t in pairs)
        api_url = f"https://{host}/w/api.php"
        params = {
            "action": "query",
            "titles": titles,
            "prop": "pageprops",
            "ppprop": "wikibase_item",
            "format": "json",
            "redirects": "1",
        }
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(api_url, params=params, headers=headers)
                if resp.status_code != 200:
                    continue
                data = resp.json().get("query", {})
                # 处理标准化映射（下划线→空格、首字母大写等）
                normalize_map: dict[str, str] = {}
                for nm in data.get("normalized", []):
                    normalize_map[nm["from"]] = nm["to"]
                # 处理重定向映射
                redirect_map: dict[str, str] = {}
                for rd in data.get("redirects", []):
                    redirect_map[rd["from"]] = rd["to"]
                # 建立 title → qid 映射
                title_to_qid: dict[str, str] = {}
                for page in data.get("pages", {}).values():
                    qid = page.get("pageprops", {}).get("wikibase_item")
                    if qid:
                        title_to_qid[page["title"]] = qid
                # 回填到原始 URL
                for url, title in pairs:
                    normalized = normalize_map.get(title, title)
                    resolved = redirect_map.get(normalized, normalized)
                    if resolved in title_to_qid:
                        result[url] = title_to_qid[resolved]
        except Exception as e:
            logger.warning("Wikidata QID 批量查询失败 (host=%s): %s", host, e)
    return result


async def search_wiki_api(query: str, lang: str) -> str | None:
    """通过 Wikipedia 搜索 API 查找词条，返回最匹配的词条 URL，找不到返回 None。"""
    api_url = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": "3",
        "srnamespace": "0",
        "format": "json",
    }
    headers = {"User-Agent": "MIVE/1.0 (https://github.com/xiuivfbc/mive; bot)"}
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(api_url, params=params, headers=headers)
            if resp.status_code != 200:
                return None
            hits = resp.json().get("query", {}).get("search", [])
            if hits:
                title = hits[0]["title"].replace(" ", "_")
                return f"https://{lang}.wikipedia.org/wiki/{title}"
    except Exception as e:
        logger.warning("Wikipedia 搜索 API 失败 (lang=%s, query=%s): %s", lang, query, e)
    return None


async def fetch_page_text(url: str, max_chars: int = 6000) -> str:
    """抓取 URL 页面并返回纯文本（限长）。"""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MIVE/1.0)"}
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return ""
            extractor = _TextExtractor()
            extractor.feed(resp.text)
            text = extractor.get_text()
            return text[:max_chars]
    except Exception as e:
        logger.warning("抓取页面失败 %s: %s", url, e)
        return ""


# 不相关段落标题关键词（遇到这些标题后跳过该段落直到下一个标题）
_IRRELEVANT_SECTIONS = frozenset(
    [
        "制作",
        "staff",
        "工作人员",
        "制作人员",
        "制作团队",
        "制作组",
        "配音",
        "声优",
        "cast",
        "音乐",
        "原声带",
        "碟片",
        "发行",
        "出版",
        "商品",
        "周边",
        "参考资料",
        "注释",
        "参见",
        "参考文献",
        "脚注",
        "制作委员会",
        "播出",
        "播放",
        "收视率",
    ]
)

# 明显的制作人员条目行（"原作：XX"、"导演：XX" 等短行）
_STAFF_ROLES_RE = re.compile(
    r"^(原作|导演|总导演|系列导演|脚本|系列构成|人物设定|角色设定|音乐|"
    r"制作人|制片人|监制|监督|演出|系列监督|主题曲|OP|ED|片头曲|片尾曲|"
    r"原画|作画监督|美术监督|色彩设计|摄影监督|CG监督|"
    r"音响监督|音效|配乐|剪辑|编辑|出版社|出版|发行|漫画家|作画)[：:]\s*\S",
    re.IGNORECASE,
)

# 章节回目行：纯数字 + 亡/述标记，如 "001"、"003亡115述"、"002亡，029述"
_CHAPTER_REF_RE = re.compile(r"^\d{1,3}(?:[亡述、，,]\s*\d{0,3}[亡述]?)*\s*$")

# 值得保留的段落标题关键词
_RELEVANT_SECTIONS = (
    "角色",
    "人物",
    "登场",
    "剧情",
    "故事",
    "简介",
    "内容",
    "背景",
    "设定",
    "世界观",
)


class _UrlTextExtractor(HTMLParser):
    """解析任意 HTML 页面，strip 噪音元素，其余标签替换为空格，保留正文文本。

    除标签名黑名单外，还按 class/id 属性跳过 Wikipedia 特有噪音：
    编辑链接、脚注引用、导航框、目录、分类栏、缩略图说明等。
    """

    # 按标签名整体跳过
    _SKIP_TAGS = {"script", "style", "head", "noscript", "template", "sup"}

    # Wikipedia class/id 关键词：包含任一关键词的元素整体跳过
    _SKIP_CLASS_KW = frozenset(
        {
            "mw-editsection",  # [编辑] 按钮
            "reflist",  # 参考文献列表
            "references",  # <ol class="references">
            "reference",  # 行内脚注 <sup class="reference">
            "navbox",  # 底部导航框
            "catlinks",  # 分类链接栏
            "mw-jump-link",  # 跳转链接
            "toc",  # 目录
            "thumb",  # 图片缩略图容器（含 figcaption）
            "hatnote",  # 消歧义/参见提示行
            "mbox",  # 维护/警告模板框
            "ambox",  # 文章消息框（正在翻译/孤立条目等）
            "footer",  # 页脚
            "printfooter",  # 打印页脚
            "mw-hidden-catlinks",
            "mw-normal-catlinks",
        }
    )
    _SKIP_ID_KW = frozenset(
        {
            "toc",
            "catlinks",
            "footer",
            "mw-navigation",
            "mw-head",
            "mw-panel",
            "siteNotice",
        }
    )

    # HTML void 元素，永远没有对应的结束标签
    _VOID_TAGS = frozenset(
        {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }
    )

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        # 记录每个非 void 开始标签是否触发了跳过，用于在对应结束标签时正确减计数
        self._tag_stack: list[tuple[str, bool]] = []
        self._parts: list[str] = []

    def _should_skip_attrs(self, attrs: list) -> bool:
        attr_map = dict(attrs)
        cls = attr_map.get("class", "")
        eid = attr_map.get("id", "")
        for kw in self._SKIP_CLASS_KW:
            if kw in cls:
                return True
        for kw in self._SKIP_ID_KW:
            if kw in eid:
                return True
        return False

    def handle_starttag(self, tag, attrs):
        triggered = tag in self._SKIP_TAGS or self._should_skip_attrs(attrs)
        if tag not in self._VOID_TAGS:
            self._tag_stack.append((tag, triggered))
        if triggered:
            self._skip_depth += 1
        elif self._skip_depth == 0:
            self._parts.append(" ")

    def handle_endtag(self, tag):
        # 从栈顶向下找最近同名标签，匹配则弹出并更新计数
        for i in range(len(self._tag_stack) - 1, -1, -1):
            t, triggered = self._tag_stack[i]
            if t == tag:
                self._tag_stack.pop(i)
                if triggered and self._skip_depth > 0:
                    self._skip_depth -= 1
                break

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        raw = "".join(self._parts)
        raw = re.sub(r"[ \t]+", " ", raw)
        return re.sub(r"\n{3,}", "\n\n", raw).strip()


async def fetch_url_text(url: str, max_chars: int = 40000) -> str | None:
    """抓取任意网页文本，过滤噪音，截断超长内容。仅处理文字类网页。"""
    try:
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; WorldBot/1.0)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            raw_html = resp.text
    except Exception as e:
        logger.warning("抓取 URL 失败 %s: %s", url, e)
        return None

    extractor = _UrlTextExtractor()
    try:
        extractor.feed(raw_html)
    except Exception:
        pass
    text = extractor.get_text()

    filtered = filter_for_extraction(text)
    from src.services.wiki_cleaner import clean_wiki_text

    filtered = clean_wiki_text(filtered)
    if len(filtered) > max_chars:
        filtered = filtered[:max_chars]
    result = filtered if filtered.strip() else None
    return result


_LINK_NSK = frozenset(
    {
        "Wikipedia",
        "Wikipedia:",
        "Help:",
        "Template:",
        "Talk:",
        "User:",
        "Special:",
        "File:",
        "Category:",
        "Portal:",
        "Draft:",
        "MediaWiki:",
        "Module:",
        "模块:",
        "模板:",
        "用户:",
        "帮助:",
        "分类:",
        "特殊:",
        "草稿:",
        "维基百科:",
        "门户:",
        "讨论:",
    }
)


def extract_wiki_links_with_context(
    text: str, context_chars: int = 120, max_links: int = 30
) -> list[dict]:
    """从 wiki markup 文本中提取链接及上下文。

    解析 `[[Target|Text]]`/`[[Target]]` 格式，以及 {{main|...}}/{{see also|...}} 模板。
    {{main}} 类模板优先置顶。每条: {link_text, display_text, context}。
    """
    # 预先提取 {{main|...}}、{{see also|...}} 等模板中的页面名（高优先级）
    main_template_re = re.compile(
        r"\{\{(?:main|see also|further|详细|参见|主条目)\s*\|([^}]+)\}\}",
        re.IGNORECASE,
    )
    priority_entries: list[dict] = []
    priority_seen: set[str] = set()
    for m in main_template_re.finditer(text):
        idx = m.start()
        ctx_start = max(0, idx - context_chars)
        ctx_end = min(len(text), m.end() + context_chars)
        context = re.sub(r"\{\{[^}]*\}\}|\[\[[^\]]*\]\]", "", text[ctx_start:ctx_end]).strip()
        for part in m.group(1).split("|"):
            page = part.strip()
            if not page or page in priority_seen:
                continue
            ns, sep, _ = page.partition(":")
            if sep and f"{ns}:" in _LINK_NSK:
                continue
            priority_seen.add(page)
            priority_entries.append({"link_text": page, "display_text": page, "context": context})

    # 用 [...](...) 之外的 wiki markup 链接: [[Page|Text]] 或 [[Page]]
    link_re = re.compile(r"\[\[([^\[\]]+?)\]\]")

    # 先把所有 markup 链接替换为显示文本，得到"渲染后"的纯文本
    plain_parts: list[tuple[str, str]] = []  # (link_text, display_text)
    plain_chunks: list[str] = []
    last = 0
    for m in link_re.finditer(text):
        raw = m.group(1)
        # 处理 [[Target|Displayed]] → link_text=Target, display=Displayed
        if "|" in raw:
            link_text, display = raw.split("|", 1)
        else:
            link_text, display = raw, raw

        # 过滤非内容链接
        ns, sep, _ = link_text.partition(":")
        if sep and f"{ns}:" in _LINK_NSK:
            plain_chunks.append(text[last : m.start()])
            last = m.end()
            continue
        # 过滤以 # 开头的锚点
        if link_text.startswith("#"):
            plain_chunks.append(text[last : m.start()])
            last = m.end()
            continue

        plain_parts.append((link_text.strip(), display.strip()))
        plain_chunks.append(text[last : m.start()])
        plain_chunks.append(display)
        last = m.end()
    plain_chunks.append(text[last:])
    plain_text = "".join(plain_chunks)

    results: list[dict] = []
    seen: set[str] = set()
    for link_text, display in plain_parts:
        # 取第一个 display 在 plain_text 中的位置来截取上下文
        idx = plain_text.find(display)
        if idx < 0:
            continue
        start = max(0, idx - context_chars)
        end = min(len(plain_text), idx + len(display) + context_chars)
        context = plain_text[start:end].strip()
        # 检查上下文是否包含中文字符（说明是链接所在语言的正文）
        link_key = link_text
        if link_key in seen or link_key in priority_seen:
            continue
        seen.add(link_key)
        if len(results) >= max_links:
            break
        results.append(
            {
                "link_text": link_text,
                "display_text": display,
                "context": context,
            }
        )
    # {{main}} 类模板结果前置（去掉已在 results 中的重复项）
    return priority_entries + results


def resolve_wiki_link(link_text: str, base_url: str) -> str | None:
    """将 wiki 内部链接文本解析为完整 URL。
    base_url 是当前页面的 URL（如 https://zh.wikipedia.org/wiki/xxx）。
    返回完整 URL；如果 link_text 看起来是外部链接或无法解析，返回 None。
    """
    from urllib.parse import quote, urlparse

    parsed = urlparse(base_url)
    domain = parsed.netloc

    # 排除非内容命名空间
    ns, sep, _ = link_text.partition(":")
    if sep and f"{ns}:" in _LINK_NSK:
        return None

    safe_chars = "/:@!$&'()*+,;="
    wiki_path = quote(link_text.replace(" ", "_"), safe=safe_chars)

    # 普通内部链接
    return f"https://{domain}/wiki/{wiki_path}"


def filter_for_extraction(text: str) -> str:
    """
    过滤页面文本，移除制作人员/STAFF行及不相关段落，保留角色/剧情/背景相关内容。
    """
    lines = text.split("\n")
    result: list[str] = []
    skip_section = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            result.append(line)
            continue

        # 启发式标题检测：短行 + 不以正文标点结尾
        is_heading = len(stripped) <= 30 and stripped[-1] not in "。，、；：….,;:）)"
        if is_heading:
            lower = stripped.lower()
            if any(kw in lower for kw in _IRRELEVANT_SECTIONS):
                skip_section = True
                continue
            elif any(kw in stripped for kw in _RELEVANT_SECTIONS):
                skip_section = False

        if skip_section:
            continue

        # 跳过明显的制作人员条目行（如 "导演：山田太郎"）
        if _STAFF_ROLES_RE.match(stripped):
            continue

        # 跳过章节回目行（如 "001"、"003亡115述"）
        if _CHAPTER_REF_RE.match(stripped):
            continue

        result.append(line)

    return "\n".join(result)


async def search_moegirl_api(query: str) -> str | None:
    """搜索萌娘百科，返回第一个匹配词条的 URL，失败返回 None。"""
    api_url = "https://zh.moegirl.org.cn/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": 3,
        "srnamespace": "0",
        "format": "json",
    }
    headers = {"User-Agent": "MIVE/1.0 (https://github.com/mive; bot)"}
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(api_url, params=params, headers=headers)
            if resp.status_code != 200:
                return None
            data = resp.json()
            hits = data.get("query", {}).get("search", [])
            if hits:
                title = hits[0]["title"]
                return f"https://zh.moegirl.org.cn/{title}"
            return None
    except Exception as e:
        logger.warning("萌娘百科搜索失败 (query=%s): %s", query, e)
    return None


async def fetch_generic_wiki_text(url: str, max_chars: int = 200_000) -> str | None:
    """抓取任意百科/词条页面 HTML，转换为保留 `##` 标题层级的 markdown。

    用于非维基百科手动确认链接（如百度百科、萌娘百科等）在未命中搜索缓存时的
    抓取兜底。与 fetch_url_text 不同：这里必须保留标题结构，因为下游
    split_wiki_grouped_raw 靠正文里的 `## 标题` 行识别角色/剧情/世界观分组
    （见 src/services/wiki_filter.py），拿到无标题的纯文本会导致全部内容被
    归入"角色"组，世界观/剧情分组落空。
    """
    try:
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; WorldBot/1.0)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            raw_html = resp.text
    except Exception as e:
        logger.warning("通用百科抓取失败 %s: %s", url, e)
        return None

    from bs4 import BeautifulSoup
    from markdownify import markdownify as _md

    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    text = _md(str(soup), heading_style="ATX")
    text = text[:max_chars]
    return text if text.strip() else None
