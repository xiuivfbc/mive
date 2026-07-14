"""Tests for wiki_cleaner.py - unified wiki content cleaner."""

from src.services.wiki_cleaner import clean_wiki_text


class TestCleanWikiText:
    """Test each cleaning rule individually."""

    def test_strip_images(self):
        """Rule 1: Remove ![alt](url) image markup."""
        text = "Before ![alt text](http://example.com/img.png) After"
        result = clean_wiki_text(text)
        assert "![" not in result
        assert "Before" in result
        assert "After" in result
        assert "alt text" not in result

    def test_strip_templates(self):
        """Rule 2: Remove {{template|...}} wiki templates."""
        text = "Before {{Infobox|name=Test|year=2020}} After"
        result = clean_wiki_text(text)
        assert "{{" not in result
        assert "}}" not in result
        assert "Before" in result
        assert "After" in result

    def test_markdown_links_to_text(self):
        """Rule 3: Convert [text](url) -> text."""
        text = "Click [here](http://example.com) for details"
        result = clean_wiki_text(text)
        assert "here" in result
        assert "http://example.com" not in result
        assert "[" not in result

    def test_wiki_links_with_display(self):
        """Rule 4a: Convert [[page|display]] -> display."""
        text = "See [[Naruto_Uzumaki|Naruto]] for details"
        result = clean_wiki_text(text)
        assert "Naruto" in result
        assert "Naruto_Uzumaki" not in result
        assert "[[" not in result

    def test_wiki_links_without_display(self):
        """Rule 4b: Convert [[page]] -> page."""
        text = "See [[Naruto]] for details"
        result = clean_wiki_text(text)
        assert "Naruto" in result
        assert "[[" not in result

    def test_strip_footnote_references(self):
        """Rule 5: Remove [1] [2] footnote references."""
        text = "Some fact[1] and another[23] end."
        result = clean_wiki_text(text)
        assert "[1]" not in result
        assert "[23]" not in result
        assert "Some fact" in result
        assert "and another" in result
        assert "end." in result

    def test_strip_html_tags(self):
        """Rule 6: Remove HTML tags like <ref>, <sup>."""
        text = "Text<ref name='src'>source</ref> more<sup>2</sup>"
        result = clean_wiki_text(text)
        assert "<ref" not in result
        assert "</ref>" not in result
        assert "<sup>" not in result
        assert "Text" in result
        assert " more" in result

    def test_strip_wiki_tables(self):
        """Rule 7: Remove wiki tables {| ... |} (multiline)."""
        text = "Before\n{| class='wikitable'\n| row1\n| row2\n|}\nAfter"
        result = clean_wiki_text(text)
        assert "Before" in result
        assert "After" in result
        assert "row1" not in result
        assert "{|" not in result

    def test_strip_bold_italic(self):
        """Rule 8: Remove **bold** / *italic* / ***bold italic*** markup."""
        text = "Normal **bold** and *italic* and ***both*** text"
        result = clean_wiki_text(text)
        assert "**" not in result
        assert "bold" in result
        assert "italic" in result
        assert "both" in result
        assert "Normal" in result

    def test_wiki_bold_triple_quote(self):
        """Rule 8a: Remove wiki '''bold''' triple-quote markup."""
        text = "这是'''粗体'''文本"
        result = clean_wiki_text(text)
        assert "粗体" in result
        assert "'''" not in result

    def test_wiki_italic_double_quote(self):
        """Rule 8a: Remove wiki ''italic'' double-quote markup."""
        text = "这是''斜体''文本"
        result = clean_wiki_text(text)
        assert "斜体" in result
        assert "''" not in result

    def test_wiki_bold_italic(self):
        """Rule 8a: Remove wiki '''''bold italic''''' five-quote markup."""
        text = "这是'''''粗斜体'''''文本"
        result = clean_wiki_text(text)
        assert "粗斜体" in result
        assert "''" not in result

    def test_strip_horizontal_rules(self):
        """Rule 9: Remove horizontal rules --- *** ___."""
        text = "Above\n\n---\n\nBelow"
        result = clean_wiki_text(text)
        assert "Above" in result
        assert "Below" in result
        assert "---" not in result

    def test_strip_heading_markers(self):
        """Rule 10: Strip heading ## markers, keep text."""
        text = "## Title\n### Subtitle\nContent"
        result = clean_wiki_text(text)
        assert "##" not in result
        assert "#" not in result
        assert "Title" in result
        assert "Subtitle" in result
        assert "Content" in result

    def test_collapse_multiple_blank_lines(self):
        """Rule 11: Collapse 3+ newlines to 2."""
        text = "A\n\n\n\n\nB"
        result = clean_wiki_text(text)
        assert "\n\n\n" not in result
        assert "A" in result
        assert "B" in result


