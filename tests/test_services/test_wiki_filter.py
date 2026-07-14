"""Tests for wiki_filter.py - section-based whitelist filter."""


class TestFilterWikiContent:
    def _filter(self, text):
        from src.services.wiki_filter import filter_wiki_content

        return filter_wiki_content(text)

    def test_preamble_always_preserved(self):
        """filter_wiki_content 只保留白名单 section，导言不保留。"""
        wiki = "这是导言内容，介绍作品基本信息。\n\n## 主题歌\n歌曲列表"
        result = self._filter(wiki)
        assert "主题歌" not in result

    def test_whitelisted_section_kept(self):
        """白名单关键词命中的 section 应被保留。"""
        wiki = "导言\n\n## 登场人物\n角色列表内容"
        result = self._filter(wiki)
        assert "登场人物" in result
        assert "角色列表内容" in result

    def test_non_whitelisted_section_dropped(self):
        """非白名单 section 应被丢弃。"""
        wiki = "导言\n\n## 制作信息\n这里是制作人员"
        result = self._filter(wiki)
        assert "制作信息" not in result
        assert "制作人员" not in result

    def test_multiple_sections_mixed(self):
        """混合 section 时，只保留白名单命中的。"""
        wiki = (
            "这是导言\n\n"
            "## 登场角色\n主角配角列表\n\n"
            "## 主题歌\n歌曲信息\n\n"
            "## 剧情\n故事情节内容\n\n"
            "## 发行信息\n商品发行"
        )
        result = self._filter(wiki)
        assert "登场角色" in result
        assert "主角配角列表" in result
        assert "剧情" in result
        assert "故事情节内容" in result
        assert "主题歌" not in result
        assert "发行信息" not in result

    def test_empty_input_returns_empty(self):
        """空输入返回空字符串。"""
        assert self._filter("") == ""

    def test_no_sections_returns_full_text(self):
        """无 section 标题时返回完整文本（全是导言）。"""
        text = "没有任何标题的纯文本内容，全部作为导言保留。"
        result = self._filter(text)
        assert result == text

    def test_english_keywords_matched(self):
        """英文关键词（Characters、Plot）也应命中白名单。"""
        wiki = "Intro text\n\n## Characters\nlist of chars\n\n## Credits\nstaff info"
        result = self._filter(wiki)
        assert "Characters" in result
        assert "list of chars" in result
        assert "Credits" not in result

    def test_level3_heading_not_section_boundary(self):
        """三级标题（### ...）不作为分割点，归属于父 section。"""
        wiki = "导言\n\n## 登场人物\n主要角色\n### 主角\n主角描述\n\n## 制作信息\n制作内容"
        result = self._filter(wiki)
        assert "登场人物" in result
        assert "主要角色" in result
        assert "主角" in result  # 三级标题保留在父 section 内（## 标记被 clean_wiki_text 折叠为 #）
        assert "制作信息" not in result

    def test_whitelist_keywords_comprehensive(self):
        """覆盖白名单中各语言关键词。"""
        from src.services.wiki_filter import filter_wiki_content

        for kw in [
            "角色",
            "人物",
            "登场",
            "Characters",
            "Cast",
            "剧情",
            "情节",
            "故事",
            "Synopsis",
            "Plot",
            "设定",
            "世界观",
            "用语",
            "背景",
            "World",
            "Setting",
            "舞台",
        ]:
            wiki = f"导言\n\n## {kw}介绍\n对应内容"
            result = filter_wiki_content(wiki)
            assert kw in result, f"白名单关键词 '{kw}' 应命中但被过滤掉了"

    def test_case_insensitive_match(self):
        """关键词匹配不区分大小写（如 characters → CHARACTERS）。"""
        wiki = "导言\n\n## CHARACTERS\n角色内容"
        result = self._filter(wiki)
        assert "CHARACTERS" in result
        assert "角色内容" in result

    def test_author_intro_excluded_from_plot(self):
        """「作者简介」命中情节白名单「简介」，但属于真人身份介绍，应被黑名单排除（斗罗大陆真实案例回归）。"""
        wiki = "导言\n\n## 作者简介\n某某，笔名某某，中国网络作家\n\n## 剧情简介\n故事梗概内容"
        result = self._filter(wiki)
        assert "作者简介" not in result
        assert "某某，笔名某某" not in result
        assert "剧情简介" in result
        assert "故事梗概内容" in result

    def test_creation_background_still_excluded_from_setting(self):
        """「創作背景」命中设定白名单「背景」，仍应被现有黑名单排除（回归验证不改坏原行为）。"""
        wiki = "导言\n\n## 創作背景\n作品创作缘由\n\n## 世界观设定\n设定内容"
        result = self._filter(wiki)
        assert "創作背景" not in result
        assert "作品创作缘由" not in result
        assert "世界观设定" in result
        assert "设定内容" in result

    def test_new_setting_keywords_matched(self):
        """新增设定组关键词（种族/種族/地理）应命中设定白名单。"""
        for kw in ["种族", "種族", "地理"]:
            wiki = f"导言\n\n## {kw}介绍\n对应内容"
            result = self._filter(wiki)
            assert kw in result, f"新增设定关键词 '{kw}' 应命中但被过滤掉了"

    def test_new_plot_keywords_matched(self):
        """新增情节组关键词（结局/結局/主线/主線）应命中情节白名单。"""
        for kw in ["结局", "結局", "主线", "主線"]:
            wiki = f"导言\n\n## {kw}\n对应内容"
            result = self._filter(wiki)
            assert kw in result, f"新增情节关键词 '{kw}' 应命中但被过滤掉了"


