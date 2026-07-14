"""web.py 工具函数单元测试（mock httpx）。"""

from unittest.mock import AsyncMock, MagicMock, patch

from src.utils.web import (
    _TextExtractor,
    fetch_wiki_api_text,
    fetch_wiki_langlink,
    filter_for_extraction,
    search_wiki_api,
)

# ── _TextExtractor ──────────────────────────────────────────────────────────


class TestTextExtractor:
    def test_plain_text_preserved(self):
        ex = _TextExtractor()
        ex.feed("<p>Hello world content here</p>")
        assert "Hello world content here" in ex.get_text()

    def test_script_tag_content_stripped(self):
        ex = _TextExtractor()
        ex.feed("<script>var x = 1;</script><p>Actual content line here</p>")
        text = ex.get_text()
        assert "var x = 1;" not in text
        assert "Actual content line here" in text

    def test_style_tag_content_stripped(self):
        ex = _TextExtractor()
        ex.feed("<style>.cls { color: red; }</style><p>Page content text</p>")
        text = ex.get_text()
        assert ".cls" not in text

    def test_nav_tag_content_stripped(self):
        ex = _TextExtractor()
        ex.feed("<nav>Menu items link</nav><p>Main body content</p>")
        text = ex.get_text()
        assert "Menu items link" not in text
        assert "Main body content" in text

    def test_short_text_below_threshold_ignored(self):
        ex = _TextExtractor()
        ex.feed("<p>Hi</p><p>This is longer content that should pass</p>")
        text = ex.get_text()
        assert "Hi" not in text
        assert "This is longer content" in text

    def test_multiple_newlines_collapsed(self):
        ex = _TextExtractor()
        ex.feed("<p>First long paragraph here</p><p>Second long paragraph here</p>")
        text = ex.get_text()
        assert "\n\n\n" not in text

    def test_nested_skip_tag_handled(self):
        ex = _TextExtractor()
        ex.feed(
            "<footer><nav>Skip this nav inside footer</nav></footer><p>Keep this content here</p>"
        )
        text = ex.get_text()
        assert "Skip this nav" not in text
        assert "Keep this content" in text


# ── filter_for_extraction ────────────────────────────────────────────────────


class TestFilterForExtraction:
    def test_staff_role_line_removed(self):
        text = "导演：山田太郎\n这是一段角色介绍内容。"
        result = filter_for_extraction(text)
        assert "导演：山田太郎" not in result
        assert "角色介绍内容" in result

    def test_irrelevant_section_heading_removes_following_lines(self):
        text = "角色介绍\nAlice是主角。\n配音\n张三 CV: 某人\n"
        result = filter_for_extraction(text)
        assert "Alice是主角" in result
        assert "张三 CV" not in result

    def test_relevant_section_heading_resumes_inclusion(self):
        text = "配音\n配音内容\n角色\n角色介绍内容在这里"
        result = filter_for_extraction(text)
        assert "配音内容" not in result
        assert "角色介绍内容在这里" in result

    def test_empty_lines_preserved(self):
        text = "第一段内容。\n\n第二段内容。"
        result = filter_for_extraction(text)
        assert "\n\n" in result

    def test_normal_content_unchanged(self):
        text = "这是一段普通的故事简介内容，包含角色登场和背景设定。"
        result = filter_for_extraction(text)
        assert result == text

    def test_multiple_staff_roles_removed(self):
        text = "原作：田中花子\n脚本：佐藤次郎\n正文内容在这里"
        result = filter_for_extraction(text)
        assert "原作：" not in result
        assert "脚本：" not in result
        assert "正文内容在这里" in result


# ── fetch_wiki_api_text ──────────────────────────────────────────────────────


def _make_http_client(response_json: dict, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=response_json)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=resp)
    return mock_client


class TestFetchWikiApiText:
    async def test_returns_extract_text(self):
        # action=parse 响应格式：parse.text.* 含 HTML
        payload = {"parse": {"text": {"*": "<p>维基百科正文内容</p>"}}}
        with patch("httpx.AsyncClient", return_value=_make_http_client(payload)):
            result = await fetch_wiki_api_text("https://zh.wikipedia.org/wiki/三体")
        assert "维基百科正文内容" in result

    async def test_truncates_at_max_chars(self):
        long_html = "<p>" + "A" * 100 + "</p>"
        payload = {"parse": {"text": {"*": long_html}}}
        with patch("httpx.AsyncClient", return_value=_make_http_client(payload)):
            result = await fetch_wiki_api_text("https://en.wikipedia.org/wiki/Test", max_chars=50)
        assert len(result) == 50

    async def test_invalid_url_returns_empty(self):
        result = await fetch_wiki_api_text("https://example.com/not-wiki")
        assert result == ""

    async def test_http_error_returns_empty(self):
        with patch("httpx.AsyncClient", return_value=_make_http_client({}, status_code=503)):
            result = await fetch_wiki_api_text("https://en.wikipedia.org/wiki/Test")
        assert result == ""

    async def test_no_extract_returns_empty(self):
        payload = {"parse": {"text": {"*": ""}}}
        with patch("httpx.AsyncClient", return_value=_make_http_client(payload)):
            result = await fetch_wiki_api_text("https://en.wikipedia.org/wiki/Test")
        assert result == ""

    async def test_network_exception_returns_empty(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=Exception("timeout"))
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await fetch_wiki_api_text("https://en.wikipedia.org/wiki/Test")
        assert result == ""

    async def test_zh_wiki_path_variant_parsed(self):
        payload = {"parse": {"text": {"*": "<p>中文词条内容</p>"}}}
        with patch("httpx.AsyncClient", return_value=_make_http_client(payload)):
            result = await fetch_wiki_api_text("https://zh.wikipedia.org/zh-cn/三体")
        assert "中文词条内容" in result