class TestCleanWikiTextBroadcastEditButtons:
    """Rule 13b: 百度百科标题下"播报"/"编辑"功能按钮文字清洗。

    真实样本形如 "## 人物介绍\n\n播报\n\n编辑\n\n### 男主角\n..."，"播报"/"编辑"
    独立成行、紧邻出现，属于百度百科的功能按钮噪音，不属于正文。
    """

    def test_strip_broadcast_and_edit_buttons_after_heading(self):
        """标题下紧跟的"播报"/"编辑"两行应被去掉，正文保留。"""
        text = "## 人物介绍\n\n播报\n\n编辑\n\n### 男主角\n主角是一名剑士。"
        result = clean_wiki_text(text)
        assert "播报" not in result
        assert "编辑" not in result
        assert "人物介绍" in result
        assert "男主角" in result
        assert "主角是一名剑士。" in result

    def test_no_blank_line_between_broadcast_and_edit(self):
        """ "播报"和"编辑"紧挨（无空行）时同样应被去掉。"""
        text = "## 作品设定\n播报\n编辑\n这里是设定正文。"
        result = clean_wiki_text(text)
        assert "播报" not in result
        assert "编辑" not in result
        assert "这里是设定正文。" in result

    def test_does_not_strip_broadcast_word_within_sentence(self):
        """正文句子中真实出现"播报"一词（非独立成行）不应被误伤。"""
        text = "他每天准时在电台播报新闻，深受观众喜爱。"
        result = clean_wiki_text(text)
        assert "播报" in result
        assert result.strip() == text

    def test_does_not_strip_edit_word_within_sentence(self):
        """正文句子中真实出现"编辑"一词（非独立成行）不应被误伤。"""
        text = "她是这本杂志的资深编辑，负责审阅所有稿件。"
        result = clean_wiki_text(text)
        assert "编辑" in result
        assert result.strip() == text

    def test_does_not_strip_standalone_broadcast_without_following_edit(self):
        """只有"播报"独立成行、后面不是"编辑"时不应被去掉（要求二者紧邻同时出现）。"""
        text = "## 剧情简介\n\n播报\n\n这是一段真实的剧情描述。"
        result = clean_wiki_text(text)
        assert "播报" in result
        assert "这是一段真实的剧情描述。" in result


class TestCleanWikiTextComposite:
    """Test combined scenarios with multiple markup types."""

    def test_mixed_markup(self):
        """Multiple markup types in one passage."""
        text = (
            "## Characters\n"
            "![photo](http://img.png)\n"
            "Naruto[[Naruto|Naruto Uzumaki]] is a **ninja**[1].\n"
            "<ref>source</ref>\n"
            "---\n"
            "{{Infobox|char}}"
        )
        result = clean_wiki_text(text)
        assert "Characters" in result
        assert "Naruto" in result
        assert "ninja" in result
        assert "![" not in result
        assert "[[" not in result
        assert "**" not in result
        assert "[1]" not in result
        assert "<ref" not in result
        assert "---" not in result
        assert "{{" not in result

    def test_wiki_article_excerpt(self):
        """Realistic wiki article excerpt with mixed content."""
        text = (
            "'''Naruto''' is a Japanese [[manga]] series written and illustrated by "
            "[[Masashi Kishimoto]].\n\n"
            "== Plot ==\n"
            "The story follows {{Nihongo|Naruto Uzumaki|うずまきナルト}}.\n\n"
            "== Characters ==\n"
            "=== Main ===\n"
            "* '''Naruto Uzumaki''' — the protagonist[1]\n"
            "* '''Sasuke Uchiha''' — rival[2]\n"
        )
        result = clean_wiki_text(text)
        assert "Naruto" in result
        assert "manga" in result
        assert "Masashi Kishimoto" in result
        assert "Plot" in result
        assert "Characters" in result
        assert "protagonist" in result
        # Markup should be gone
        assert "'''" not in result
        assert "[[" not in result
        assert "{{" not in result
        assert "[1]" not in result