class TestFilterWikiContentGrouped:
    def _grouped(self, text):
        from src.services.wiki_filter import filter_wiki_content_grouped

        return filter_wiki_content_grouped(text)

    def test_no_headings_falls_back_to_characters(self):
        """全文无 ## 标题时，整篇内容整体归入 characters 组（兜底优先权）。"""
        text = "没有任何标题的纯文本，整体应归入 characters。"
        result = self._grouped(text)
        assert result["characters"] == text
        assert result["preamble"] == ""
        assert result["world_setting"] == ""
        assert result["plot"] == ""

    def test_sections_classified_into_correct_groups(self):
        """命中各组白名单关键词的 section 应归入对应分组。"""
        wiki = (
            "这是导言\n\n"
            "## 登场角色\n角色列表内容\n\n"
            "## 世界观设定\n设定相关内容\n\n"
            "## 剧情简介\n故事梗概内容\n\n"
            "## 制作信息\n与三组都无关的内容"
        )
        result = self._grouped(wiki)
        assert "这是导言" in result["preamble"]
        assert "角色列表内容" in result["characters"]
        assert "设定相关内容" in result["world_setting"]
        assert "故事梗概内容" in result["plot"]
        # 都不命中的 section 不归类到任何组
        assert "与三组都无关的内容" not in result["characters"]
        assert "与三组都无关的内容" not in result["world_setting"]
        assert "与三组都无关的内容" not in result["plot"]
        assert "与三组都无关的内容" not in result["preamble"]

    def test_priority_characters_over_setting_over_plot(self):
        """标题同时命中多组关键词时，按"角色 > 设定 > 剧情"优先级只归入一组。"""
        wiki = "## 角色设定与剧情简介\n这段内容应该只出现一次"
        result = self._grouped(wiki)
        assert "这段内容应该只出现一次" in result["characters"]
        assert "这段内容应该只出现一次" not in result["world_setting"]
        assert "这段内容应该只出现一次" not in result["plot"]

    def test_unmatched_sections_not_collected_anywhere(self):
        """都不命中白名单的 section 不归类到任何组（不污染角色组配额）。"""
        wiki = "导言文本\n\n## 制作团队\n制作人员名单\n\n## 周边商品\n商品列表"
        result = self._grouped(wiki)
        for group in ("characters", "world_setting", "plot"):
            assert "制作人员名单" not in result[group]
            assert "商品列表" not in result[group]

    def test_images_stripped_from_all_groups(self):
        """各分组内容均去掉图片标记，与 filter_wiki_content 行为一致。"""
        wiki = "## 登场角色\n![头像](http://example.com/a.png)角色描述文本"
        result = self._grouped(wiki)
        assert "![" not in result["characters"]
        assert "角色描述文本" in result["characters"]

    def test_preamble_preserved_and_images_stripped(self):
        """导言（首个标题之前的内容）始终保留，并同样去掉图片标记。"""
        wiki = "导言![封面](http://example.com/cover.png)介绍\n\n## 剧情\n故事内容"
        result = self._grouped(wiki)
        assert "导言" in result["preamble"]
        assert "介绍" in result["preamble"]
        assert "![" not in result["preamble"]

    def test_author_intro_not_classified_into_plot_group(self):
        """「作者简介」不应归入情节组（真人身份黑名单，斗罗大陆真实案例回归）。"""
        wiki = "导言\n\n## 作者简介\n某某，中国网络作家\n\n## 剧情简介\n故事梗概内容"
        result = self._grouped(wiki)
        assert "某某，中国网络作家" not in result["plot"]
        assert "某某，中国网络作家" not in result["characters"]
        assert "某某，中国网络作家" not in result["world_setting"]
        assert "故事梗概内容" in result["plot"]

    def test_actor_bio_not_classified_into_characters_group(self):
        """命中角色白名单但属于真人身份介绍的标题（如「演员简介」）不应归入角色组。"""
        wiki = "导言\n\n## 演员简介\n某演员生平介绍\n\n## 登场角色\n角色列表内容"
        result = self._grouped(wiki)
        assert "某演员生平介绍" not in result["characters"]
        assert "某演员生平介绍" not in result["plot"]
        assert "某演员生平介绍" not in result["world_setting"]
        assert "角色列表内容" in result["characters"]

    def test_creation_background_still_excluded_from_setting_group(self):
        """「創作背景」仍应被现有设定黑名单排除，不归入设定组（回归验证）。"""
        wiki = "导言\n\n## 創作背景\n作品创作缘由\n\n## 世界观设定\n设定内容"
        result = self._grouped(wiki)
        assert "作品创作缘由" not in result["world_setting"]
        assert "设定内容" in result["world_setting"]

    def test_new_keywords_classified_into_correct_groups(self):
        """新增关键词（种族/地理 → 设定组；结局/主线 → 情节组）应正确分类。"""
        wiki = (
            "导言\n\n"
            "## 种族设定\n种族内容\n\n"
            "## 地理\n地理内容\n\n"
            "## 结局\n结局内容\n\n"
            "## 主线剧情\n主线内容"
        )
        result = self._grouped(wiki)
        assert "种族内容" in result["world_setting"]
        assert "地理内容" in result["world_setting"]
        assert "结局内容" in result["plot"]
        assert "主线内容" in result["plot"]


