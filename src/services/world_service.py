import asyncio
import logging
import os
import time
import uuid
from datetime import datetime

from fastapi import HTTPException

from src.debug_logger import wcd
from src.llm.base import LLMProvider, LLMQuotaExhaustedError, get_lang_hint, llm_operation
from src.models.scale import DEFAULT_SCALE
from src.models.templates import get_template
from src.models.templates import list_templates as _list_templates
from src.models.world import Element, WorldDoc, WorldMeta, WorldSource
from src.services.extraction_service import ExtractionService
from src.services.search_service import SearchService
from src.services.wiki_cleaner import clean_wiki_text
from src.services.wiki_filter import (
    _DEFAULT_BUDGET,
    WIKI_SECTION_BUDGETS,
    _truncate_at_boundary,
    extract_md_links_with_context,
    filter_page_header_noise,
    filter_subpage_content,
    filter_wiki_content_grouped,
    split_wiki_grouped_raw,
)
from src.utils.web import (
    _LANG_TO_WIKI,
    fetch_generic_wiki_text,
    fetch_url_text,
    fetch_wiki_api_text,
    resolve_wiki_link,
    search_moegirl_api,
    search_wiki_api,
)

logger = logging.getLogger(__name__)


def _safe_type_name(exc: object) -> str:
    """Safely get exception type name; handles edge cases where exc may be None."""
    try:
        return type(exc).__name__ if exc is not None else "NoneType"
    except Exception:
        return "Unknown"


def _ws_write_log(filename: str, content: str) -> None:
    """Write content to a log file in the logs directory."""
    logs_dir = "logs"
    if not os.path.isdir(logs_dir):
        return
    try:
        with open(os.path.join(logs_dir, filename), "w", encoding="utf-8") as f:
            f.write(content)
    except OSError:
        pass


_WIKI_NON_CONTENT_PREFIXES = (
    "/Template:",
    "/Talk:",
    "/User:",
    "/Help:",
    "/Wikipedia:",
    "/Special:",
    "/File:",
    "/Category:",
    "/Portal:",
    # moegirl 同类
    "/模板:",
    "/用户:",
    "/帮助:",
    "/分类:",
    "/特殊:",
)


def _filter_content_pages(results) -> list:
    """过滤掉 wiki Template/Talk/User/Help 等非内容页，保留正文条目页。"""

    def _is_content(r) -> bool:
        from urllib.parse import unquote, urlparse

        path = unquote(urlparse(r.url).path)
        return not any(seg in path for seg in _WIKI_NON_CONTENT_PREFIXES)

    return [r for r in results if _is_content(r)]


# 候选全文预览的纯技术性硬字符上限（非业务截断，仅防止极端超长页面拖垮前端/传输）
_WIKI_PREVIEW_MAX_CHARS = 80_000


def _extract_excerpt(
    raw_content: str | None, max_chars: int = 300, content: str | None = None
) -> str | None:
    """Extract a plain-text excerpt."""
    if not raw_content:
        return None
    grouped = filter_wiki_content_grouped(raw_content)
    for section_name in ("plot", "world_setting", "characters"):
        section = grouped.get(section_name, "")
        section = section.strip()
        if section:
            return section[:max_chars]
    cleaned = clean_wiki_text(raw_content)
    if not cleaned.strip():
        if content:
            return content[:max_chars]
        return None
    return cleaned[:max_chars]


