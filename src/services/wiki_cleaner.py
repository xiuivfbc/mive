"""Unified wiki content cleaner: wiki markdown -> plain text.

All regex patterns concentrated here. clean_wiki_text() is idempotent.
"""

import re


def clean_wiki_text(text: str) -> str:
    """Unified cleaner: wiki markdown -> plain text. Idempotent."""
    if not text:
        return ""
    # 1. Images ![alt](url)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    # 2. Wiki templates {{template|...}}
    text = re.sub(r"\{\{[^}]*\}\}", "", text)
    # 3a. Empty markdown links [](...) — residual from [![](img)](link) after image removal
    text = re.sub(r"\[\]\([^)]*\)", "", text)
    # 3b. Markdown links [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    # 4. Wiki links [[page|display]] -> display, [[page]] -> page
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    # 5. Footnote references [1] [2]
    text = re.sub(r"\[\d+\]", "", text)
    # 6. HTML tags <ref>, <sup> etc.
    text = re.sub(r"<[^>]+>", "", text)
    # 7. Wiki tables {| ... |} (multiline)
    text = re.sub(r"\{\|.*?\|\}", "", text, flags=re.DOTALL)
    # 8. Bold/italic: wiki '''bold''' and ''italic'' (before markdown * handling)
    text = re.sub(r"'''([^']+?)'''", r"\1", text)
    text = re.sub(r"''([^']+?)''", r"\1", text)
    # 8b. Markdown bold/italic **text** / *text* / ***text***
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    # 9. CSS style blocks from wiki HTML
    #    Match any line containing CSS property declarations (e.g. .mw-parser-output {...})
    #    Uses non-greedy matching per-line to handle consecutive CSS blocks correctly
    text = re.sub(
        r"(?:^|\n)\s*[a-zA-Z.@#][^\n]*\{[^\n}]*\}[^\n]*(?:\{[^\n}]*\}[^\n]*)*",
        "",
        text,
        flags=re.MULTILINE,
    )
    # 9b. Inline CSS fragments embedded in text (e.g. .mw-parser-output ruby>rt{...})
    text = re.sub(r"\.mw-parser-output[^\n{]*\{[^}]*\}", "", text)
    # 10. Markdown table rows: convert consecutive |...| blocks to plain text.
    #     Previously this step DELETED all table rows, which accidentally removed
    #     character descriptions stored in wiki tables (e.g. moegirl's | 角色名 | 描述 |).
    #     Now: skip separator rows (| --- |), convert cell content to space-separated text.
    def _convert_table_block(lines: list[str]) -> list[str]:
        result = []
        buf: list[str] = []
        sep_re = re.compile(r"^\|[\s\-|]+\|$")

        def flush():
            for row in buf:
                stripped = row.strip()
                if sep_re.match(stripped):
                    continue
                if stripped.startswith("|") and stripped.endswith("|"):
                    cells = [c.strip() for c in stripped.strip("|").split("|")]
                    cells = [c for c in cells if c]
                    if cells:
                        result.append(" ".join(cells))
            buf.clear()

        for row in lines:
            stripped = row.strip()
            if stripped.startswith("|") and stripped.endswith("|"):
                buf.append(row)
            else:
                flush()
                result.append(row)
        flush()
        return result

    text = "\n".join(_convert_table_block(text.split("\n")))
    # 11. Cite note residual markers (#cite_note-...)
    text = re.sub(r"\(#cite_note-[^)]*\)", "", text)
    # 12. Horizontal rules --- *** ___ (allow leading whitespace)
    text = re.sub(r"^\s*[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
    # 13. Heading ## xxx -> xxx (strip # markers)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # 13b. 百度百科"播报"/"编辑"功能按钮文字：仅当二者独立成行且紧邻出现时才是噪音
    #      （标题下常见 "标题\n\n播报\n\n编辑\n\n正文..."），不匹配正文中真实出现
    #      "播报"/"编辑"字样的句子（要求整行内容仅为该词，不允许同行有其他文字）
    text = re.sub(
        r"^[ \t]*播报[ \t]*\n(?:[ \t]*\n)*[ \t]*编辑[ \t]*$\n?",
        "",
        text,
        flags=re.MULTILINE,
    )
    # 14. Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