class TestTruncateAtBoundary:
    def _truncate(self, text, budget, window=300):
        from src.services.wiki_filter import _truncate_at_boundary

        return _truncate_at_boundary(text, budget, window=window)

    def test_text_within_budget_returned_unchanged(self):
        """文本长度未超过预算时原样返回。"""
        text = "短文本内容"
        assert self._truncate(text, 100) == text

    def test_text_exactly_at_budget_returned_unchanged(self):
        """文本长度恰好等于预算时原样返回。"""
        text = "x" * 50
        assert self._truncate(text, 50) == text

    def test_empty_text_returns_empty(self):
        """空文本输入返回空字符串。"""
        assert self._truncate("", 100) == ""

    def test_zero_budget_hard_cuts_when_no_boundary_in_window(self):
        """budget=0 且窗口内无自然边界时，应硬切为空字符串（而非负数切片整段保留）。"""
        # 无段落分隔、无句末标点的纯文本，强制触发硬切 fallback
        assert self._truncate("无标点无分隔的纯文本内容超过预算", 0) == ""

    def test_negative_budget_clamped_to_zero(self):
        """budget 为负数时应先夹紧到 0 再处理，不能让 Python 负数切片 text[:-5]
        从文本末尾保留内容（与"截断到预算"的语义相悖）。"""
        text = "x" * 100  # 无任何边界标记，必然走硬切 fallback
        result = self._truncate(text, -5)
        assert result == ""
        assert self._truncate(text, -100) == ""
        # 负数 budget 与 budget=0 行为应一致（统一夹紧）
        assert self._truncate(text, -5) == self._truncate(text, 0)

    def test_prefers_paragraph_boundary_near_budget(self):
        """优先在 budget 附近的 \\n\\n 段落分隔处截断。"""
        # 段落分隔位于 budget(=50) 附近的窗口内
        text = "A" * 45 + "\n\n" + "B" * 100
        result = self._truncate(text, 50, window=20)
        assert result == "A" * 45 + "\n\n"
        assert "B" not in result

    def test_falls_back_to_sentence_punctuation(self):
        """找不到段落分隔时，回退到句末标点处截断。"""
        text = "中文句子一。" + "中文句子二。" + "X" * 200
        # budget 落在窗口能覆盖到第一个句号之后的位置
        result = self._truncate(text, 6, window=10)
        assert result.endswith("。")
        assert "X" not in result

    def test_hard_cut_when_no_boundary_found(self):
        """窗口内既无段落分隔也无句末标点时，直接在 budget 处硬切。"""
        text = "a" * 1000
        result = self._truncate(text, 500, window=50)
        assert len(result) == 500

    def test_truncation_window_does_not_exceed_text_length(self):
        """budget 接近文本末尾时窗口边界不越界，不抛异常。"""
        text = "段落甲内容。\n\n" + "段落乙内容很长很长很长。"
        result = self._truncate(text, len(text) - 1, window=300)
        assert len(result) <= len(text)