class WorldService:
    def __init__(
        self,
        repo,
        extraction: ExtractionService | None,
        search: SearchService | None,
        llm: LLMProvider | None = None,
        sub_llm: LLMProvider | None = None,
    ):
        self.repo = repo
        self.extraction = extraction
        self.search = search
        self.llm = llm
        # 副模型（判断类调用：judge_fast_path）。None 时退回主模型。
        # BYOK 短路在 API 层经 EntitlementService.get_sub_llm 重新赋值此字段。
        self.sub_llm = sub_llm or llm

    async def _populate_event_index(
        self,
        world_id: str,
        elements: list[Element],
    ) -> int:
        """将世界创建时提取的事件元素写入 m26_event_index 索引。

        返回写入的事件数量。
        """
        from src.db.repositories.event_index_repo import EventIndexRepository

        event_elements = [e for e in elements if e.category == "事件"]
        if not event_elements:
            logger.debug("_populate_event_index | no event elements | world=%s", world_id)
            return 0

        event_index_repo = EventIndexRepository(self.repo.session)
        count = 0
        for elem in event_elements:
            brief = elem.brief or elem.detail or elem.name
            # 截断 brief 到 200 字，避免过长
            if len(brief) > 200:
                brief = brief[:200]
            await event_index_repo.add(
                world_id=uuid.UUID(world_id),
                event_name=elem.name,
                brief=brief,
                dissemination=0.5,  # 世界创建阶段无传播度数据，使用默认值
                core_participants=None,  # 角色尚未创建，无法关联参与者
            )
            count += 1

        logger.info(
            "_populate_event_index | populated %d event index entries | world=%s",
            count,
            world_id,
        )
        return count

    async def _generate_plot_summary_llm(
        self, title: str, author: str | None, plot_content: str | None, elements: list
    ) -> str:
        """用 LLM 生成一段简短的作品剧情/简介。plot_content is already cleaned."""
        llm_operation.set("剧情简介生成")
        if self.llm is None:
            return ""
        context_parts = []
        if plot_content:
            filtered = plot_content[:5000] if len(plot_content) > 5000 else plot_content
            if filtered.strip():
                context_parts.append(f"维基百科资料（剧情节选）：\n{filtered}")
        if elements:
            briefs = [f"- {e.name}：{e.brief}" for e in elements[:10] if e.brief]
            if briefs:
                context_parts.append("世界观元素：\n" + "\n".join(briefs))
        if context_parts:
            context = "\n\n".join(context_parts)
            author_part = f"（{author}）" if author else ""
            prompt = (
                f"## 任务\n\n"
                f"请根据以下资料，为《{title}》{author_part}"
                "写一段 **100-200字** 的故事简介，描述主要剧情脉络。\n\n"
                "## 要求\n\n"
                "- 语言简洁，不要分点列举，用自然段落叙述\n"
                "- 只返回简介正文，不要标题\n\n"
                "## 参考资料\n\n"
                f"{context}"
            )
        else:
            # 快速路径无素材时，凭作品名+作者生成简介
            author_part = f"，作者{author}" if author else ""
            prompt = (
                f"请为《{title}》{author_part}"
                "写一段100-200字的故事简介，描述主要剧情脉络。"
                "语言简洁，不要分点列举，用自然段落叙述。"
                "只返回简介正文，不要标题。"
            )
        try:
            result = await self.llm.complete(
                system="你是一个简洁的作品简介撰写助手。" + get_lang_hint(),
                prompt=prompt,
                max_tokens=400,
            )
            return result.content.strip() if result.content else ""
        except Exception:
            return ""

    async def _generate_common_sense_llm(
        self,
        wiki_plot: str | None,
        wiki_world_setting: str | None,
        title: str | None = None,
    ) -> str | None:
        """用 LLM 生成一段世界观常识概述（类似故事简介风格）。"""
        llm_operation.set("常识生成")
        if self.llm is None:
            return None
        context_parts = []
        if wiki_plot:
            filtered = wiki_plot[:5000] if len(wiki_plot) > 5000 else wiki_plot
            if filtered.strip():
                context_parts.append(f"剧情资料：\n{filtered}")
        if wiki_world_setting:
            ws = wiki_world_setting
            filtered = ws[:5000] if len(ws) > 5000 else ws
            if filtered.strip():
                context_parts.append(f"世界设定：\n{filtered}")
        if not context_parts:
            # 无素材：用标题让 LLM 自由发挥生成世界观底色
            if title and title.strip():
                system = (
                    "你是一个世界观创作助手。请根据以下作品名称，为其虚构世界观设定。\n\n"
                    "## 要求\n\n"
                    "- 创作一段该世界的常识背景——科技水平、魔法体系、社会制度、地理气候等\n"
                    "- 聚焦该世界中大多数角色都知道的常识性信息，不要涉及具体角色或剧情\n"
                    "- 去掉过渡句和多余的连接词，直接罗列事实\n"
                    "- 用结构化 Markdown 呈现：按实际涉及的维度"
                    "（如科技水平/社会制度/地理气候等）分简短小标题或分点罗列，"
                    "维度不固定，按素材实际情况决定\n"
                    "- common_sense 是一个 JSON 字符串字段，内部如需换行（分点/分段），"
                    "必须使用 JSON 转义的 \\n 字符序列（反斜杠+n），"
                    "禁止在字符串里直接输出真实换行符，否则返回内容将无法解析\n"
                    "- 200字以内" + get_lang_hint()
                )
                prompt = (
                    f"作品名称：{title.strip()}\n\n"
                    "请为该作品创作一段世界观常识背景。返回 JSON 格式（换行请使用 \\n 转义）：\n"
                    '```json\n{"common_sense": "### 科技水平\\n蒸汽机与初级电力普及。\\n\\n'
                    '### 社会制度\\n城邦联盟制，议会共治。"}\n```'
                )
                try:
                    result = await self.llm.complete_json(system, prompt)
                    if not isinstance(result, dict):
                        return None
                    raw = result.get("common_sense")
                    if not isinstance(raw, str) or not raw.strip():
                        return None
                    return raw.strip()
                except Exception:
                    logger.warning(
                        "_generate_common_sense_llm (title-only) failed, returning None",
                        exc_info=True,
                    )
                    return None
            return None
        context = "\n\n".join(context_parts)
        system = (
            "你是一个世界观分析助手。请根据以下作品资料，用一段话概括这个世界的常识背景。\n\n"
            "## 要求\n\n"
            "- 聚焦该世界中大多数角色都知道的常识性信息"
            "（如科技水平、魔法体系、社会制度、地理气候等）\n"
            "- 不要涉及只有少数角色才知道的秘密或隐情\n"
            "- 去掉过渡句和多余的连接词，直接罗列事实\n"
            "- 用结构化 Markdown 呈现：按实际涉及的维度分简短小标题或分点罗列，"
            "维度不固定，按素材实际情况决定\n"
            "- common_sense 是一个 JSON 字符串字段，内部如需换行（分点/分段），"
            "必须使用 JSON 转义的 \\n 字符序列（反斜杠+n），"
            "禁止在字符串里直接输出真实换行符，否则返回内容将无法解析\n"
            "- 200字以内\n"
            "- 如果该作品世界观与现实地球无显著差异，返回空字符串" + get_lang_hint()
        )
        prompt = (
            f"{context}\n\n"
            "请用一段话概括该世界的常识背景。返回 JSON 格式（换行请使用 \\n 转义）：\n"
            '```json\n{"common_sense": "### 科技水平\\n蒸汽机与初级电力普及。\\n\\n'
            '### 社会制度\\n城邦联盟制，议会共治。"}\n```'
        )
        try:
            result = await self.llm.complete_json(system, prompt)
            if not isinstance(result, dict):
                return None
            raw = result.get("common_sense")
            if not isinstance(raw, str) or not raw.strip():
                return None
            return raw.strip()
        except Exception:
            logger.warning("_generate_common_sense_llm failed, returning None", exc_info=True)
            return None

    async def _build_plot_summary(
        self, title: str, author: str | None, plot_content: str | None, elements: list
    ) -> str | None:
        """Build plot summary from cleaned plot_content; LLM fallback if empty."""
        if plot_content and plot_content.strip():
            return plot_content
        summary = await self._generate_plot_summary_llm(title, author, plot_content, elements)
        return summary or None

    _LANG_NAMES = {
        "zh": "中文",
        "en": "English",
        "ja": "日本語",
        "ko": "한국어",
        "fr": "français",
        "de": "Deutsch",
        "es": "español",
    }

    async def _localize_title(self, title: str, author: str | None, wiki_lang: str) -> str:
        """用 LLM 查询作品在目标语言下的通用名称。失败则返回原标题。"""
        llm_operation.set("标题本地化")
        if not self.llm:
            return title
        lang_name = self._LANG_NAMES.get(wiki_lang, wiki_lang)
        author_part = f"，作者：{author}" if author else ""
        system = (
            "## 任务\n\n"
            "只回复作品在目标语言中**最广为人知的名称**，不加任何标点或说明，不确定则原样输出。"
        )
        prompt = f"**作品**：{title}{author_part}\n**目标语言**：{lang_name}"
        try:
            resp = await self.llm.complete(system=system, prompt=prompt, max_tokens=500)
            localized = resp.content.strip().splitlines()[0].strip()
            # 去除 LLM 可能带上的书名号
            localized = localized.strip("《》「」『』[]【】")
            if localized:
                logger.info("LLM 本地化标题: %s → %s (lang=%s)", title, localized, wiki_lang)
                return localized
        except Exception as e:
            logger.warning("LLM 标题本地化失败: %s", e)
        return title

    # 语言代码到 Wikipedia 子域名的映射（用于构建 include_domains）
    _LANG_TO_WIKI_DOMAIN = {
        "zh-CN": "zh.wikipedia.org",
        "zh-TW": "zh.wikipedia.org",
        "zh": "zh.wikipedia.org",
        "ja": "ja.wikipedia.org",
        "ko": "ko.wikipedia.org",
        "en": "en.wikipedia.org",
        "fr": "fr.wikipedia.org",
        "de": "de.wikipedia.org",
        "es": "es.wikipedia.org",
    }

    async def _search_wiki(
        self,
        title: str,
        author: str | None,
        preferred_language: str = "zh-CN",
        work_language: str | None = None,
    ):
        """搜索维基百科，返回去重后的候选列表，最多 3 条。
        返回格式: [(url, lang, raw_content, page_title), ...]
        Tavily 可用时：按用户语言/作品语言/英文三个 Wikipedia 子域名限域搜索，max_results=5，
        查 Wikidata QID 去重 → 同 QID 优先用户语言 → 英文 → 其他。
        Tavily 不可用时：LLM 本地化标题后搜用户语言 Wikipedia，兜底英文，返回单条。
        """
        from src.utils.web import fetch_wiki_qids

        query = f"{title} {author}" if author else title
        wiki_lang = _LANG_TO_WIKI.get(preferred_language, "zh")

        if self.search:
            try:
                # 构建 include_domains：用户语言 + 作品语言 + 英文，去重
                domains: list[str] = []
                seen_domains: set[str] = set()
                for lang_key in (preferred_language, work_language, "en"):
                    if lang_key is None:
                        continue
                    domain = self._LANG_TO_WIKI_DOMAIN.get(lang_key)
                    if domain and domain not in seen_domains:
                        domains.append(domain)
                        seen_domains.add(domain)

                # 中文作品额外搜索百度百科和萌娘百科
                _is_chinese = (
                    preferred_language in ("zh-CN", "zh-TW", "zh")
                    or (work_language or "") in ("zh-CN", "zh-TW", "zh")
                )
                if _is_chinese:
                    if "baike.baidu.com" not in seen_domains:
                        domains.append("baike.baidu.com")
                        seen_domains.add("baike.baidu.com")
                    if "zh.moegirl.org.cn" not in seen_domains:
                        domains.append("zh.moegirl.org.cn")
                        seen_domains.add("zh.moegirl.org.cn")

                logger.debug(
                    "_search_wiki | Tavily search START | query=%s | domains=%s", query, domains
                )
                import asyncio as _asyncio
                import re as _re
                from urllib.parse import unquote, urlparse

                # 与 Tavily 并行发起 Wikipedia API 搜索+抓取（利用 Wikipedia 自身的重定向/别名机制）
                async def _wiki_api_fetch(q: str, lang: str):
                    url = await search_wiki_api(q, lang)
                    if not url:
                        return None, None, None
                    page_title = unquote(url.split("/wiki/")[-1]).replace("_", " ") or None
                    try:
                        raw_text = await fetch_wiki_api_text(url, max_chars=50000)
                        content = clean_wiki_text(raw_text) if raw_text else None
                    except Exception:
                        content = None
                    return url, page_title, content

                wiki_api_task = _asyncio.create_task(_wiki_api_fetch(query, wiki_lang))

                # 中文作品并行发起萌娘百科 API 搜索
                moegirl_api_task = None
                moegirl_api_url: str | None = None
                if _is_chinese:
                    async def _search_moegirl_api(q: str) -> str | None:
                        try:
                            return await search_moegirl_api(q)
                        except Exception:
                            return None
                    moegirl_api_task = _asyncio.create_task(_search_moegirl_api(query))

                raw = await self.search.search(
                    query, allowed_domains=domains, max_results=5, include_raw_content=True
                )
                wiki_api_url: str | None = None
                wiki_api_title: str | None = None
                wiki_api_content: str | None = None
                try:
                    wiki_api_url, wiki_api_title, wiki_api_content = await wiki_api_task
                except Exception as _e:
                    logger.debug("_search_wiki | wiki_api_task failed: %s", _e)

                if moegirl_api_task is not None:
                    try:
                        moegirl_api_url = await moegirl_api_task
                    except Exception as _e:
                        logger.debug("_search_wiki | moegirl_api_task failed: %s", _e)

                logger.debug("_search_wiki | Tavily raw results | count=%d", len(raw) if raw else 0)
                filtered = _filter_content_pages(raw)
                logger.debug(
                    "_search_wiki | After content page filtering | count=%d", len(filtered)
                )
                if not filtered and not wiki_api_url:
                    logger.info(
                        "_search_wiki | NO_CONTENT_RESULTS | query=%s | raw_count=%d",
                        query,
                        len(raw) if raw else 0,
                    )
                    return []

                # 构建候选列表：(url, lang, raw_content, clean_title, tavily_result)
                candidates: list[tuple[str, str, str | None, str | None, object]] = []
                for r in filtered:
                    found_lang = urlparse(r.url).netloc.split(".")[0]
                    clean_title = (
                        _re.sub(r"\s*[-–]\s*\S*[Ww]ikipedi\S*$", "", r.title or "").strip() or None
                    )
                    candidates.append((r.url, found_lang, r.raw_content, clean_title, r))

                # 萌娘百科 API 结果插入位置 1（Wikipedia API 结果之后）
                if moegirl_api_url:
                    moegirl_title = None
                    if "zh.moegirl.org.cn" in moegirl_api_url:
                        _parts = moegirl_api_url.split("/")
                        if _parts:
                            moegirl_title = _parts[-1].replace("_", " ")
                    candidates.insert(
                        1, (moegirl_api_url, wiki_lang, None, moegirl_title, None)
                    )
                    logger.debug(
                        "_search_wiki | moegirl_api prepended | url=%s | title=%s",
                        moegirl_api_url,
                        moegirl_title,
                    )

                # 把 Wikipedia API 结果插到头部（若 URL 不重复）；QID 去重会自动合并同一词条
                if wiki_api_url and wiki_api_url not in {c[0] for c in candidates}:
                    candidates.insert(
                        0, (wiki_api_url, wiki_lang, wiki_api_content, wiki_api_title, None)
                    )
                    logger.debug(
                        "_search_wiki | wiki_api prepended | url=%s | title=%s | has_content=%s",
                        wiki_api_url,
                        wiki_api_title,
                        bool(wiki_api_content),
                    )

                # 批量查 Wikidata QID 去重
                all_urls = [c[0] for c in candidates]
                logger.debug(
                    "_search_wiki | Querying Wikidata QIDs | candidate_count=%d", len(all_urls)
                )
                qid_map = await fetch_wiki_qids(all_urls)
                logger.debug(
                    "_search_wiki | QID mapping complete | qid_count=%d | no_qid_count=%d",
                    len([q for q in qid_map.values() if q.startswith("Q")]),
                    len([q for q in qid_map.values() if not q.startswith("Q")]),
                )

                seen_qids: dict[str, list[tuple[str, str, str | None, str | None, object]]] = {}
                for c in candidates:
                    qid = qid_map.get(c[0], c[0])  # 查不到 QID 的用 URL 当唯一键
                    seen_qids.setdefault(qid, []).append(c)

                logger.debug(
                    "_search_wiki | After QID deduplication | unique_qid_count=%d", len(seen_qids)
                )

                # 每个 QID 组内按语言偏好排序：用户语言 > 英文 > 其他
                def _lang_score(lang: str) -> int:
                    if lang == wiki_lang:
                        return 0
                    if lang == "en":
                        return 1
                    return 2

                deduped: list[tuple[str, str, str | None, str | None, object]] = []
                for qid, group in seen_qids.items():
                    group.sort(key=lambda c: _lang_score(c[1]))
                    deduped.append(group[0])
                    if len(group) > 1:
                        logger.debug(
                            "_search_wiki | QID group dedup | qid=%s | group_size=%d | "
                            "selected_lang=%s",
                            qid,
                            len(group),
                            group[0][1],
                        )

                # 取前 5 条
                results: list[tuple[str, str, str | None, str | None, object | None]] = []
                for url, lang, raw_content, clean_title, tavily_result in deduped[:5]:
                    logger.info(
                        "_search_wiki | CANDIDATE_SELECTED | url=%s | lang=%s | title=%s",
                        url,
                        lang,
                        clean_title or "(no_title)",
                    )
                    tavily_content = (
                        getattr(tavily_result, "content", None) if tavily_result else None
                    )
                    results.append((url, lang, raw_content, clean_title, tavily_content))
                logger.info(
                    "_search_wiki | TAVILY_RESULTS_FINAL | query=%s | result_count=%d",
                    query,
                    len(results),
                )
                return results
            except Exception as e:
                logger.warning("Tavily wikipedia 搜索失败，降级到 Wikipedia API: %s", e)

        # Tavily 不可用或失败：LLM 本地化标题后搜用户语言 Wikipedia，兜底英文
        localized = await self._localize_title(title, author, wiki_lang)
        for lang, search_query in ([(wiki_lang, localized)] if wiki_lang != "en" else []) + [
            ("en", query)
        ]:
            url = await search_wiki_api(search_query, lang)
            if url:
                logger.info(
                    "Wikipedia API 搜索命中: %s (lang=%s, query=%s)", url, lang, search_query
                )
                return [(url, lang, None, None, None)]

        return []

    async def check_wiki(
        self,
        title: str,
        author: str | None,
        preferred_language: str = "zh-CN",
        work_language: str | None = None,
    ) -> dict:
        """预检维基百科是否有该作品词条。
        返回 {found, results: [{url, lang, page_title, raw_content}]}。
        """
        logger.debug(
            "check_wiki START | title=%s | author=%s | preferred_language=%s | work_language=%s",
            title,
            author or "none",
            preferred_language,
            work_language or "none",
        )
        t_start = time.monotonic()

        wiki_results = await self._search_wiki(title, author, preferred_language, work_language)
        elapsed = time.monotonic() - t_start

        if not wiki_results:
            logger.info("check_wiki NO_RESULTS | title=%s | elapsed_sec=%.1f", title, elapsed)
            return {"found": False, "results": []}

        logger.info(
            "check_wiki RESULTS_FOUND | title=%s | count=%d | elapsed_sec=%.1f",
            title,
            len(wiki_results),
            elapsed,
        )

        items = []
        for url, lang, raw_content, page_title, tavily_content in wiki_results:
            items.append(
                {
                    "url": url,
                    "lang": lang,
                    "page_title": page_title,
                    "excerpt": _extract_excerpt(raw_content, content=tavily_content),
                }
            )

        return {"found": True, "results": items}

    async def fetch_wiki_full_preview(
        self,
        wiki_url: str,
        title: str | None = None,
        author: str | None = None,
        preferred_language: str = "zh-CN",
        work_language: str | None = None,
    ) -> tuple[str, bool] | None:
        if "wikipedia.org/wiki/" not in wiki_url:
            raw_text = await self._fetch_confirmed_wiki_text(
                wiki_url, title, author, preferred_language, work_language
            )
        else:
            raw_text = await fetch_wiki_api_text(wiki_url)
        if not raw_text:
            return None

        cleaned = clean_wiki_text(raw_text)
        if not cleaned.strip():
            return None

        if len(cleaned) > _WIKI_PREVIEW_MAX_CHARS:
            return cleaned[:_WIKI_PREVIEW_MAX_CHARS], True
        return cleaned, False

    async def _fetch_confirmed_wiki_text(
        self,
        confirmed_wiki_url: str,
        title: str | None,
        author: str | None,
        preferred_language: str = "zh-CN",
        work_language: str | None = None,
    ) -> str | None:
        if "wikipedia.org/wiki/" in confirmed_wiki_url:
            return await fetch_wiki_api_text(confirmed_wiki_url)

        if title:
            search_results = await self._search_wiki(
                title, author, preferred_language, work_language
            )
            for url, _lang, raw_content, _page_title, _content in search_results:
                if url == confirmed_wiki_url:
                    if raw_content:
                        return raw_content
                    break

        return await fetch_generic_wiki_text(confirmed_wiki_url)

    async def _fetch_and_filter_wiki(
        self, wiki_url: str, lang: str, scale: str = DEFAULT_SCALE
    ) -> tuple[str | None, str]:
        """抓取并过滤 wiki 正文，返回 (wiki_text | None, search_context)。

        按档位分配的预算（WIKI_SECTION_BUDGETS）分别截断角色/设定/剧情三组内容，
        优先保证角色信息不被截断丢失（核心原则：角色数量与质量必须匹配档位）。
        """
        raw_text = await fetch_wiki_api_text(wiki_url)

        if not raw_text:
            return None, ""

        grouped = filter_wiki_content_grouped(raw_text)
        budget = WIKI_SECTION_BUDGETS.get(scale, _DEFAULT_BUDGET)

        # all 档位不截断角色部分，由 extraction_service 分批处理
        if scale == "all":
            chars_kept = grouped["characters"]
        else:
            chars_kept = _truncate_at_boundary(grouped["characters"], budget["characters"])
        setting_kept = _truncate_at_boundary(grouped["world_setting"], budget["world_setting"])
        plot_kept = _truncate_at_boundary(grouped["plot"], budget["plot"])

        logger.info(
            "_fetch_and_filter_wiki | 分组截断 | scale=%s | "
            "characters: %d -> %d (budget=%d) | "
            "world_setting: %d -> %d (budget=%d) | "
            "plot: %d -> %d (budget=%d)",
            scale,
            len(grouped["characters"]),
            len(chars_kept),
            budget["characters"],
            len(grouped["world_setting"]),
            len(setting_kept),
            budget["world_setting"],
            len(grouped["plot"]),
            len(plot_kept),
            budget["plot"],
        )

        filtered = grouped["preamble"] + chars_kept + setting_kept + plot_kept

        if filtered.strip():
            return filtered, f"[来源: {wiki_url}]\n{filtered}"
        return None, ""

    async def _pick_link_from_candidates(
        self, candidates: list[dict], title: str, author: str | None
    ) -> dict | None:
        """从候选链接中选出最有价值的一个，直接调 LLM 判断。"""
        if not candidates or not self.llm:
            return None
        llm_operation.set("Wiki 链接筛选")
        items_text = "\n".join(
            f"{i + 1}. {c['link_text']} — {c['url']}" for i, c in enumerate(candidates[:5])
        )
        author_hint = f"（{author}）" if author else ""
        prompt = f"""当前在为「{title}」{author_hint}建立世界观和角色图谱，
需要从 Wikipedia 提取角色、剧情、设定等信息。

以下是从 Wikipedia 词条正文中截取的链接，请判断哪个链接最可能包含有价值的补充内容。

## ✅ 优先选择

- **角色列表/角色集合页面**（如"XX角色列表"、"登场人物"、"人物介绍"等，包含多个角色信息）
- 世界观设定页、用语列表页（如"XX用语列表"、"世界观"等）
- 作品衍生/前传/续集页

## ⚠️ 不选

- **作品主页面**（如"ONE PIECE"、"火影忍者"等主词条，避免循环引用）
- **单个角色详情页**（如"路飞"、"索隆"等单独角色介绍）
- 演员、导演、编剧、制作人等**现实人物页面**
- 影视作品、漫画改编、出版物、音乐、周边等衍生作品列表页
- 通用类型页面（如"喜劇"、"電視影集"等）
- 如果所有链接都是上述无用类型，返回 chosen: null

## 候选链接

{items_text}

## 输出格式

```json
{{"chosen": 候选序号（从1开始）}}
```
没有有价值的补充链接时：
```json
{{"chosen": null}}
```

只返回 JSON，不要包含其他文字。"""

        try:
            logger.debug(
                "_pick_link_from_candidates | LLM selection CALL START | candidate_count=%d",
                len(candidates),
            )
            resp = await self.llm.complete_json(
                system="你是内容分析助手。只返回合法的 JSON 对象。",
                prompt=prompt,
                max_tokens=500,
            )
            logger.debug(
                "_pick_link_from_candidates | LLM response | type=%s | content=%s",
                type(resp).__name__,
                str(resp)[:150] if resp else "empty",
            )
            if isinstance(resp, dict) and resp.get("chosen") is not None:
                idx = resp["chosen"] - 1
                if 0 <= idx < len(candidates):
                    chosen_url = candidates[idx]["url"]
                    logger.info(
                        "_pick_link_from_candidates | CHOSEN | index=%d | url=%s | reason=%s",
                        idx + 1,
                        chosen_url,
                        resp.get("reason", "(no_reason)"),
                    )
                    return candidates[idx]
                else:
                    logger.warning(
                        "_pick_link_from_candidates | INVALID_INDEX "
                        "| chosen=%d | candidate_count=%d",
                        resp.get("chosen"),
                        len(candidates),
                    )
            else:
                logger.info(
                    "_pick_link_from_candidates | NO_SELECTION | reason=null_or_invalid_format"
                )
        except Exception as e:
            logger.exception(
                "_pick_link_from_candidates | LLM_SELECTION_FAILED | error_type=%s | error_msg=%s",
                _safe_type_name(e),
                str(e)[:200],
            )
        return None

    async def _scan_and_fetch_useful_link_from_group(
        self,
        raw_characters: str,
        wiki_url: str,
        lang: str,
        title: str,
        author: str | None = None,
        scale: str = DEFAULT_SCALE,
        depth: int = 0,
        remaining_fetches: int = 5,
        remaining_llm_calls: int = 4,
    ) -> tuple[str | None, str | None, int, tuple[str, str] | None]:
        """Scan section for links, LLM picks best, fetch content.

        Args:
            depth: 0=主页面, 1=子链接
            remaining_fetches: 剩余 URL 获取次数
            remaining_llm_calls: 剩余 LLM 调用次数

        Returns:
            (link_url, raw_content, fetch_count, sub_info)
            sub_info: depth=0 且递归发现子链接时为 (sub_url, sub_content)，否则 None
        """
        logger.debug(
            "_scan_and_fetch_useful_link_from_group START | wiki_url=%s | title=%s | "
            "raw_len=%d | depth=%d | remaining_fetches=%d | remaining_llm_calls=%d",
            wiki_url,
            title,
            len(raw_characters),
            depth,
            remaining_fetches,
            remaining_llm_calls,
        )

        if not raw_characters.strip():
            return None, None, 0, None

        # 检查预算
        if remaining_fetches <= 0 or remaining_llm_calls <= 0:
            logger.debug(
                "_scan_and_fetch_useful_link_from_group | SKIP | NO_BUDGET | "
                "remaining_fetches=%d | remaining_llm_calls=%d",
                remaining_fetches,
                remaining_llm_calls,
            )
            return None, None, 0, None

        # 1. Extract links from raw character section (preserving markup)
        link_entries = extract_md_links_with_context(raw_characters, context_chars=0, max_links=5)
        logger.debug(
            "_scan_and_fetch_useful_link_from_group | Links extracted | count=%d | depth=%d",
            len(link_entries) if link_entries else 0,
            depth,
        )
        if not link_entries:
            return None, None, 0, None

        # 2. Resolve to full URLs
        candidates: list[dict] = []
        for entry in link_entries:
            url = resolve_wiki_link(entry["link_text"], wiki_url)
            if not url:
                continue
            candidates.append(
                {
                    "url": url,
                    "link_text": entry["link_text"],
                }
            )

        if not candidates:
            return None, None, 0, None

        # 3. LLM picks best candidate (消耗 1 次 LLM 调用)
        chosen = await self._pick_link_from_candidates(candidates, title, author)
        if not chosen:
            return None, None, 0, None

        chosen_url = chosen["url"]
        is_wiki_link = "wikipedia.org/wiki/" in chosen_url
        logger.info(
            "_scan_and_fetch_useful_link_from_group | FETCHING_CHOSEN "
            "| url=%s | is_wiki=%s | depth=%d",
            chosen_url,
            is_wiki_link,
            depth,
        )

        # 4. Fetch content (消耗 1 次 URL 获取)
        raw = None
        if is_wiki_link:
            raw = await fetch_wiki_api_text(chosen_url)
            if not raw or not raw.strip():
                raw = None

        if not raw:
            content = await fetch_url_text(chosen_url, max_chars=40000)
            if content and content.strip():
                raw = content

        if not raw:
            logger.warning(
                "_scan_and_fetch_useful_link_from_group | CONTENT_EMPTY | url=%s | depth=%d",
                chosen_url,
                depth,
            )
            return None, None, 1, None  # 消耗了 1 次获取但失败

        logger.info(
            "_scan_and_fetch_useful_link_from_group | SUCCESS | url=%s | len=%d | depth=%d",
            chosen_url,
            len(raw),
            depth,
        )

        # 如果是 depth=0，递归处理子链接内容
        if depth == 0 and remaining_fetches > 1 and remaining_llm_calls > 1:
            # 过滤页头噪音
            filtered_raw = filter_page_header_noise(raw)
            logger.debug(
                "_scan_and_fetch_useful_link_from_group | RECURSE "
                "| original_len=%d | filtered_len=%d",
                len(raw),
                len(filtered_raw),
            )

            # 递归扫描（depth=1）
            (
                sub_url,
                sub_content,
                sub_fetches,
                _sub_sub,
            ) = await self._scan_and_fetch_useful_link_from_group(
                filtered_raw,
                wiki_url,
                lang,
                title,
                author,
                scale,
                depth=1,
                remaining_fetches=remaining_fetches - 1,
                remaining_llm_calls=remaining_llm_calls - 1,
            )
            total_fetches = 1 + sub_fetches
            if sub_content:
                logger.info(
                    "_scan_and_fetch_useful_link_from_group"
                    " | SUB_LINK_FOUND"
                    " | sub_url=%s | sub_len=%d",
                    sub_url,
                    len(sub_content),
                )
                return chosen_url, raw, total_fetches, (sub_url, sub_content)
            return chosen_url, raw, total_fetches, None

        return chosen_url, raw, 1, None

    # 无 wiki 依据兜底场景使用的角色举证数量档位（与 SCALES.char_range 是两套独立数字，
    # 不共用/不影响 ScaleConfig：judge_fast_path 快路径门控只对 standard 生效，
    # 这里四个档位都要生效，且数值本身也不同，故单独维护）。
    _FALLBACK_CHAR_RANGES: dict[str, tuple[int, int]] = {
        "standard": (5, 10),
        "detailed": (10, 30),
        "deep": (20, 40),
        "all": (30, 60),
    }

    async def _identify_and_propose_characters(
        self,
        title: str,
        author: str | None,
        description: str | None,
        char_min: int,
        char_max: int,
    ) -> dict:
        """两段式调用的第一段：LLM 判断能否识别作品，若能则同时举证角色名。

        判断类调用，走副模型（self.sub_llm）；BYOK 用户在 API 层已短路回主模型。

        返回 {can_identify, can_generate, work_name, characters}；任意一步不满足条件
        （无法识别/角色数不足/调用失败/返回格式错误）都返回全 False 的兜底结构。
        """
        logger.debug(
            "_identify_and_propose_characters | LLM_CALL_START | title=%s | author=%s",
            title,
            author or "none",
        )
        llm_operation.set("快速路径判断")
        system = (
            "你是一个作品识别器。用户会提供作品的标题、作者和描述。\n\n"
            "## 判断标准\n\n"
            "1. 用户输入是否能唯一确定一个广为传播的虚构作品"
            "（小说/动漫/影视/游戏等）？\n"
            "2. 基于该作品的知名度，你是否能凭自身知识生成世界观元素"
            "（角色/地点/势力等）和角色关系？\n\n"
            f"如果两个条件都满足，还必须提供该作品的 **{char_min}-{char_max}** 个主要角色名字。\n\n"
            "## 输出格式\n\n"
            "```json\n"
            '{"can_identify": bool, "can_generate": bool, "work_name": "string", '
            '"characters": ["角色1", "角色2", ...]}\n'
            "```\n"
            f"characters 必须包含 {char_min}-{char_max} 个角色真实名字（不要编造）。\n"
            f"如果无法确定至少 {char_min} 个角色，将 can_identify 和 can_generate 都设为 false。"
            + get_lang_hint()
        )
        prompt_parts = [f"标题: {title}"]
        if author:
            prompt_parts.append(f"作者: {author}")
        if description:
            prompt_parts.append(f"描述: {description[:500]}")
        prompt = "\n".join(prompt_parts)

        fail_result = {
            "can_identify": False,
            "can_generate": False,
            "work_name": "",
            "characters": [],
        }

        try:
            logger.debug(
                "_identify_and_propose_characters | LLM_CALL_PARAMS "
                "| system_len=%d | prompt_len=%d | max_tokens=512",
                len(system),
                len(prompt),
            )
            resp = await self.sub_llm.complete_json(
                system=system,
                prompt=prompt,
                max_tokens=512,
            )
            logger.debug(
                "_identify_and_propose_characters | LLM_CALL_END | title=%s | "
                "resp_type=%s | resp_content=%s",
                title,
                type(resp).__name__,
                str(resp)[:300] if resp else "empty",
            )
        except Exception as e:
            logger.exception(
                "_identify_and_propose_characters | LLM_CALL_FAILED | title=%s "
                "| error_type=%s | error_msg=%s | fallback=normal_path",
                title,
                _safe_type_name(e),
                str(e)[:200],
            )
            return fail_result

        if not isinstance(resp, dict):
            logger.warning(
                "_identify_and_propose_characters | INVALID_RESPONSE_TYPE | title=%s "
                "| expected=dict | got=%s | resp=%s",
                title,
                type(resp).__name__,
                str(resp)[:200],
            )
            return fail_result

        can_identify = bool(resp.get("can_identify", False))
        can_generate = bool(resp.get("can_generate", False))
        work_name = resp.get("work_name", "")
        characters = resp.get("characters", [])

        if not (can_identify and can_generate):
            logger.info(
                "_identify_and_propose_characters | REJECT | title=%s | "
                "can_identify=%s | can_generate=%s | reason=llm_declined",
                title,
                can_identify,
                can_generate,
            )
            return fail_result

        if not isinstance(characters, list) or len(characters) < char_min:
            logger.info(
                "_identify_and_propose_characters | REJECT | title=%s | "
                "characters_count=%d | reason=insufficient_characters",
                title,
                len(characters) if isinstance(characters, list) else 0,
            )
            return fail_result

        characters = [str(c).strip() for c in characters[:char_max] if str(c).strip()]
        if len(characters) < char_min:
            logger.info(
                "_identify_and_propose_characters | REJECT | title=%s | "
                "characters_count=%d | reason=empty_character_names",
                title,
                len(characters),
            )
            return fail_result

        logger.debug(
            "_identify_and_propose_characters | PASS | title=%s | work_name=%s | characters=%s",
            title,
            work_name,
            characters,
        )
        return {
            "can_identify": True,
            "can_generate": True,
            "work_name": work_name,
            "characters": characters,
        }

    async def _verify_characters(self, work_name: str, characters: list[str]) -> dict:
        """两段式调用的第二段：逐一验证角色名是否确实属于该作品。

        判断类调用，走副模型（self.sub_llm）。不做阈值判断——阈值策略由调用方
        （judge_fast_path）自行决定，本方法只负责给出逐个角色的验证结果。

        返回 {success, accepted, rejected}；success=False 表示 LLM 调用异常/
        返回格式错误/条目缺失，调用方应视为整批验证失败。
        """
        llm_operation.set("快速路径验证")
        verify_system = (
            "你是一个作品知识验证器。用户会给你一部作品的名称和一组角色名。\n\n"
            "## 任务\n\n"
            "请逐一判断每个角色是否确实属于该作品（原作中真实存在的角色）。\n"
            "注意区分不同作品中名字相似但实际不同的角色。\n\n"
            "## 输出格式\n\n"
            "```json\n"
            '{"verdict": "accept" 或 "reject", '
            '"details": [{"name": "角色名", "belongs": true/false}, ...]}\n'
            "```\n\n"
            "- details 必须包含与输入角色列表相同数量的条目，不要遗漏任何一个\n"
            "- 如实标记每个角色的 belongs 状态。verdict 设为 accept 即可\n"
            "- 如果你不确定某个角色是否属于该作品，也应将其 belongs 设为 false" + get_lang_hint()
        )
        verify_prompt = f"作品: {work_name}\n角色列表: {', '.join(characters)}"

        fail_result: dict = {"success": False, "accepted": [], "rejected": set()}

        try:
            logger.debug(
                "_verify_characters | VERIFY_CALL_START | work_name=%s",
                work_name,
            )
            verify_resp = await self.sub_llm.complete_json(
                system=verify_system,
                prompt=verify_prompt,
                max_tokens=512,
            )
            logger.debug(
                "_verify_characters | VERIFY_CALL_END | work_name=%s | "
                "resp_type=%s | resp_content=%s",
                work_name,
                type(verify_resp).__name__,
                str(verify_resp)[:300] if verify_resp else "empty",
            )
        except Exception as e:
            logger.exception(
                "_verify_characters | VERIFY_CALL_FAILED | work_name=%s "
                "| error_type=%s | error_msg=%s",
                work_name,
                _safe_type_name(e),
                str(e)[:200],
            )
            return fail_result

        if not isinstance(verify_resp, dict):
            logger.warning(
                "_verify_characters | VERIFY_INVALID_RESPONSE | work_name=%s | got=%s "
                "| fallback=reject",
                work_name,
                type(verify_resp).__name__,
            )
            return fail_result

        details = verify_resp.get("details", [])
        # details 条目数不足或格式错误 → LLM 漏检/格式异常，保守拒绝
        dict_details = (
            [d for d in details if isinstance(d, dict)] if isinstance(details, list) else []
        )
        if len(dict_details) < len(characters):
            logger.info(
                "_verify_characters | REJECT | work_name=%s | valid_details_count=%d | "
                "expected=%d | reason=incomplete_or_malformed_details",
                work_name,
                len(dict_details),
                len(characters),
            )
            return fail_result

        # 找出被拒绝的角色（默认 belongs=False，与 prompt 的保守策略一致）
        # 用 strip 归一化名字，避免 LLM 返回微小空白差异导致过滤失败
        rejected = {d.get("name", "?").strip() for d in dict_details if not d.get("belongs", False)}
        accepted = (
            [c for c in characters if c.strip() not in rejected] if rejected else list(characters)
        )

        return {"success": True, "accepted": accepted, "rejected": rejected}

    async def judge_fast_path(
        self,
        title: str,
        author: str | None,
        description: str | None,
        scale: str,
        char_min: int = 10,
        char_max: int = 10,
    ) -> dict:
        logger.debug(
            "judge_fast_path | DECISION_GATE_START | title=%s | author=%s | scale=%s",
            title,
            author or "none",
            scale,
        )

        fail_result = {
            "can_identify": False,
            "can_generate": False,
            "work_name": "",
            "characters": [],
        }

        if scale not in ("standard", "detailed"):
            logger.debug(
                "judge_fast_path | GATE_SKIP | reason=scale_not_eligible | scale=%s", scale
            )
            return fail_result

        # ── 阶段一：识别 + 举证 ──
        identify_result = await self._identify_and_propose_characters(
            title, author, description, char_min, char_max
        )
        if not (identify_result["can_identify"] and identify_result["can_generate"]):
            return identify_result

        work_name = identify_result["work_name"]
        characters = identify_result["characters"]

        # ── 阶段二：验证角色归属 ──
        verify_result = await self._verify_characters(work_name or title, characters)
        if not verify_result["success"]:
            return fail_result

        rejected = verify_result["rejected"]
        reject_ratio = len(rejected) / len(characters) if characters else 1.0

        if reject_ratio > 0.3:
            logger.info(
                "judge_fast_path | GATE_REJECT | stage=verify | title=%s | work_name=%s | "
                "rejected_count=%d | reject_ratio=%.1f%% | rejected=%s",
                title,
                work_name,
                len(rejected),
                reject_ratio * 100,
                rejected,
            )
            return fail_result

        logger.info(
            "judge_fast_path | GATE_ACCEPT | title=%s | work_name=%s | characters_verified=%d",
            title,
            work_name,
            len(verify_result["accepted"]),
        )
        return {
            "can_identify": True,
            "can_generate": True,
            "work_name": work_name,
            "characters": verify_result["accepted"],
        }

    async def _generate_characters_without_wiki(
        self, title: str, author: str | None, scale: str
    ) -> list[str]:
        """wiki 角色资料缺失/过短时的无依据兜底：让 LLM 凭自身知识举证并验证角色名。

        与 judge_fast_path 共用识别+验证两段式调用，但不做 30% 阈值整批拒绝——
        只逐个剔除验证不通过的角色，剩下几个算几个（哪怕最后只剩 0 个）。
        四个创建档位都生效，        不受 judge_fast_path「仅 standard/detailed」这条限制。

        举证角色数量上限使用 _FALLBACK_CHAR_RANGES（与 SCALES.char_range 是两套独立
        数字），不是 judge_fast_path 快路径门控用的那一套。
        """
        char_min, char_max = self._FALLBACK_CHAR_RANGES.get(
            scale, self._FALLBACK_CHAR_RANGES["standard"]
        )
        logger.debug(
            "_generate_characters_without_wiki | START | title=%s | scale=%s | char_range=%d-%d",
            title,
            scale,
            char_min,
            char_max,
        )

        identify_result = await self._identify_and_propose_characters(
            title, author, None, char_min, char_max
        )
        if not (identify_result["can_identify"] and identify_result["can_generate"]):
            logger.info(
                "_generate_characters_without_wiki | LLM 无法识别作品，返回空列表 | title=%s",
                title,
            )
            return []

        work_name = identify_result["work_name"]
        characters = identify_result["characters"]

        verify_result = await self._verify_characters(work_name or title, characters)
        if not verify_result["success"]:
            logger.info(
                "_generate_characters_without_wiki | 验证阶段失败，返回空列表 | title=%s",
                title,
            )
            return []

        accepted = verify_result["accepted"]
        logger.info(
            "_generate_characters_without_wiki | DONE | title=%s | proposed=%d | accepted=%d",
            title,
            len(characters),
            len(accepted),
        )
        return accepted

    async def build_world_content_fast(
        self,
        world_id: str,
        title: str,
        author: str | None,
        type: str | None,
        description: str | None,
        urls: list[str],
        user_id: str,
        scale: str = "standard",
        detected_work_type: str | None = None,
        preferred_language: str = "zh-CN",
        fast_path_characters: list[str] | None = None,
    ) -> WorldDoc:
        """快速路径：LLM 直接生成元素，不经过 Tavily/Wikipedia。

        standard 档位使用，跳过网络搜索，仅依赖 LLM 自身知识。
        参考网址仍会抓取并用于补充提取。
        """
        t0 = time.monotonic()
        wcd(
            f'[快速路径] ═══ 开始 ═══ world_id={world_id} | title="{title}" | author="{author}" | '
            f"scale={scale} | desc_len={len(description) if description else 0}"
        )
        logger.info(
            "build_world_content_fast START | world=%s | title=%s | author=%s | "
            "scale=%s | has_description=%s | urls_count=%d | detected_work_type=%s",
            world_id,
            title,
            author or "none",
            scale,
            bool(description),
            len(urls),
            detected_work_type or "none",
        )
        llm_operation.set("世界创建(快速)")

        # 2. 并行：元素提取 + 剧情简介
        wcd("[快速路径] 并行启动: 元素提取 + 剧情简介")
        logger.debug(
            "build_world_content_fast | Starting parallel extract & plot | world=%s", world_id
        )
        t_extract_start = time.monotonic()

        async def _do_extract():
            if not self.extraction:
                logger.warning(
                    "build_world_content_fast | extraction service not available | world=%s",
                    world_id,
                )
                return [], []
            logger.debug(
                "build_world_content_fast | extraction.extract() CALL START | world=%s | "
                "params: scale=%s, wiki=None, ref=None",
                world_id,
                scale,
            )
            t_extract_call_start = time.monotonic()
            try:
                elements, char_candidates = await self.extraction.extract(
                    title=title,
                    author=author,
                    description=description,
                    scale=scale,
                    wiki_characters=None,  # 快速路径无 wiki
                    wiki_plot=None,
                    wiki_world_setting=None,
                    ref_content=None,  # standard 不用参考网址
                )
                t_extract_call = time.monotonic() - t_extract_call_start
                logger.debug(
                    "build_world_content_fast | extraction.extract() CALL END | "
                    "world=%s | elements=%d | char_candidates=%d | elapsed_sec=%.1f",
                    world_id,
                    len(elements) if elements else 0,
                    len(char_candidates) if char_candidates else 0,
                    t_extract_call,
                )
                # 快路径角色：优先使用已验证的角色列表
                if fast_path_characters is not None:
                    char_candidates = [{"name": name} for name in fast_path_characters]
                    logger.info(
                        "build_world_content_fast | Using fast_path_characters "
                        "| count=%d | world=%s",
                        len(char_candidates),
                        world_id,
                    )
                if elements:
                    by_category = {}
                    for e in elements:
                        by_category.setdefault(e.category, 0)
                        by_category[e.category] += 1
                    logger.debug(
                        "build_world_content_fast | extraction breakdown | world=%s | %s",
                        world_id,
                        " | ".join(f"{k}={v}" for k, v in sorted(by_category.items())),
                    )
                return elements, char_candidates
            except Exception as e:
                t_extract_call = time.monotonic() - t_extract_call_start
                logger.exception(
                    "build_world_content_fast | extraction.extract() FAILED | "
                    "world=%s | error_type=%s | elapsed_sec=%.1f | error_msg=%s",
                    world_id,
                    _safe_type_name(e),
                    t_extract_call,
                    str(e)[:200],
                )
                raise

        async def _do_plot():
            if description:
                logger.debug(
                    "build_world_content_fast | Using provided description "
                    "as plot | world=%s | len=%d",
                    world_id,
                    len(description),
                )
                return description
            logger.debug(
                "build_world_content_fast | _build_plot_summary() CALL START | world=%s | "
                "mode=llm_fallback",
                world_id,
            )
            t_plot_call_start = time.monotonic()
            try:
                result = await self._build_plot_summary(title, author, None, [])
                t_plot_call = time.monotonic() - t_plot_call_start
                logger.debug(
                    "build_world_content_fast | _build_plot_summary() CALL END | "
                    "world=%s | plot_len=%s | elapsed_sec=%.1f",
                    world_id,
                    len(result) if result else 0,
                    t_plot_call,
                )
                return result
            except Exception as e:
                t_plot_call = time.monotonic() - t_plot_call_start
                logger.exception(
                    "build_world_content_fast | _build_plot_summary() FAILED | "
                    "world=%s | error_type=%s | elapsed_sec=%.1f | fallback=empty",
                    world_id,
                    _safe_type_name(e),
                    t_plot_call,
                )
                return None

        async def _do_common_sense():
            # 快速路径无 wiki 素材，用 description 或标题生成世界观底色
            return await self._generate_common_sense_llm(
                wiki_plot=description,
                wiki_world_setting=None,
                title=title,
            )

        (elements, char_candidates), plot_summary, common_sense = await asyncio.gather(
            _do_extract(), _do_plot(), _do_common_sense()
        )
        t_extract_elapsed = time.monotonic() - t_extract_start

        wcd(
            f"[快速路径] 并行完成 ✓ elements={len(elements) if elements else 0} | "
            f"plot_len={len(plot_summary) if plot_summary else 0} | "
            f"common_sense={len(common_sense) if common_sense else 0} "
            f"| 耗时={t_extract_elapsed:.1f}s"
        )
        logger.info(
            "build_world_content_fast | EXTRACTION_COMPLETED | world=%s | elements=%d | "
            "plot_summary_len=%s | common_sense_len=%d | elapsed_sec=%.1f",
            world_id,
            len(elements) if elements else 0,
            len(plot_summary) if plot_summary else 0,
            len(common_sense) if common_sense else 0,
            t_extract_elapsed,
        )
        wcd(f"[build_world_content_fast] 元素提取完成: elements={len(elements) if elements else 0}")

        # 3. 构建 WorldDoc 并保存
        wcd("[快速路径] 构建 WorldDoc 并保存...")
        logger.debug("build_world_content_fast | Building WorldDoc | world=%s", world_id)
        world = WorldDoc(
            world_id=world_id,
            version="1.0",
            source=WorldSource(
                title=title,
                author=author,
                type=type,
                references=urls,
                input_text=description,
                detected_work_type=detected_work_type or None,
                wiki_text=None,
                plot_summary=plot_summary,
                common_sense=common_sense,
            ),
            meta=WorldMeta(
                created_at=datetime.now(),
                updated_at=datetime.now(),
                last_analyzed_at=datetime.now(),
            ),
            elements=elements,
            char_candidates=char_candidates,
            scale=scale,
        )

        logger.debug("build_world_content_fast | repo.save() CALL START | world=%s", world_id)
        try:
            await self.repo.save(world, user_id=user_id)
            logger.debug("build_world_content_fast | repo.save() CALL END | world=%s", world_id)
        except Exception as e:
            logger.exception(
                "build_world_content_fast | repo.save() FAILED | world=%s | error_type=%s",
                world_id,
                _safe_type_name(e),
            )
            raise

        # 将事件元素写入事件索引（M26EventIndex）
        try:
            await self._populate_event_index(world_id, elements)
        except Exception as e:
            logger.warning(
                "build_world_content_fast | _populate_event_index FAILED | world=%s: %s",
                world_id,
                e,
            )

        elapsed = time.monotonic() - t0
        elem_count = len(elements) if elements else 0
        wcd(f"[快速路径] ═══ 完成 ═══ elements={elem_count} | 总耗时={elapsed:.1f}s")
        logger.info(
            "build_world_content_fast COMPLETED | world=%s | elements=%d | "
            "extraction_sec=%.1f | total_sec=%.1f",
            world_id,
            len(elements) if elements else 0,
            t_extract_elapsed,
            elapsed,
        )
        wcd(
            f"[build_world_content_fast] 完成: world_id={world_id}, "
            f"elements={elem_count}, 总耗时={elapsed:.1f}s"
        )
        return world

    async def check_llm_available(self) -> None:
        """快速检测 LLM 服务是否可用，不可用时抛 HTTPException。"""
        llm_operation.set("世界创建")
        logger.debug("check_llm_available | LLM ping START")
        try:
            await self.llm.complete(system="", prompt="你好", max_tokens=5)
            logger.debug("check_llm_available | LLM ping SUCCESS")
        except LLMQuotaExhaustedError:
            logger.exception("check_llm_available | LLM_QUOTA_EXHAUSTED")
            raise
        except Exception as e:
            logger.exception(
                "check_llm_available | LLM ping FAILED | error_type=%s", _safe_type_name(e)
            )
            raise HTTPException(status_code=503, detail="LLM 服务暂不可用，请稍后重试") from e

    async def _curate_ref_content(
        self, raw_text: str | None, title: str, author: str | None
    ) -> str | None:
        if not raw_text or not raw_text.strip():
            return None
        if not self.sub_llm:
            return raw_text

        llm_operation.set("参考网址摘录")
        author_part = f"\n作者: {author}" if author else ""
        system = (
            "你是内容摘录助手，任务是从网页抓取的原始文本中挑出与指定作品相关的内容。\n\n"
            "## 判断标准\n\n"
            "- 只保留与该作品角色或剧情相关、包含实质信息的段落"
            "（仅仅提及作品名字、一句话带过不算数）\n"
            "- 摘录内容必须是原文中逐字出现的文字，禁止改写、总结或添加任何说明\n"
            "- 如果原文中完全没有符合条件的内容，只回复 NONE，不要输出其他任何文字\n\n"
            "## 输出\n\n"
            "直接输出摘录到的原文段落（可以是多段，保持原文措辞），或者只输出 NONE。"
            + get_lang_hint()
        )
        prompt = f"作品标题: {title}{author_part}\n\n原始网页文本:\n{raw_text}"

        try:
            logger.debug(
                "_curate_ref_content | LLM_CALL_START | title=%s | raw_len=%d",
                title,
                len(raw_text),
            )
            assert self.sub_llm is not None
            resp = await self.sub_llm.complete(system=system, prompt=prompt, max_tokens=4096)
            curated = resp.content.strip()
        except Exception as e:
            logger.warning(
                "_curate_ref_content | LLM_CALL_FAILED | title=%s | error_type=%s | error_msg=%s "
                "| fallback=keep_raw_text",
                title,
                _safe_type_name(e),
                str(e)[:200],
            )
            return raw_text

        if not curated or curated.upper() == "NONE":
            logger.debug("_curate_ref_content | NO_USEFUL_CONTENT | title=%s", title)
            return None
        return curated

    async def build_world_content(
        self,
        world_id: str,
        title: str,
        author: str | None,
        type: str | None,
        description: str | None,
        urls: list[str],
        user_id: str,
        scale: str = "standard",
        detected_work_type: str | None = None,
        preferred_language: str = "zh-CN",
        confirmed_wiki_url: str | None = None,
    ) -> WorldDoc:
        """执行世界创建的重量级部分：抓取→提取→生成，并行化所有网络请求。

        完成后 upsert 到 DB（已存在的存根记录会被更新）。
        """
        t0 = time.monotonic()
        wcd(
            f'[正常路径] ═══ 开始 ═══ world_id={world_id} | title="{title}" | author="{author}" | '
            f'scale={scale} | wiki_url="{confirmed_wiki_url}" | '
            f"desc_len={len(description) if description else 0} | urls={len(urls)}"
        )
        logger.info(
            "build_world_content START | world=%s | title=%s | author=%s | "
            "scale=%s | has_wiki_url=%s | has_description=%s | urls_count=%d | "
            "detected_work_type=%s",
            world_id,
            title,
            author or "none",
            scale,
            bool(confirmed_wiki_url),
            bool(description),
            len(urls),
            detected_work_type or "none",
        )
        llm_operation.set("世界创建")
        source_urls: list[str] = []
        wiki_text: str | None = None
        wiki_characters: str | None = None
        wiki_plot: str | None = None
        wiki_world_setting: str | None = None

        ref_texts: list[str] = []
        is_high_scale = scale in ("detailed", "deep")
        logger.debug(
            "build_world_content | scale_classification | world=%s | scale=%s | is_high_scale=%s",
            world_id,
            scale,
            is_high_scale,
        )

        if confirmed_wiki_url:
            from urllib.parse import urlparse

            lang = urlparse(confirmed_wiki_url).netloc.split(".")[0]
            source_urls = [confirmed_wiki_url]

            logger.debug(
                "build_world_content | wiki_branch | world=%s "
                "| wiki_url=%s | lang=%s | is_high_scale=%s",
                world_id,
                confirmed_wiki_url,
                lang,
                is_high_scale,
            )
            _t_fetch_start = time.monotonic()

            # Single wiki fetch (supports non-Wikipedia URLs like Baidu Baike, Moegirl)
            raw_text = await self._fetch_confirmed_wiki_text(
                confirmed_wiki_url, title, author, preferred_language
            )

            if not raw_text:
                logger.info("build_world_content | wiki_fetch_empty | world=%s", world_id)
            else:
                logger.info(
                    "build_world_content | wiki_fetched | world=%s | len=%d",
                    world_id,
                    len(raw_text),
                )

                raw_groups = split_wiki_grouped_raw(raw_text)
                raw_chars = raw_groups["characters"]
                raw_setting = raw_groups["world_setting"]

                # Link scanning: when section is short (< 888 chars cleaned)
                # Scan characters and setting sections in parallel
                # 支持两层递归：主页面 → 子链接 → 子链接的子链接
                # 预算：每部分 2 次 URL 获取 + 2 次 LLM 调用（共 4 次 LLM + 5 次 URL）
                char_link_log = ""
                setting_link_log = ""

                async def _scan_section(
                    section_raw: str, section_name: str
                ) -> tuple[str, str, tuple[str, str] | None] | tuple[None, None, None]:
                    logger.debug(
                        "build_world_content | link_scan_trigger | world=%s "
                        "| section=%s | raw_len=%d",
                        world_id,
                        section_name,
                        len(section_raw),
                    )
                    # depth=0：主页面扫描，预算 2 次获取 + 2 次 LLM
                    (
                        link_url,
                        link_raw,
                        fetch_count,
                        sub_info,
                    ) = await self._scan_and_fetch_useful_link_from_group(
                        section_raw,
                        confirmed_wiki_url,
                        lang,
                        title,
                        author,
                        scale,
                        depth=0,
                        remaining_fetches=2,
                        remaining_llm_calls=2,
                    )
                    if not link_raw:
                        return None, None, None
                    # 过滤子链接内容的噪音段落
                    filtered_raw = filter_subpage_content(link_raw)
                    cleaned_link = clean_wiki_text(filtered_raw)
                    if not cleaned_link.strip():
                        return None, None, None
                    logger.info(
                        "build_world_content | link_appended | world=%s "
                        "| section=%s | url=%s | len=%d | fetch_count=%d",
                        world_id,
                        section_name,
                        link_url,
                        len(cleaned_link),
                        fetch_count,
                    )
                    return cleaned_link, link_url, sub_info

                (
                    (char_link, char_url, char_sub_info),
                    (setting_link, setting_url, setting_sub_info),
                ) = await asyncio.gather(
                    _scan_section(raw_chars, "characters"),
                    _scan_section(raw_setting, "world_setting"),
                )
                # 保存主链清洗结果（拼接前），用于日志
                cleaned_chars_main = clean_wiki_text(raw_chars)
                cleaned_setting_main = clean_wiki_text(raw_setting)

                if char_link:
                    raw_chars += f"\n\n---SOURCE_BOUNDARY: {char_url}---\n\n" + char_link
                    char_link_log = f"\n子链：{char_url}\n{char_link}"
                    if char_sub_info:
                        sub_url, sub_content = char_sub_info
                        # depth=1 递归返回的是 fetch_wiki_api_text 原始输出，
                        # 需要 filter_subpage_content + clean_wiki_text 清洗
                        filtered_sub = filter_subpage_content(sub_content)
                        cleaned_sub = clean_wiki_text(filtered_sub)
                        if cleaned_sub.strip():
                            raw_chars += f"\n\n---SOURCE_BOUNDARY: {sub_url}---\n\n" + cleaned_sub
                            char_link_log += f"\n子链的子链：{sub_url}\n{cleaned_sub}"
                if setting_link:
                    raw_setting += f"\n\n---SOURCE_BOUNDARY: {setting_url}---\n\n" + setting_link
                    setting_link_log = f"\n子链：{setting_url}\n{setting_link}"
                    if setting_sub_info:
                        sub_url, sub_content = setting_sub_info
                        # 同 char_sub_info：depth=1 返回的是原始 wiki API 输出，需要清洗
                        filtered_sub = filter_subpage_content(sub_content)
                        cleaned_sub = clean_wiki_text(filtered_sub)
                        if cleaned_sub.strip():
                            raw_setting += f"\n\n---SOURCE_BOUNDARY: {sub_url}---\n\n" + cleaned_sub
                            setting_link_log += f"\n子链的子链：{sub_url}\n{cleaned_sub}"

                # Ref URL fetching (high scale only)
                if is_high_scale and urls:

                    async def _fetch_ref_url(url: str) -> str | None:
                        try:
                            if "wikipedia.org/wiki/" in url:
                                from urllib.parse import urlparse as _up

                                _wlang = _up(url).netloc.split(".")[0]
                                ref_raw = await fetch_wiki_api_text(url)
                                raw = clean_wiki_text(ref_raw) if ref_raw else None
                            else:
                                raw = await fetch_url_text(url)
                            curated = await self._curate_ref_content(raw, title, author)
                            return curated if curated else raw
                        except Exception as e:
                            logger.warning(
                                "build_world_content | _fetch_ref_url FAILED | url=%s: %s", url, e
                            )
                            return None

                    fetched = await asyncio.gather(*[_fetch_ref_url(u) for u in urls[:3]])
                    ref_texts = [
                        f"[来源: {u}]\n{t}" for u, t in zip(urls[:3], fetched, strict=False) if t
                    ]

                # Clean each group（合并后的内容用于提取）
                budget = WIKI_SECTION_BUDGETS.get(scale, _DEFAULT_BUDGET)
                cleaned_chars = clean_wiki_text(raw_chars)
                cleaned_plot = clean_wiki_text(raw_groups["plot"])
                cleaned_setting = clean_wiki_text(raw_setting)

                # Write log files（主链用拼接前的清洗结果，子链分开写）
                _ws_write_log(
                    "wiki_characters.txt",
                    f"# 清洗后的角色部分\n# 字符数: {len(cleaned_chars)}"
                    f"\n主链：{confirmed_wiki_url}"
                    f"\n{cleaned_chars_main}{char_link_log}",
                )
                _ws_write_log(
                    "wiki_plot.txt",
                    f"# 清洗后的剧情部分\n# 字符数: {len(cleaned_plot)}"
                    f"\n主链：{confirmed_wiki_url}"
                    f"\n{cleaned_plot}",
                )
                _ws_write_log(
                    "wiki_world_setting.txt",
                    f"# 清洗后的设定部分\n# 字符数: {len(cleaned_setting)}"
                    f"\n主链：{confirmed_wiki_url}"
                    f"\n{cleaned_setting_main}{setting_link_log}",
                )

                # Truncate each group
                # all 档位：不截断角色 wiki，由 extraction_service 分批处理
                if scale == "all":
                    wiki_characters = cleaned_chars
                else:
                    wiki_characters = _truncate_at_boundary(cleaned_chars, budget["characters"])
                wiki_plot = _truncate_at_boundary(cleaned_plot, budget["plot"])
                wiki_world_setting = _truncate_at_boundary(cleaned_setting, budget["world_setting"])

                logger.info(
                    "build_world_content | groups_cleaned_truncated | world=%s | "
                    "chars: %d->%d | plot: %d->%d | setting: %d->%d",
                    world_id,
                    len(cleaned_chars),
                    len(wiki_characters),
                    len(cleaned_plot),
                    len(wiki_plot),
                    len(cleaned_setting),
                    len(wiki_world_setting),
                )

                # Build full wiki_text for extraction (concatenation of all groups)
                wiki_text = "\n\n".join(
                    filter(None, [wiki_characters, wiki_world_setting, wiki_plot])
                )

        else:
            # No wiki branch: fetch ref URLs for high scale
            logger.debug(
                "build_world_content | no_wiki_branch | world=%s | "
                "is_high_scale=%s | urls_count=%d",
                world_id,
                is_high_scale,
                len(urls),
            )
            if is_high_scale and urls:

                async def _fetch_ref_url_plain(url: str) -> str | None:
                    try:
                        if "wikipedia.org/wiki/" in url:
                            from urllib.parse import urlparse as _up

                            wlang = _up(url).netloc.split(".")[0]
                            text, _ = await self._fetch_and_filter_wiki(url, wlang, scale)
                            return text
                        raw = await fetch_url_text(url)
                        curated = await self._curate_ref_content(raw, title, author)
                        return curated if curated else raw
                    except Exception as e:
                        logger.warning(
                            "build_world_content | _fetch_ref_url_plain FAILED | url=%s: %s",
                            url,
                            e,
                        )
                        return None

                fetched = await asyncio.gather(*[_fetch_ref_url_plain(u) for u in urls[:3]])
                ref_texts = [
                    f"[来源: {u}]\n{t}" for u, t in zip(urls[:3], fetched, strict=False) if t
                ]

        ref_content: str | None = "\n\n".join(ref_texts) if ref_texts else None

        if ref_content:
            logger.info(
                "build_world_content | ref_content_ready | world=%s | len=%d",
                world_id,
                len(ref_content),
            )

        # wiki 角色资料为空或过短（阈值与 extraction_service.extract_characters 的
        # 跳过判断一致）：无论是 wiki 页面本身内容单薄，还是压根没有确认的 wiki 页面，
        # 都触发无依据兜底，让 LLM 凭自身知识举证角色，避免角色图谱只剩用户自己。
        needs_char_fallback = not wiki_characters or len(wiki_characters) < 100
        if needs_char_fallback:
            logger.debug(
                "build_world_content | char_fallback_trigger | world=%s | wiki_characters_len=%d",
                world_id,
                len(wiki_characters) if wiki_characters else 0,
            )

        wcd("[正常路径] 并行启动: 元素提取 + 剧情简介")
        logger.debug("build_world_content | Starting parallel extract & plot | world=%s", world_id)
        t_extract_start = time.monotonic()

        async def _do_extract():
            if not self.extraction:
                logger.warning(
                    "build_world_content | extraction service not available | world=%s", world_id
                )
                return [], []
            t_extract_call_start = time.monotonic()
            try:
                elements, char_candidates = await self.extraction.extract(
                    title=title,
                    author=author,
                    description=description,
                    scale=scale,
                    wiki_characters=wiki_characters,
                    wiki_plot=wiki_plot,
                    wiki_world_setting=wiki_world_setting,
                    ref_content=ref_content,
                )
                t_extract_call = time.monotonic() - t_extract_call_start
                logger.debug(
                    "build_world_content | extraction.extract() CALL END "
                    "| world=%s | elements=%d | char_candidates=%d | elapsed_sec=%.1f",
                    world_id,
                    len(elements) if elements else 0,
                    len(char_candidates) if char_candidates else 0,
                    t_extract_call,
                )
                return elements, char_candidates
            except Exception as e:
                t_extract_call = time.monotonic() - t_extract_call_start
                logger.exception(
                    "build_world_content | extraction.extract() FAILED | "
                    "world=%s | error_type=%s | elapsed_sec=%.1f | error_msg=%s",
                    world_id,
                    _safe_type_name(e),
                    t_extract_call,
                    str(e)[:200],
                )
                raise

        async def _do_plot():
            if description:
                return description
            try:
                return await self._build_plot_summary(title, author, wiki_plot, [])
            except Exception as e:
                logger.exception(
                    "build_world_content | _build_plot_summary() FAILED | "
                    "world=%s | error_type=%s | fallback=empty",
                    world_id,
                    _safe_type_name(e),
                )
                return None

        async def _do_common_sense():
            return await self._generate_common_sense_llm(
                wiki_plot=wiki_plot,
                wiki_world_setting=wiki_world_setting,
            )

        async def _do_char_fallback() -> list[str] | None:
            if not needs_char_fallback:
                return None
            return await self._generate_characters_without_wiki(title, author, scale)

        (
            (elements, char_candidates),
            plot_summary,
            common_sense,
            fallback_characters,
        ) = await asyncio.gather(_do_extract(), _do_plot(), _do_common_sense(), _do_char_fallback())
        t_extract_elapsed = time.monotonic() - t_extract_start

        if needs_char_fallback and fallback_characters:
            char_candidates = [{"name": name} for name in fallback_characters]
            wcd(f"[正常路径] 无维基依据角色兜底 ✓ {len(char_candidates)} 个角色")
            logger.info(
                "build_world_content | Using fallback characters (no wiki evidence) | "
                "count=%d | world=%s",
                len(char_candidates),
                world_id,
            )

        wcd(
            f"[正常路径] 并行完成 elements={len(elements) if elements else 0} + "
            f"char_candidates={len(char_candidates) if char_candidates else 0} | "
            f"plot_len={len(plot_summary) if plot_summary else 0} | "
            f"common_sense={len(common_sense) if common_sense else 0} "
            f"| 耗时={t_extract_elapsed:.1f}s"
        )
        logger.info(
            "build_world_content | EXTRACTION_COMPLETED | world=%s | elements=%d | "
            "char_candidates=%d | wiki_text_len=%d | plot_summary_len=%d | "
            "common_sense_len=%d | elapsed_sec=%.1f",
            world_id,
            len(elements) if elements else 0,
            len(char_candidates) if char_candidates else 0,
            len(wiki_text) if wiki_text else 0,
            len(plot_summary) if plot_summary else 0,
            len(common_sense) if common_sense else 0,
            t_extract_elapsed,
        )

        wcd("[正常路径] 构建 WorldDoc 并保存...")
        logger.debug("build_world_content | Building WorldDoc | world=%s", world_id)
        world = WorldDoc(
            world_id=world_id,
            version="1.0",
            source=WorldSource(
                title=title,
                author=author,
                type=type,
                references=urls,
                input_text=description,
                detected_work_type=detected_work_type or None,
                source_urls=source_urls,
                wiki_text=wiki_text,
                wiki_characters=wiki_characters,
                wiki_plot=wiki_plot,
                wiki_world_setting=wiki_world_setting,
                plot_summary=plot_summary,
                common_sense=common_sense,
            ),
            meta=WorldMeta(
                created_at=datetime.now(),
                updated_at=datetime.now(),
                last_analyzed_at=datetime.now(),
            ),
            elements=elements,
            char_candidates=char_candidates,
            scale=scale,
        )

        logger.debug("build_world_content | repo.save() CALL START | world=%s", world_id)
        try:
            await self.repo.save(world, user_id=user_id)
            logger.debug("build_world_content | repo.save() CALL END | world=%s", world_id)
        except Exception as e:
            logger.exception(
                "build_world_content | repo.save() FAILED | world=%s | error_type=%s",
                world_id,
                _safe_type_name(e),
            )
            raise

        # 将事件元素写入事件索引（M26EventIndex）
        try:
            await self._populate_event_index(world_id, elements)
        except Exception as e:
            logger.warning(
                "build_world_content | _populate_event_index FAILED | world=%s: %s",
                world_id,
                e,
            )

        elapsed = time.monotonic() - t0
        elem_count = len(elements) if elements else 0
        wcd(f"[正常路径] ═══ 完成 ═══ elements={elem_count} | 总耗时={elapsed:.1f}s")

        logger.info(
            "build_world_content COMPLETED | world=%s | elements=%d | "
            "wiki_text_len=%d | ref_content_len=%d | plot_summary_len=%d | "
            "extraction_sec=%.1f | total_sec=%.1f",
            world_id,
            elem_count,
            len(wiki_text) if wiki_text else 0,
            len(ref_content) if ref_content else 0,
            len(plot_summary) if plot_summary else 0,
            t_extract_elapsed,
            elapsed,
        )
        wcd(
            f"[build_world_content] 完成: world_id={world_id}, elements={elem_count}, "
            f"wiki_text_len={len(wiki_text) if wiki_text else 0}, 总耗时={elapsed:.1f}s"
        )
        return world

    async def create_world(
        self,
        title: str,
        author: str | None,
        type: str | None,
        description: str | None,
        urls: list[str],
        user_id: str,
        scale: str = "standard",
        detected_work_type: str | None = None,
        preferred_language: str = "zh-CN",
        confirmed_wiki_url: str | None = None,
        confirmed_wiki_raw_content: str | None = None,
    ) -> WorldDoc:
        """同步创建世界（兼容接口，内部调用 check_llm_available + build_world_content）。"""
        await self.check_llm_available()
        world_id = str(uuid.uuid4())
        return await self.build_world_content(
            world_id=world_id,
            title=title,
            author=author,
            type=type,
            description=description,
            urls=urls,
            user_id=user_id,
            scale=scale,
            detected_work_type=detected_work_type,
            preferred_language=preferred_language,
            confirmed_wiki_url=confirmed_wiki_url,
        )

    def list_templates(self) -> list[dict]:
        """返回模板列表摘要（id, title, category, description, element_count）"""
        return [
            {
                "id": tpl.id,
                "title": tpl.title,
                "category": tpl.category,
                "description": tpl.description,
                "element_count": len(tpl.elements),
            }
            for tpl in _list_templates()
        ]

    async def create_from_template(
        self,
        template_id: str,
        scale: str,
        user_id: str,
        preferred_language: str = "zh-CN",
        char_repo=None,
        rel_repo=None,
    ) -> WorldDoc:
        """从模板创建世界，如果模板有该档位的预设数据则直接写入角色和关系。"""
        tpl = get_template(template_id)
        if tpl is None:
            raise HTTPException(status_code=404, detail="模板不存在")

        # 模板自带 10-11 个元素，直接全部使用
        elements = [
            Element(
                id=f"elem_{uuid.uuid4().hex[:8]}",
                category=te.category,
                name=te.name,
                brief=te.brief,
                detail=te.detail,
            )
            for te in tpl.elements
        ]

        world_id = str(uuid.uuid4())
        world = WorldDoc(
            world_id=world_id,
            version="1.0",
            source=WorldSource(
                title=tpl.title,
                type="template",
                plot_summary=tpl.plot_summary,
                core_conflict=tpl.core_conflict or None,
                tone_and_atmosphere=tpl.tone_and_atmosphere or None,
            ),
            meta=WorldMeta(
                created_at=datetime.now(),
                updated_at=datetime.now(),
                last_analyzed_at=datetime.now(),
            ),
            elements=elements,
            scale=scale,
        )

        await self.repo.save(world, user_id=user_id)

        # 如果模板有该档位的预设角色/关系，直接写入 DB
        scale_data = tpl.scales.get(scale)
        if scale_data and char_repo and rel_repo:
            # 1. 批量创建角色
            char_dicts = [
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
            created_chars = await char_repo.bulk_create(world_id, char_dicts)

            # 2. 构建 name→id 映射
            name_to_id = {c.name: c.id for c in created_chars}

            # 3. 批量创建关系（去重）
            rel_dicts = []
            seen_pairs: set[tuple[str, str]] = set()
            for tr in scale_data.relations:
                a_id = name_to_id.get(tr.character_a)
                b_id = name_to_id.get(tr.character_b)
                if a_id and b_id:
                    pair = (str(a_id), str(b_id))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    rel_dicts.append(
                        {
                            "character_a": str(a_id),
                            "character_b": str(b_id),
                            "type": tr.type,
                            "direction": tr.direction,
                            "description": tr.description,
                        }
                    )
            if rel_dicts:
                await rel_repo.bulk_create(world_id, rel_dicts)

            await self.repo.update_counts(
                world_id, char_count=len(created_chars), rel_count=len(rel_dicts)
            )

            logger.info(
                "create_from_template | 预设数据写入完成 | world=%s | chars=%d | rels=%d",
                world_id,
                len(created_chars),
                len(rel_dicts),
            )

        return world

    async def list_worlds(self, user_id: str) -> list[dict]:
        return await self.repo.list_by_user(user_id)

    async def get_world(self, world_id: str) -> WorldDoc | None:
        return await self.repo.get(world_id)

    async def get_world_with_updated_at(self, world_id: str) -> tuple[WorldDoc, datetime] | None:
        """返回 (WorldDoc, row-level updated_at) 或 None，避免二次查询。"""
        return await self.repo.get_with_updated_at(world_id)

    async def delete_world(self, world_id: str) -> bool:
        return await self.repo.delete(world_id)

    async def update_element(
        self,
        world_id: str,
        element_id: str,
        brief: str,
        detail: str,
        name: str | None = None,
        category: str | None = None,
    ) -> Element | None:
        world = await self.repo.get(world_id)
        if world is None:
            return None

        target = None
        for elem in world.elements:
            if elem.id == element_id:
                target = elem
                break

        if target is None:
            return None

        if name is not None:
            target.name = name
        if category is not None:
            target.category = category
        target.brief = brief
        target.detail = detail
        world.meta.updated_at = datetime.now()
        await self.repo.save(world, user_id=None)
        return target

    async def add_element(
        self, world_id: str, category: str, name: str, brief: str, detail: str
    ) -> Element | None:
        world = await self.repo.get(world_id)
        if world is None:
            return None

        elem = Element(
            id=f"elem_{uuid.uuid4().hex[:8]}",
            category=category,
            name=name,
            brief=brief,
            detail=detail,
        )
        world.elements.append(elem)
        world.meta.updated_at = datetime.now()
        await self.repo.save(world, user_id=None)
        return elem

    async def update_common_sense(self, world_id: str, common_sense: str) -> bool:
        world = await self.repo.get(world_id)
        if world is None:
            return False
        world.source.common_sense = common_sense
        world.meta.updated_at = datetime.now()
        await self.repo.save(world, user_id=None)
        return True

    async def update_plot_summary(self, world_id: str, plot_summary: str) -> bool:
        world = await self.repo.get(world_id)
        if world is None:
            return False
        world.source.plot_summary = plot_summary
        world.meta.updated_at = datetime.now()
        await self.repo.save(world, user_id=None)
        return True

    async def update_core_conflict(self, world_id: str, core_conflict: str) -> bool:
        world = await self.repo.get(world_id)
        if world is None:
            return False
        world.source.core_conflict = core_conflict
        world.meta.updated_at = datetime.now()
        await self.repo.save(world, user_id=None)
        return True

    async def update_tone_and_atmosphere(self, world_id: str, tone_and_atmosphere: str) -> bool:
        world = await self.repo.get(world_id)
        if world is None:
            return False
        world.source.tone_and_atmosphere = tone_and_atmosphere
        world.meta.updated_at = datetime.now()
        await self.repo.save(world, user_id=None)
        return True

    async def update_plot_development(self, world_id: str, plot_development: str) -> bool:
        world = await self.repo.get(world_id)
        if world is None:
            return False
        world.source.plot_development = plot_development
        world.meta.updated_at = datetime.now()
        await self.repo.save(world, user_id=None)
        return True

    async def update_title(self, world_id: str, title: str) -> bool:
        world = await self.repo.get(world_id)
        if world is None:
            return False
        world.source.title = title
        world.meta.updated_at = datetime.now()
        await self.repo.save(world, user_id=None)
        return True

    async def delete_element(self, world_id: str, element_id: str) -> bool:
        world = await self.repo.get(world_id)
        if world is None:
            return False

        original_len = len(world.elements)
        world.elements = [e for e in world.elements if e.id != element_id]
        if len(world.elements) == original_len:
            return False

        world.meta.updated_at = datetime.now()
        await self.repo.save(world, user_id=None)
        return True

    async def copy_world(self, source_world_id: str, user_id: str) -> WorldDoc:
        source = await self.repo.get(source_world_id)
        if source is None:
            raise ValueError(f"World not found: {source_world_id}")

        new_world = WorldDoc(
            world_id=str(uuid.uuid4()),
            world_base_id=source.world_id,
            version="1.0",
            source=WorldSource(
                title=source.source.title,
                author=source.source.author,
                type=source.source.type,
                references=list(source.source.references),
                input_text=source.source.input_text,
                plot_summary=source.source.plot_summary,
                common_sense=source.source.common_sense,
            ),
            meta=WorldMeta(
                created_at=datetime.now(),
                updated_at=datetime.now(),
            ),
            elements=[
                Element(
                    id=f"elem_{uuid.uuid4().hex[:8]}",
                    category=e.category,
                    name=e.name,
                    brief=e.brief,
                    detail=e.detail,
                )
                for e in source.elements
            ],
            scale=source.scale,
        )

        await self.repo.save(new_world, user_id=user_id)
        return new_world