class TestCleanWikiTextIdempotency:
    """Test that cleaning twice produces the same result."""

    def test_idempotent_on_clean_text(self):
        """Already clean text should be unchanged by a second cleaning."""
        text = "Plain text with no markup at all."
        assert clean_wiki_text(text) == clean_wiki_text(clean_wiki_text(text))

    def test_idempotent_on_mixed_markup(self):
        """Cleaning twice on mixed markup produces same result."""
        text = "## Title\n**bold** [link](http://x.com) [[page|Name]] text"
        once = clean_wiki_text(text)
        twice = clean_wiki_text(once)
        assert once == twice

    def test_idempotent_on_images_and_templates(self):
        """Images and templates fully removed, second pass is no-op."""
        text = "![img](url) {{tpl}} remaining text"
        once = clean_wiki_text(text)
        twice = clean_wiki_text(once)
        assert once == twice


class TestCleanWikiTextEdgeCases:
    """Edge cases."""

    def test_empty_string(self):
        """Empty string returns empty string."""
        assert clean_wiki_text("") == ""

    def test_none_input(self):
        """None input returns empty string."""
        assert clean_wiki_text(None) == ""

    def test_whitespace_only(self):
        """Whitespace-only returns empty string (stripped)."""
        assert clean_wiki_text("   \n\n  ") == ""

    def test_only_markup(self):
        """Text that is entirely markup returns empty."""
        text = "![img](url) {{tpl}} ---"
        result = clean_wiki_text(text)
        assert result == "" or result.strip() == ""

    def test_preserves_content_without_markup(self):
        """Plain text without any markup passes through unchanged."""
        text = "Just a plain paragraph with normal text."
        result = clean_wiki_text(text)
        assert result == text