class TestWikiSectionBudgets:
    def test_all_scales_present(self):
        """四档（standard/detailed/deep/all）预算配置齐全。"""
        from src.services.wiki_filter import WIKI_SECTION_BUDGETS

        assert set(WIKI_SECTION_BUDGETS.keys()) == {
            "standard",
            "detailed",
            "deep",
            "all",
        }

    def test_each_scale_has_three_categories(self):
        """每档预算均包含 characters / plot / world_setting 三个配额。"""
        from src.services.wiki_filter import WIKI_SECTION_BUDGETS

        for scale, budget in WIKI_SECTION_BUDGETS.items():
            assert set(budget.keys()) == {"characters", "plot", "world_setting"}, scale

    def test_plot_and_world_setting_fixed_across_scales(self):
        """剧情/设定预算固定不随档位膨胀，不与角色抢资源（核心原则）。"""
        from src.services.wiki_filter import WIKI_SECTION_BUDGETS

        plot_values = {b["plot"] for b in WIKI_SECTION_BUDGETS.values()}
        setting_values = {b["world_setting"] for b in WIKI_SECTION_BUDGETS.values()}
        assert plot_values == {8000}
        assert setting_values == {9000}

    def test_characters_budget_increases_with_scale(self):
        """角色预算严格随档位升高（角色信息优先级最高，按档位走）。"""
        from src.services.wiki_filter import WIKI_SECTION_BUDGETS

        order = ["standard", "detailed", "deep", "all"]
        char_budgets = [WIKI_SECTION_BUDGETS[s]["characters"] for s in order]
        assert char_budgets == sorted(char_budgets)
        assert len(set(char_budgets)) == len(char_budgets)  # 严格递增，无重复

    def test_total_budget_per_scale_matches_design(self):
        """各档预算总和应符合设计规格（32000/67000/117000/317000）。"""
        from src.services.wiki_filter import WIKI_SECTION_BUDGETS

        expected_totals = {
            "standard": 32000,
            "detailed": 67000,
            "deep": 117000,
            "all": 317000,
        }
        for scale, expected in expected_totals.items():
            assert sum(WIKI_SECTION_BUDGETS[scale].values()) == expected