# ── fetch_wiki_langlink ──────────────────────────────────────────────────────


class TestFetchWikiLanglink:
    async def test_returns_localized_url(self):
        payload = {"query": {"pages": {"1": {"langlinks": [{"lang": "ja", "*": "三体_小説"}]}}}}
        with patch("httpx.AsyncClient", return_value=_make_http_client(payload)):
            result = await fetch_wiki_langlink(
                "https://en.wikipedia.org/wiki/The_Three-Body_Problem", "ja"
            )
        assert result == "https://ja.wikipedia.org/wiki/三体_小説"

    async def test_no_langlink_returns_none(self):
        payload = {"query": {"pages": {"1": {"langlinks": []}}}}
        with patch("httpx.AsyncClient", return_value=_make_http_client(payload)):
            result = await fetch_wiki_langlink("https://en.wikipedia.org/wiki/Test", "ja")
        assert result is None

    async def test_invalid_url_returns_none(self):
        result = await fetch_wiki_langlink("https://example.com/not-wiki", "ja")
        assert result is None

    async def test_http_error_returns_none(self):
        with patch("httpx.AsyncClient", return_value=_make_http_client({}, status_code=404)):
            result = await fetch_wiki_langlink("https://en.wikipedia.org/wiki/Test", "ja")
        assert result is None

    async def test_spaces_replaced_with_underscores(self):
        payload = {"query": {"pages": {"1": {"langlinks": [{"lang": "ko", "*": "삼체 소설"}]}}}}
        with patch("httpx.AsyncClient", return_value=_make_http_client(payload)):
            result = await fetch_wiki_langlink("https://en.wikipedia.org/wiki/Test", "ko")
        assert result == "https://ko.wikipedia.org/wiki/삼체_소설"

    async def test_network_exception_returns_none(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=Exception("network error"))
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await fetch_wiki_langlink("https://en.wikipedia.org/wiki/Test", "ja")
        assert result is None


# ── search_wiki_api ──────────────────────────────────────────────────────────


class TestSearchWikiApi:
    async def test_returns_url_for_first_hit(self):
        payload = {"query": {"search": [{"title": "三体"}, {"title": "三体 (小说)"}]}}
        with patch("httpx.AsyncClient", return_value=_make_http_client(payload)):
            result = await search_wiki_api("三体 刘慈欣", "zh")
        assert result == "https://zh.wikipedia.org/wiki/三体"

    async def test_no_results_returns_none(self):
        payload = {"query": {"search": []}}
        with patch("httpx.AsyncClient", return_value=_make_http_client(payload)):
            result = await search_wiki_api("nonexistent query xyz", "en")
        assert result is None

    async def test_http_error_returns_none(self):
        with patch("httpx.AsyncClient", return_value=_make_http_client({}, status_code=500)):
            result = await search_wiki_api("test", "en")
        assert result is None

    async def test_spaces_in_title_replaced_with_underscores(self):
        payload = {"query": {"search": [{"title": "The Three Body Problem"}]}}
        with patch("httpx.AsyncClient", return_value=_make_http_client(payload)):
            result = await search_wiki_api("three body problem", "en")
        assert result == "https://en.wikipedia.org/wiki/The_Three_Body_Problem"

    async def test_network_exception_returns_none(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=Exception("timeout"))
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await search_wiki_api("test", "en")
        assert result is None

    async def test_uses_correct_language_domain(self):
        payload = {"query": {"search": [{"title": "진격의 거인"}]}}

        captured_urls = []

        async def mock_get(url, **kwargs):
            captured_urls.append(url)
            resp = MagicMock()
            resp.status_code = 200
            resp.json = MagicMock(return_value=payload)
            return resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = mock_get

        with patch("httpx.AsyncClient", return_value=mock_client):
            await search_wiki_api("진격의 거인", "ko")

        assert any("ko.wikipedia.org" in u for u in captured_urls)
