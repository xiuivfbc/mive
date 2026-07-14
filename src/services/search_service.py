import hashlib
import json
import logging
from dataclasses import asdict, dataclass

from tavily import AsyncTavilyClient

logger = logging.getLogger(__name__)
_cache_logger = logging.getLogger("tavily.cache")

_CACHE_TTL = 7 * 24 * 3600  # 7 天


class MockSearchService:
    """开发用 mock，返回两条假 Wikipedia 候选，使 wiki-select UI 正常展示。"""

    async def search(
        self,
        query: str,
        *,
        allowed_domains: list[str] | None = None,
        max_results: int = 5,
        include_raw_content: bool = False,
    ) -> list["SearchResult"]:
        # 根据 allowed_domains 决定返回哪些语言的假结果
        domains = allowed_domains or ["zh.wikipedia.org", "en.wikipedia.org"]
        results = []
        _MOCK_CONTENT = (  # noqa: N806
            "== 剧情 ==\n这是一个虚构作品的 Mock 词条内容，仅用于本地开发测试。\n"
            "作品讲述了一段跌宕起伏的故事，主角在重重困难中成长。\n"
        )
        if any("zh.wikipedia.org" in d for d in domains):
            results.append(
                SearchResult(
                    url="https://zh.wikipedia.org/wiki/Mock_%E4%BD%9C%E5%93%81",
                    title="Mock 作品 - 维基百科，自由的百科全书",
                    content="Mock 作品是一部虚构的测试用作品。",
                    score=0.95,
                    raw_content=_MOCK_CONTENT if include_raw_content else None,
                )
            )
        if any("en.wikipedia.org" in d for d in domains):
            results.append(
                SearchResult(
                    url="https://en.wikipedia.org/wiki/Mock_Work",
                    title="Mock Work - Wikipedia",
                    content="Mock Work is a fictional work used for local development testing.",
                    score=0.88,
                    raw_content=_MOCK_CONTENT if include_raw_content else None,
                )
            )
        return results[:max_results]


@dataclass
class SearchResult:
    url: str
    title: str
    content: str
    score: float
    raw_content: str | None = None


class SearchService:
    def __init__(self, api_key: str, redis=None):
        self.client = AsyncTavilyClient(api_key=api_key)
        self._redis = redis

    def _cache_key(
        self,
        query: str,
        allowed_domains: list[str] | None,
        max_results: int,
        include_raw_content: bool,
    ) -> str:
        parts = f"{query}|{sorted(allowed_domains or [])}|{max_results}|{include_raw_content}"
        digest = hashlib.sha256(parts.encode()).hexdigest()[:16]
        return f"tavily:{digest}"

    async def search(
        self,
        query: str,
        *,
        allowed_domains: list[str] | None = None,
        max_results: int = 5,
        include_raw_content: bool = False,
    ) -> list[SearchResult]:
        if self._redis is not None:
            key = self._cache_key(query, allowed_domains, max_results, include_raw_content)
            try:
                cached = await self._redis.get(key)
                if cached is not None:
                    _cache_logger.info(
                        "HIT key=%s query=%r domains=%s", key, query, allowed_domains
                    )
                    return [SearchResult(**r) for r in json.loads(cached)]
            except Exception:
                logger.warning("Tavily cache read failed", exc_info=True)

        kwargs: dict = {
            "query": query,
            "max_results": max_results,
            "include_answer": False,
            "topic": "general",
            "include_raw_content": include_raw_content,
        }
        if allowed_domains:
            kwargs["include_domains"] = allowed_domains

        resp = await self.client.search(**kwargs)
        results = [
            SearchResult(
                url=r["url"],
                title=r["title"],
                content=r["content"],
                score=r["score"],
                raw_content=r.get("raw_content"),
            )
            for r in resp["results"]
        ]

        if self._redis is not None:
            try:
                await self._redis.set(key, json.dumps([asdict(r) for r in results]), ex=_CACHE_TTL)
            except Exception:
                logger.warning("Tavily cache write failed", exc_info=True)

        return results