class TestSplitWikiGroupedRaw:
    """Test split_wiki_grouped_raw: pure split, no text transformation."""

    def test_no_headings_entire_content_to_characters(self):
        """No ## headings -> entire content goes to characters."""
        from src.services.wiki_filter import split_wiki_grouped_raw

        text = "Just some text with no headings."
        result = split_wiki_grouped_raw(text)
        assert result["characters"] == text
        assert result["preamble"] == ""
        assert result["world_setting"] == ""
        assert result["plot"] == ""

    def test_preserves_link_syntax(self):
        """Raw split preserves markdown/wiki link syntax unchanged."""
        from src.services.wiki_filter import split_wiki_grouped_raw

        text = "Preamble\n\n## Characters\nSee [[Naruto|Naruto Uzumaki]] and [link](http://x.com)"
        result = split_wiki_grouped_raw(text)
        assert "[[Naruto|Naruto Uzumaki]]" in result["characters"]
        assert "[link](http://x.com)" in result["characters"]

    def test_preserves_image_syntax(self):
        """Raw split preserves image syntax unchanged."""
        from src.services.wiki_filter import split_wiki_grouped_raw

        text = "## Characters\n![photo](http://img.png) character text"
        result = split_wiki_grouped_raw(text)
        assert "![" in result["characters"]
        assert "![photo](http://img.png)" in result["characters"]

    def test_preserves_template_syntax(self):
        """Raw split preserves {{template}} syntax unchanged."""
        from src.services.wiki_filter import split_wiki_grouped_raw

        text = "## Characters\n{{Infobox|name=Test}} content"
        result = split_wiki_grouped_raw(text)
        assert "{{Infobox|name=Test}}" in result["characters"]

    def test_sections_classified_correctly(self):
        """Sections are classified into correct groups."""
        from src.services.wiki_filter import split_wiki_grouped_raw

        text = (
            "Preamble\n\n"
            "## Characters\nchar content\n\n"
            "## World Setting\nsetting content\n\n"
            "## Plot\nplot content"
        )
        result = split_wiki_grouped_raw(text)
        assert "Preamble" in result["preamble"]
        assert "char content" in result["characters"]
        assert "setting content" in result["world_setting"]
        assert "plot content" in result["plot"]

    def test_preamble_merged_into_characters(self):
        """After raw split, caller can merge preamble into characters."""
        from src.services.wiki_filter import split_wiki_grouped_raw

        text = "Preamble intro\n\n## Characters\nchar list"
        result = split_wiki_grouped_raw(text)
        assert "Preamble intro" in result["preamble"]
        assert "Preamble intro" not in result["characters"]
        # Caller merges: preamble + characters
        merged = result["preamble"] + result["characters"]
        assert "Preamble intro" in merged
        assert "char list" in merged