class TestCleanWikiTextNoiseRemoval:
    """Test removal of wiki preamble noise: CSS blocks, markdown tables, cite notes."""

    def test_css_mw_parser_output_block(self):
        """Remove .mw-parser-output CSS rule block."""
        text = (
            ".mw-parser-output .mbox-text,.mw-parser-output .mbox-image{border-collapse:collapse}\n"
            "Actual content here."
        )
        result = clean_wiki_text(text)
        assert "mw-parser-output" not in result
        assert "border-collapse" not in result
        assert "Actual content here." in result

    def test_css_html_body_mediawiki_block(self):
        """Remove html body.mediawiki CSS rule block."""
        text = "html body.mediawiki .mw-parser-output{font-size:14px}\n正文内容在此。"
        result = clean_wiki_text(text)
        assert "mediawiki" not in result
        assert "font-size" not in result
        assert "正文内容在此。" in result

    def test_css_generic_class_selector_block(self):
        """Remove CSS blocks starting with .className selectors."""
        text = ".mbox-small{text-align:center;font-size:smaller}\n正文内容。"
        result = clean_wiki_text(text)
        assert "mbox-small" not in result
        assert "text-align" not in result
        assert "正文内容。" in result

    def test_css_id_selector_block(self):
        """Remove CSS blocks starting with #id selectors."""
        text = "#some-id{background-color:#f9f9f9}\n正文内容。"
        result = clean_wiki_text(text)
        assert "some-id" not in result
        assert "background-color" not in result
        assert "正文内容。" in result

    def test_markdown_table_rows_simple(self):
        """Remove simple markdown table rows | content |."""
        text = "| 出版社 | 集英社 |\n| 导演 | 山田太郎 |\n正文内容。"
        result = clean_wiki_text(text)
        assert "出版社" not in result
        assert "集英社" not in result
        assert "导演" not in result
        assert "正文内容。" in result

    def test_markdown_table_separator_rows(self):
        """Remove markdown table separator rows | --- | --- |."""
        text = "| 列1 | 列2 |\n| --- | --- |\n| 值1 | 值2 |\n正文内容。"
        result = clean_wiki_text(text)
        assert "---" not in result
        assert "列1" not in result
        assert "值1" not in result
        assert "正文内容。" in result

    def test_maintenance_template_table(self):
        """Remove maintenance template tables (e.g. '此條目需要补充更多来源')."""
        text = "|  |  |\n| --- | --- |\n| 此條目需要补充更多来源 | |\n## 角色\n角色列表内容。"
        result = clean_wiki_text(text)
        assert "此條目" not in result
        assert "---" not in result
        assert "角色" in result
        assert "角色列表内容。" in result

    def test_infobox_table(self):
        """Remove infobox metadata tables."""
        text = (
            "| 入間同學入魔了！ | |\n"
            "| 出版社 | 集英社 |\n"
            "| 連載雜誌 | 週刊少年Jump |\n"
            "## 角色\n"
            "角色描述。"
        )
        result = clean_wiki_text(text)
        assert "入間同學入魔了" not in result
        assert "出版社" not in result
        assert "連載雜誌" not in result
        assert "角色" in result
        assert "角色描述。" in result

    def test_cite_note_residual(self):
        """Remove (#cite_note-...) residual markers."""
        text = "Some fact(#cite_note-1) and another(#cite_note-2) end."
        result = clean_wiki_text(text)
        assert "#cite_note" not in result
        assert "Some fact" in result
        assert "and another" in result
        assert "end." in result

    def test_cite_note_residual_with_complex_ids(self):
        """Remove cite notes with complex IDs like #cite_note-auto-2."""
        text = "Reference(#cite_note-auto-2) here."
        result = clean_wiki_text(text)
        assert "#cite_note" not in result
        assert "Reference" in result
        assert "here." in result

    def test_full_preamble_noise_scenario(self):
        """Realistic scenario: CSS + table + maintenance + infobox noise before content."""
        text = (
            ".mw-parser-output .mbox-text{border-collapse:collapse}\n"
            ".mw-parser-output .mbox-image{padding:2px}\n"
            "|  |  |\n"
            "| --- | --- |\n"
            "| 此条目或其章节有关正在连载 | |\n"
            "| 入間同學入魔了！ | |\n"
            "| 出版社 | 集英社 |\n"
            "| 导演 | 某某 |\n"
            "本頁面使用HTML注音（ruby標記）...\n"
            "## 角色\n"
            "入間達也 — 主角。\n"
            "## 剧情\n"
            "故事讲述了一个少年的冒险。"
        )
        result = clean_wiki_text(text)
        # CSS should be gone
        assert "mw-parser-output" not in result
        assert "border-collapse" not in result
        # Table rows should be gone
        assert "出版社" not in result
        assert "导演" not in result
        assert "---" not in result
        # Maintenance notice should be gone
        assert "此条目" not in result
        assert "正在连载" not in result
        # Infobox title should be gone
        assert "入間同學入魔了" not in result
        # Content should survive
        assert "角色" in result
        assert "入間達也" in result
        assert "剧情" in result
        assert "故事讲述了一个少年的冒险" in result

    def test_no_false_positive_on_normal_text_with_pipe(self):
        """Normal text containing | should not be stripped if not a table row."""
        # A line that has | in the middle but doesn't start with |
        text = "A | B is not a table row."
        result = clean_wiki_text(text)
        assert "not a table row" in result

    def test_no_false_positive_on_single_pipe_line(self):
        """A line with only a single | (not a table row) should not be stripped."""
        text = "Text before\n| just one pipe\nText after"
        result = clean_wiki_text(text)
        # Line doesn't end with |, so it's not a table row -- preserved
        assert "just one pipe" in result
        assert "Text before" in result
        assert "Text after" in result