class TestTruncateTrailingFooter:
    """百度百科等非维基页面末尾页脚噪音截断（相关搜索/新手上路/版权行）。

    样本结构贴近真实百度百科抓取内容：标题下紧跟"播报"/"编辑"按钮文字，
    最后一个标题后跟着"相关搜索"（六个井号）+ "新手上路"等页脚区块。
    """

    _REAL_SAMPLE = (
        "## 作品设定\n\n"
        "播报\n\n"
        "编辑\n\n"
        "本作讲述的是一个发生在虚构大陆上的冒险故事，"
        "主角一行人为了寻找传说中的圣物而踏上旅途。\n\n"
        "###### 相关搜索\n\n"
        "* [同名小说下载](https://baike.baidu.com/xxx)\n"
        "* [同人漫画在线看](https://baike.baidu.com/yyy)\n\n"
        "新手上路\n\n"
        "* 我是新手\n"
        "* 我要投诉\n\n"
        "©2024 Baidu 使用百度前必读\n"
    )

    def test_split_wiki_headings_drops_footer(self):
        """相关搜索及之后内容应被截断掉，标题正文保留。"""
        from src.services.wiki_filter import split_wiki_grouped_raw

        result = split_wiki_grouped_raw(self._REAL_SAMPLE)
        assert "作品设定" in result["world_setting"]
        assert "本作讲述的是一个发生在虚构大陆上的冒险故事" in result["world_setting"]
        assert "相关搜索" not in result["world_setting"]
        assert "同名小说下载" not in result["world_setting"]
        assert "新手上路" not in result["world_setting"]
        assert "Baidu" not in result["world_setting"]

    def test_filter_wiki_content_grouped_drops_footer(self):
        """filter_wiki_content_grouped（清洗后版本）同样不含页脚噪音。"""
        from src.services.wiki_filter import filter_wiki_content_grouped

        result = filter_wiki_content_grouped(self._REAL_SAMPLE)
        assert "本作讲述的是一个发生在虚构大陆上的冒险故事" in result["world_setting"]
        assert "相关搜索" not in result["world_setting"]
        assert "新手上路" not in result["world_setting"]
        assert "Baidu" not in result["world_setting"]

    def test_no_anchor_present_is_noop(self):
        """维基百科等没有这几个锚点文本的正文：截断函数应无操作（透传原文）。"""
        from src.services.wiki_filter import _truncate_trailing_footer

        text = "## Characters\nNaruto Uzumaki is the main character.\n\n## Plot\nA long story."
        assert _truncate_trailing_footer(text) == text

    def test_earliest_anchor_wins_when_multiple_present(self):
        """多个锚点同时出现时，取最靠前的位置截断。"""
        from src.services.wiki_filter import _truncate_trailing_footer

        text = "正文内容\n\n新手上路\n\n###### 相关搜索\n\n©2024 Baidu\n"
        truncated = _truncate_trailing_footer(text)
        assert truncated == "正文内容\n\n"


class TestFilterWikiContentGroupedCleaned:
    """Test that filter_wiki_content_grouped now uses clean_wiki_text."""

    def test_images_stripped_from_output(self):
        """filter_wiki_content_grouped strips images via clean_wiki_text."""
        from src.services.wiki_filter import filter_wiki_content_grouped

        text = "## Characters\n![photo](http://img.png) character text"
        result = filter_wiki_content_grouped(text)
        assert "![" not in result["characters"]
        assert "character text" in result["characters"]

    def test_links_cleaned_from_output(self):
        """filter_wiki_content_grouped cleans links via clean_wiki_text."""
        from src.services.wiki_filter import filter_wiki_content_grouped

        text = "## Characters\nSee [here](http://x.com) and [[Page|Display]]"
        result = filter_wiki_content_grouped(text)
        assert "http://x.com" not in result["characters"]
        assert "[[" not in result["characters"]
        assert "here" in result["characters"]
        assert "Display" in result["characters"]

    def test_templates_cleaned_from_output(self):
        """filter_wiki_content_grouped cleans templates."""
        from src.services.wiki_filter import filter_wiki_content_grouped

        text = "## Characters\n{{Infobox|Test}} content"
        result = filter_wiki_content_grouped(text)
        assert "{{" not in result["characters"]
        assert "content" in result["characters"]


class TestFilterWikiContentCleaned:
    """Test that filter_wiki_content now uses clean_wiki_text."""

    def test_images_stripped(self):
        """filter_wiki_content strips images via clean_wiki_text."""
        from src.services.wiki_filter import filter_wiki_content

        text = "## Characters\n![photo](http://img.png) character text"
        result = filter_wiki_content(text)
        assert "![" not in result
        assert "character text" in result

    def test_templates_stripped(self):
        """filter_wiki_content strips templates via clean_wiki_text."""
        from src.services.wiki_filter import filter_wiki_content

        text = "## Characters\n{{Infobox|Test}} content"
        result = filter_wiki_content(text)
        assert "{{" not in result
        assert "content" in result
