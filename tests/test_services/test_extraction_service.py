"""Tests for ExtractionService - core element extraction."""

from unittest.mock import AsyncMock, patch

import pytest

from src.models.world import Element

FIXED_TABS = ["场所", "势力", "规则", "事件", "物品", "文化", "其他"]


class TestExtractCharacters:
    """extract_characters() - 从 wiki 角色资料中提取角色并分级。"""

    @pytest.fixture
    def mock_llm(self):
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_llm):
        from src.services.extraction_service import ExtractionService

        return ExtractionService(llm=mock_llm)

    async def test_returns_list_of_dicts_with_name_and_tier(self, service, mock_llm):
        """应返回包含 name 和 tier 的字典列表。"""
        mock_llm.complete_json.return_value = [
            {"name": "主角A", "tier": "core"},
            {"name": "配角B", "tier": "supporting"},
        ]

        result = await service.extract_characters(
            wiki_characters="角色资料内容" * 20, char_target=5, title="测试"
        )

        assert len(result) == 2
        assert result[0]["name"] == "主角A"
        assert result[0]["tier"] == "core"
        assert result[1]["name"] == "配角B"
        assert result[1]["tier"] == "supporting"

    async def test_empty_wiki_returns_empty_list(self, service, mock_llm):
        """wiki_characters 为空时返回空列表，不调用 LLM。"""
        result = await service.extract_characters(wiki_characters="", char_target=5, title="测试")
        mock_llm.complete_json.assert_not_called()
        assert result == []

    async def test_short_wiki_returns_empty_list(self, service, mock_llm):
        """wiki_characters 长度 < 100 时返回空列表。"""
        result = await service.extract_characters(
            wiki_characters="短内容", char_target=5, title="测试"
        )
        mock_llm.complete_json.assert_not_called()
        assert result == []

    async def test_invalid_tier_defaults_to_extra(self, service, mock_llm):
        """tier 不在 core/supporting/extra 中时默认为 extra。"""
        mock_llm.complete_json.return_value = [
            {"name": "角色X", "tier": "unknown"},
            {"name": "角色Y", "tier": "core"},
        ]

        result = await service.extract_characters(
            wiki_characters="角色资料内容" * 20, char_target=5, title="测试"
        )

        assert result[0]["tier"] == "extra"
        assert result[1]["tier"] == "core"

    async def test_missing_name_is_filtered(self, service, mock_llm):
        """缺少 name 的条目应被过滤。"""
        mock_llm.complete_json.return_value = [
            {"name": "有效角色", "tier": "core"},
            {"tier": "supporting"},  # 缺少 name
            {"name": "", "tier": "extra"},  # 空 name
        ]

        result = await service.extract_characters(
            wiki_characters="角色资料内容" * 20, char_target=5, title="测试"
        )

        assert len(result) == 1
        assert result[0]["name"] == "有效角色"

    async def test_dict_unwrap_characters_key(self, service, mock_llm):
        """LLM 返回 dict 包装时应自动 unwrap。"""
        mock_llm.complete_json.return_value = {
            "characters": [
                {"name": "角色A", "tier": "core"},
            ]
        }

        result = await service.extract_characters(
            wiki_characters="角色资料内容" * 20, char_target=5, title="测试"
        )

        assert len(result) == 1
        assert result[0]["name"] == "角色A"

    async def test_wiki_used_as_cacheable_prefix(self, service, mock_llm):
        """wiki_characters 应作为 cacheable_system_prefix 传入 LLM。"""
        mock_llm.complete_json.return_value = [
            {"name": "角色A", "tier": "core"},
        ]
        wiki = "角色资料内容" * 20

        await service.extract_characters(wiki_characters=wiki, char_target=5, title="测试")

        call_kwargs = mock_llm.complete_json.call_args.kwargs
        assert call_kwargs.get("cacheable_system_prefix") == wiki


class TestExtractElements:
    """extract_elements() - 从 wiki 剧情+设定中提取非角色元素。"""

    @pytest.fixture
    def mock_llm(self):
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_llm):
        from src.services.extraction_service import ExtractionService

        return ExtractionService(llm=mock_llm)

    async def test_returns_seven_tabs(self, service, mock_llm):
        """应返回包含全部 7 个固定 tab 的字典。"""
        mock_llm.complete_json.return_value = {
            "场所": [{"name": "学校", "brief": "学校简介"}],
            "势力": [],
            "规则": [{"name": "魔法", "brief": "魔法体系"}],
            "事件": [],
            "物品": [],
            "文化": [],
            "其他": [],
        }

        result = await service.extract_elements(
            wiki_plot="剧情资料", wiki_world_setting="设定资料", title="测试", scale="standard"
        )

        for tab in FIXED_TABS:
            assert tab in result, f"缺少 tab: {tab}"

    async def test_empty_tab_returns_empty_list(self, service, mock_llm):
        """LLM 返回某 tab 为空时应返回空列表。"""
        mock_llm.complete_json.return_value = {tab: [] for tab in FIXED_TABS}

        result = await service.extract_elements(
            wiki_plot="剧情", wiki_world_setting="设定", title="测试", scale="standard"
        )

        assert result["事件"] == []

    async def test_missing_tab_filled_with_empty_list(self, service, mock_llm):
        """LLM 漏掉某 tab 时，应自动补全为空列表。"""
        partial = {tab: [] for tab in FIXED_TABS}
        partial.pop("文化")
        mock_llm.complete_json.return_value = partial

        result = await service.extract_elements(
            wiki_plot="剧情", wiki_world_setting="设定", title="测试", scale="standard"
        )

        assert result["文化"] == []

    async def test_items_must_have_name_and_brief(self, service, mock_llm):
        """每项元素应有 name 和 brief，缺少的应被过滤。"""
        mock_llm.complete_json.return_value = {
            "场所": [
                {"name": "学校", "brief": "学校简介"},
                {"brief": "无名"},  # 缺少 name
                {"name": "有效", "brief": "简介"},
            ],
            "势力": [],
            "规则": [],
            "事件": [],
            "物品": [],
            "文化": [],
            "其他": [],
        }

        result = await service.extract_elements(
            wiki_plot="剧情", wiki_world_setting="设定", title="测试", scale="standard"
        )

        assert len(result["场所"]) == 2
        assert result["场所"][0]["name"] == "学校"
        assert result["场所"][1]["name"] == "有效"

    async def test_wiki_combined_as_cacheable_prefix(self, service, mock_llm):
        """wiki_plot + wiki_world_setting 合并后应作为 cacheable_system_prefix。"""
        mock_llm.complete_json.return_value = {tab: [] for tab in FIXED_TABS}

        await service.extract_elements(
            wiki_plot="剧情内容",
            wiki_world_setting="设定内容",
            title="测试",
            scale="standard",
        )

        call_kwargs = mock_llm.complete_json.call_args.kwargs
        prefix = call_kwargs.get("cacheable_system_prefix", "")
        assert "设定内容" in prefix
        assert "剧情内容" in prefix

    async def test_list_response_mapped_to_tabs(self, service, mock_llm):
        """LLM 返回裸数组时应按 FIXED_TABS 顺序映射。"""
        mock_llm.complete_json.return_value = [
            [{"name": "场所A", "brief": "简介"}],  # 场所
            [],  # 势力
            [],  # 规则
            [],  # 事件
            [],  # 物品
            [],  # 文化
            [],  # 其他
        ]

        result = await service.extract_elements(
            wiki_plot="剧情", wiki_world_setting="设定", title="测试", scale="standard"
        )

        assert len(result["场所"]) == 1
        assert result["场所"][0]["name"] == "场所A"


class TestGenerateDetailsBatch:
    """generate_details_batch() - 分批生成 detail。"""

    @pytest.fixture
    def mock_llm(self):
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_llm):
        from src.services.extraction_service import ExtractionService

        return ExtractionService(llm=mock_llm)

    def _make_char_response(self, names: list[str]) -> list[dict]:
        return [{"name": n, "detail": f"{n}详情", "category": "characters"} for n in names]

    async def test_character_extra_batch_size_20(self, service, mock_llm):
        """批次大小为 20。"""
        names = [f"E{i}" for i in range(22)]  # 22 items → 2 batches
        mock_llm.complete_json.side_effect = [
            self._make_char_response(names[:20]),
            self._make_char_response(names[20:]),
        ]

        result = await service.generate_details_batch(
            tab="characters",
            names=names,
            wiki_content="wiki",
            brief_map={n: f"{n}简介" for n in names},
        )

        assert mock_llm.complete_json.call_count == 2
        assert len(result) == 22

    async def test_non_character_tab_batch_size_20(self, service, mock_llm):
        """非角色 tab，批次大小为 20。"""
        names = [f"场所{i}" for i in range(22)]  # 22 items → 2 batches
        mock_llm.complete_json.side_effect = [
            [{"name": n, "detail": "d", "category": "场所"} for n in names[:20]],
            [{"name": n, "detail": "d", "category": "场所"} for n in names[20:]],
        ]

        result = await service.generate_details_batch(
            tab="场所",
            names=names,
            wiki_content="wiki",
        )

        assert mock_llm.complete_json.call_count == 2
        assert len(result) == 22

    async def test_elements_have_required_fields(self, service, mock_llm):
        """生成的 Element 应有 id/name/category/brief/detail 字段。"""
        from src.models.world import Element

        mock_llm.complete_json.return_value = [
            {"name": "场所X", "detail": "详情", "category": "场所"}
        ]

        result = await service.generate_details_batch(
            tab="场所",
            names=["场所X"],
            wiki_content="wiki",
            brief_map={"场所X": "简介"},
        )

        assert len(result) == 1
        assert isinstance(result[0], Element)
        assert result[0].id.startswith("elem_")
        assert result[0].name == "场所X"
        assert result[0].brief == "简介"

    async def test_wiki_used_as_cacheable_prefix(self, service, mock_llm):
        """wiki_content 应作为 cacheable_system_prefix 传入 LLM 调用。"""
        mock_llm.complete_json.return_value = [{"name": "场所Y", "detail": "d", "category": "场所"}]

        await service.generate_details_batch(
            tab="场所",
            names=["场所Y"],
            wiki_content="这是wiki全文",
        )

        call_kwargs = mock_llm.complete_json.call_args.kwargs
        assert call_kwargs.get("cacheable_system_prefix") == "这是wiki全文"

    async def test_empty_names_returns_empty_list(self, service, mock_llm):
        """空 names 列表应直接返回空，不调用 LLM。"""
        result = await service.generate_details_batch(tab="场所", names=[], wiki_content="wiki")
        mock_llm.complete_json.assert_not_called()
        assert result == []


class TestFormatElementWithTab:
    """_format_element_with_tab() - 格式化元素名+类别标签。"""

    def test_basic_format(self):
        from src.services.extraction_service import _format_element_with_tab

        assert _format_element_with_tab("东京", "场所") == "- 东京（类别：场所）"

    def test_different_tabs(self):
        from src.services.extraction_service import _format_element_with_tab

        assert _format_element_with_tab("暗影议会", "势力") == "- 暗影议会（类别：势力）"
        assert _format_element_with_tab("魔法", "规则") == "- 魔法（类别：规则）"

    def test_special_characters_in_name(self):
        from src.services.extraction_service import _format_element_with_tab

        result = _format_element_with_tab("「幻影」", "物品")
        assert result == "- 「幻影」（类别：物品）"


class TestGenerateDetailsUnified:
    """generate_details_unified() - 跨 tab 统一批量生成 detail。"""

    @pytest.fixture
    def mock_llm(self):
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_llm):
        from src.services.extraction_service import ExtractionService

        return ExtractionService(llm=mock_llm)

    async def test_unified_batching_75_elements_across_3_tabs(self, service, mock_llm):
        """75 个元素跨 3 个 tab → 4 批（20+20+20+15）。"""
        elements_with_tabs = (
            [(f"场所{i}", "场所") for i in range(25)]
            + [(f"势力{i}", "势力") for i in range(25)]
            + [(f"规则{i}", "规则") for i in range(25)]
        )
        brief_map = {name: f"{name}简介" for name, _ in elements_with_tabs}

        call_batches = []

        async def capture_batch(*args, **kwargs):
            # Extract names from the prompt to count batch size
            prompt = kwargs.get("prompt", "")
            count = prompt.count("\n- ")
            call_batches.append(count)
            return [{"name": f"场所{i}", "detail": "d", "category": "场所"} for i in range(count)]

        mock_llm.complete_json.side_effect = capture_batch

        await service.generate_details_unified(
            elements_with_tabs=elements_with_tabs,
            wiki_content="wiki",
            brief_map=brief_map,
        )

        assert mock_llm.complete_json.call_count == 4
        assert call_batches == [20, 20, 20, 15]

    async def test_empty_elements_returns_empty(self, service, mock_llm):
        """空列表应直接返回空，不调用 LLM。"""
        result = await service.generate_details_unified(
            elements_with_tabs=[],
            wiki_content="wiki",
            brief_map=None,
        )
        mock_llm.complete_json.assert_not_called()
        assert result == []

    async def test_single_tab_elements(self, service, mock_llm):
        """只有 1 个 tab 的元素，行为等价于原来的 generate_details_batch。"""
        elements_with_tabs = [(f"场所{i}", "场所") for i in range(3)]
        mock_llm.complete_json.return_value = [
            {"name": f"场所{i}", "detail": "d", "category": "场所"} for i in range(3)
        ]

        result = await service.generate_details_unified(
            elements_with_tabs=elements_with_tabs,
            wiki_content="wiki",
            brief_map={"场所0": "简介0", "场所1": "简介1", "场所2": "简介2"},
        )

        assert len(result) == 3
        for elem in result:
            assert isinstance(elem, Element)
            assert elem.category == "场所"

    async def test_prompt_contains_tab_labels(self, service, mock_llm):
        """prompt 应包含每个元素的 tab 标签。"""
        elements_with_tabs = [("东京", "场所"), ("暗影议会", "势力")]
        mock_llm.complete_json.return_value = [
            {"name": "东京", "detail": "d", "category": "场所"},
            {"name": "暗影议会", "detail": "d", "category": "势力"},
        ]

        await service.generate_details_unified(
            elements_with_tabs=elements_with_tabs,
            wiki_content="wiki",
            brief_map=None,
        )

        call_kwargs = mock_llm.complete_json.call_args.kwargs
        prompt = call_kwargs["prompt"]
        assert "东京（类别：场所）" in prompt
        assert "暗影议会（类别：势力）" in prompt

    async def test_brief_map_preserved(self, service, mock_llm):
        """brief_map 中的 brief 应正确透传到 Element。"""
        elements_with_tabs = [("东京", "场所")]
        mock_llm.complete_json.return_value = [
            {"name": "东京", "detail": "详细描述", "category": "场所"}
        ]

        result = await service.generate_details_unified(
            elements_with_tabs=elements_with_tabs,
            wiki_content="wiki",
            brief_map={"东京": "日本首都"},
        )

        assert len(result) == 1
        assert result[0].brief == "日本首都"

    async def test_category_matches_tab(self, service, mock_llm):
        """每个 Element 的 category 应与对应 tab 一致。"""
        elements_with_tabs = [("东京", "场所"), ("暗影议会", "势力"), ("魔法", "规则")]
        mock_llm.complete_json.return_value = [
            {"name": "东京", "detail": "d", "category": "场所"},
            {"name": "暗影议会", "detail": "d", "category": "势力"},
            {"name": "魔术", "detail": "d", "category": "规则"},
        ]

        result = await service.generate_details_unified(
            elements_with_tabs=elements_with_tabs,
            wiki_content="wiki",
            brief_map=None,
        )

        cat_map = {e.name: e.category for e in result}
        assert cat_map["东京"] == "场所"
        assert cat_map["暗影议会"] == "势力"

    async def test_category_fallback_to_tab_when_llm_omits(self, service, mock_llm):
        """LLM 返回缺少 category 时，应回退到输入的 tab 标签。"""
        elements_with_tabs = [("东京", "场所"), ("暗影议会", "势力")]
        # LLM 不返回 category 字段
        mock_llm.complete_json.return_value = [
            {"name": "东京", "detail": "日本首都"},
            {"name": "暗影议会", "detail": "秘密组织"},
        ]

        result = await service.generate_details_unified(
            elements_with_tabs=elements_with_tabs,
            wiki_content="wiki",
            brief_map=None,
        )

        cat_map = {e.name: e.category for e in result}
        assert cat_map["东京"] == "场所"
        assert cat_map["暗影议会"] == "势力"

    async def test_wiki_used_as_cacheable_prefix(self, service, mock_llm):
        """wiki_content 应作为 cacheable_system_prefix 传入 LLM。"""
        elements_with_tabs = [("东京", "场所")]
        mock_llm.complete_json.return_value = [{"name": "东京", "detail": "d", "category": "场所"}]

        await service.generate_details_unified(
            elements_with_tabs=elements_with_tabs,
            wiki_content="这是wiki全文",
            brief_map=None,
        )

        call_kwargs = mock_llm.complete_json.call_args.kwargs
        assert call_kwargs.get("cacheable_system_prefix") == "这是wiki全文"


class TestExtractWithWikiPipeline:
    """extract() 有 wiki 数据时使用并行流水线。"""

    @pytest.fixture
    def mock_llm(self):
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_llm):
        from src.services.extraction_service import ExtractionService

        return ExtractionService(llm=mock_llm)

    async def test_extract_with_wiki_returns_elements_and_char_candidates(self, service, mock_llm):
        """有 wiki 数据时 extract() 应返回 (elements, char_candidates) 元组。"""
        from unittest.mock import AsyncMock, patch

        from src.models.world import Element

        char_result = [{"name": "主角A", "tier": "core"}]
        elem_result = {
            "场所": [{"name": "学校", "brief": "学校简介"}],
            "势力": [],
            "规则": [],
            "事件": [],
            "物品": [],
            "文化": [],
            "其他": [],
        }

        with (
            patch.object(service, "extract_characters", AsyncMock(return_value=char_result)),
            patch.object(service, "extract_elements", AsyncMock(return_value=elem_result)),
            patch.object(
                service,
                "generate_details_unified",
                AsyncMock(
                    return_value=[
                        Element(id="elem_2", category="场所", name="学校", brief="b", detail="d"),
                    ]
                ),
            ),
        ):
            result = await service.extract(
                title="T",
                author="A",
                description="D",
                wiki_characters="角色资料" * 20,
                wiki_plot="剧情资料",
                wiki_world_setting="设定资料",
                scale="detailed",
            )

        assert isinstance(result, tuple)
        assert len(result) == 2
        elements, char_candidates = result
        assert len(elements) == 1
        assert elements[0].name == "学校"
        assert len(char_candidates) == 1
        assert char_candidates[0]["name"] == "主角A"
        assert char_candidates[0]["tier"] == "core"

    async def test_extract_without_wiki_uses_pipeline(self, service, mock_llm):
        """无 wiki 数据时 extract() 也走流水线。"""
        with patch.object(service, "_extract_pipeline", new_callable=AsyncMock) as mock_pipeline:
            mock_pipeline.return_value = (
                [Element(id="elem_1", category="场所", name="学校", brief="b", detail="d")],
                [{"name": "角色X", "tier": "core"}],
            )
            result = await service.extract(
                title="T",
                author="A",
                description="D",
                scale="standard",
            )
            mock_pipeline.assert_called_once()

        assert isinstance(result, tuple)
        elements, char_candidates = result
        assert len(elements) == 1
        assert len(char_candidates) == 1

    async def test_extract_pipeline_all_scale_no_boundary_no_segments(self, service, mock_llm):
        """all 档位 wiki_characters 超预算但无 ---SOURCE_BOUNDARY--- 时不应触发分段提取。"""
        char_result = [{"name": "角色A", "tier": "core"}]
        elem_result = {tab: [] for tab in FIXED_TABS}

        with (
            patch.object(service, "_split_characters_segments") as mock_split,
            patch.object(
                service, "extract_characters", AsyncMock(return_value=char_result)
            ) as mock_chars,
            patch.object(service, "extract_elements", AsyncMock(return_value=elem_result)),
            patch.object(service, "generate_details_unified", AsyncMock(return_value=[])),
            patch(
                "src.services.wiki_filter.WIKI_SECTION_BUDGETS",
                {
                    "all": {"characters": 100},
                    "standard": {"characters": 15000, "plot": 8000, "world_setting": 9000},
                },
            ),
        ):
            await service._extract_pipeline(
                title="T",
                author="A",
                description="D",
                scale="all",
                ref_content=None,
                wiki_characters="x" * 200,  # exceeds mocked budget of 100, but no SOURCE_BOUNDARY
                wiki_plot=None,
                wiki_world_setting=None,
            )

        mock_split.assert_not_called()
        call_args = mock_chars.call_args
        assert call_args.kwargs.get("segments") is None

    async def test_extract_pipeline_source_boundary_triggers_segment_extraction(
        self, service, mock_llm
    ):
        """wiki_characters 包含 ---SOURCE_BOUNDARY--- 分隔符时，无论档位均触发分段提取。"""
        from src.services.extraction_service import WikiSegment

        char_result = [{"name": "角色A", "tier": "core"}]
        elem_result = {tab: [] for tab in FIXED_TABS}
        segments = [WikiSegment(text="segment1", source="主链", index=0)]
        wiki_with_boundary = (
            "角色A介绍" * 20
            + "\n\n---SOURCE_BOUNDARY: https://example.com/subpage---\n\n"
            + "角色B介绍" * 20
        )

        with (
            patch.object(
                service, "_split_characters_segments", return_value=segments
            ) as mock_split,
            patch.object(
                service, "extract_characters", AsyncMock(return_value=char_result)
            ) as mock_chars,
            patch.object(service, "extract_elements", AsyncMock(return_value=elem_result)),
            patch.object(service, "generate_details_unified", AsyncMock(return_value=[])),
        ):
            await service._extract_pipeline(
                title="T",
                author="A",
                description="D",
                scale="standard",
                ref_content=None,
                wiki_characters=wiki_with_boundary,
                wiki_plot=None,
                wiki_world_setting=None,
            )

        mock_split.assert_called_once()
        call_kwargs = mock_chars.call_args.kwargs
        assert call_kwargs.get("segments") == segments

    async def test_extract_pipeline_all_scale_under_budget_no_segments(self, service, mock_llm):
        """无 ---SOURCE_BOUNDARY--- 且未超预算时不应触发分段提取。"""
        char_result = [{"name": "角色A", "tier": "core"}]
        elem_result = {tab: [] for tab in FIXED_TABS}

        with (
            patch.object(service, "_split_characters_segments") as mock_split,
            patch.object(
                service, "extract_characters", AsyncMock(return_value=char_result)
            ) as mock_chars,
            patch.object(service, "extract_elements", AsyncMock(return_value=elem_result)),
            patch.object(service, "generate_details_unified", AsyncMock(return_value=[])),
            patch(
                "src.services.wiki_filter.WIKI_SECTION_BUDGETS",
                {
                    "all": {"characters": 1000},
                    "standard": {"characters": 15000, "plot": 8000, "world_setting": 9000},
                },
            ),
        ):
            await service._extract_pipeline(
                title="T",
                author="A",
                description="D",
                scale="all",
                ref_content=None,
                wiki_characters="x" * 200,  # under mocked budget of 1000
                wiki_plot=None,
                wiki_world_setting=None,
            )

        mock_split.assert_not_called()
        call_args = mock_chars.call_args
        # segments should not be in kwargs (or be None)
        assert call_args.kwargs.get("segments") is None

    async def test_extract_pipeline_source_boundary_under_budget_still_segments(
        self, service, mock_llm
    ):
        """非 all 档位，wiki_characters 有 ---SOURCE_BOUNDARY--- 但未超预算，仍应触发分段提取。"""
        from src.services.extraction_service import WikiSegment

        char_result = [{"name": "角色A", "tier": "core"}]
        elem_result = {tab: [] for tab in FIXED_TABS}
        segments = [WikiSegment(text="segment1", source="主链", index=0)]
        # 有 SOURCE_BOUNDARY 分隔符，总长度远小于 standard 的 15000 预算
        wiki_with_boundary = (
            "角色A是主角介绍" * 20
            + "\n\n---SOURCE_BOUNDARY: https://example.com/subpage---\n\n"
            + "角色B是配角介绍" * 20
        )

        with (
            patch.object(
                service, "_split_characters_segments", return_value=segments
            ) as mock_split,
            patch.object(
                service, "extract_characters", AsyncMock(return_value=char_result)
            ) as mock_chars,
            patch.object(service, "extract_elements", AsyncMock(return_value=elem_result)),
            patch.object(service, "generate_details_unified", AsyncMock(return_value=[])),
        ):
            await service._extract_pipeline(
                title="T",
                author="A",
                description="D",
                scale="standard",
                ref_content=None,
                wiki_characters=wiki_with_boundary,
                wiki_plot=None,
                wiki_world_setting=None,
            )

        mock_split.assert_called_once()
        call_kwargs = mock_chars.call_args.kwargs
        assert call_kwargs.get("segments") == segments


class TestEnforceTierDistribution:
    """_enforce_tier_distribution() - 层级分布强制修正。"""

    def test_small_list_no_change(self):
        """n <= 20 时不修改。"""
        from src.services.extraction_service import ExtractionService

        chars = [{"name": f"C{i}", "tier": "supporting"} for i in range(20)]
        result = ExtractionService._enforce_tier_distribution(chars)
        assert all(c["tier"] == "supporting" for c in result)

    def test_extra_ratio_already_adequate(self):
        """extra 占比 >= 50% 时不修改。"""
        from src.services.extraction_service import ExtractionService

        chars = (
            [{"name": f"Core{i}", "tier": "core"} for i in range(5)]
            + [{"name": f"Sup{i}", "tier": "supporting"} for i in range(5)]
            + [{"name": f"Ext{i}", "tier": "extra"} for i in range(20)]
        )
        result = ExtractionService._enforce_tier_distribution(chars)
        assert sum(1 for c in result if c["tier"] == "extra") == 20

    def test_demotes_tail_supporting_to_extra(self):
        """extra 不足时，从尾部降级 supporting 为 extra。"""
        from src.services.extraction_service import ExtractionService

        # 25 chars: 3 core + 22 supporting (0 extra)
        chars = [{"name": f"Core{i}", "tier": "core"} for i in range(3)] + [
            {"name": f"Sup{i}", "tier": "supporting"} for i in range(22)
        ]
        result = ExtractionService._enforce_tier_distribution(chars)
        extra_count = sum(1 for c in result if c["tier"] == "extra")
        assert extra_count >= 15  # should target ~60% of 25 = 15
        # Core should be untouched
        assert sum(1 for c in result if c["tier"] == "core") == 3

    def test_preserves_core_tier(self):
        """core 角色不会被降级。"""
        from src.services.extraction_service import ExtractionService

        chars = [{"name": "Hero", "tier": "core"}] + [
            {"name": f"Sup{i}", "tier": "supporting"} for i in range(30)
        ]
        result = ExtractionService._enforce_tier_distribution(chars)
        assert result[0]["tier"] == "core"  # Hero untouched


class TestExtractionService:
    @pytest.fixture
    def mock_llm(self):
        """创建 mock LLM provider。"""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_llm):
        """创建注入 mock LLM 的 ExtractionService。"""
        from src.services.extraction_service import ExtractionService

        return ExtractionService(llm=mock_llm)

    async def test_extract_returns_elements_and_char_candidates(self, service, mock_llm):
        """extract() 应返回 (elements, char_candidates) 元组。"""
        expected_elements = [
            Element(
                id="elem_1",
                category="势力阵营",
                name="ETO",
                brief="地球三体组织",
                detail="协助三体人入侵地球的秘密组织...",
            ),
        ]
        expected_chars = [{"name": "叶文洁", "tier": "core"}]
        with patch.object(
            service,
            "_extract_pipeline",
            new_callable=AsyncMock,
            return_value=(expected_elements, expected_chars),
        ):
            result = await service.extract(
                title="三体",
                author="刘慈欣",
                description="硬科幻经典",
            )

        assert isinstance(result, tuple)
        elements, char_candidates = result
        assert len(elements) == 1
        assert all(isinstance(e, Element) for e in elements)
        assert elements[0].name == "ETO"
        assert len(char_candidates) == 1
        assert char_candidates[0]["name"] == "叶文洁"

    async def test_extract_assigns_element_ids(self, service, mock_llm):
        """extract() 应为每个元素分配唯一 id。"""
        expected_elements = [
            Element(id="elem_aaa", category="场所", name="A", brief="...", detail="..."),
            Element(id="elem_bbb", category="势力", name="B", brief="...", detail="..."),
        ]
        with patch.object(
            service,
            "_extract_pipeline",
            new_callable=AsyncMock,
            return_value=(expected_elements, []),
        ):
            elements, _ = await service.extract(title="测试", author=None, description=None)

        assert elements[0].id != elements[1].id
        assert elements[0].id.startswith("elem_")
        assert elements[1].id.startswith("elem_")

    async def test_extract_handles_empty_llm_response(self, service, mock_llm):
        """流水线返回空时应返回空列表而非报错。"""
        with patch.object(
            service, "_extract_pipeline", new_callable=AsyncMock, return_value=([], [])
        ):
            elements, chars = await service.extract(title="测试", author=None, description=None)
        assert elements == []
        assert chars == []

    async def test_extract_filters_invalid_items(self, service, mock_llm):
        """流水线已过滤无效条目，extract() 直接透传结果。"""
        expected_elements = [
            Element(id="elem_1", category="场所", name="有效元素", brief="...", detail="..."),
        ]
        with patch.object(
            service,
            "_extract_pipeline",
            new_callable=AsyncMock,
            return_value=(expected_elements, []),
        ):
            elements, _ = await service.extract(title="测试", author=None, description=None)
        assert len(elements) == 1
        assert elements[0].name == "有效元素"

    async def test_extract_deduplicates_similar_names(self, service, mock_llm):
        """流水线已通过 NER 去重，extract() 直接透传结果。"""
        expected_elements = [
            Element(
                id="elem_1",
                category="势力阵营",
                name="地球防卫组织",
                brief="更长的简介",
                detail="更长的详细描述",
            ),
        ]
        with patch.object(
            service,
            "_extract_pipeline",
            new_callable=AsyncMock,
            return_value=(expected_elements, []),
        ):
            elements, _ = await service.extract(title="测试", author=None, description=None)

        assert len(elements) == 1
        assert elements[0].detail == "更长的详细描述"


class TestExtractReturnsTuple:
    """extract() 应返回 tuple[list[Element], list[dict]]，第二个元素是角色候选。"""

    @pytest.fixture
    def mock_llm(self):
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_llm):
        from src.services.extraction_service import ExtractionService

        return ExtractionService(llm=mock_llm)

    async def test_extract_returns_elements_and_char_candidates(self, service, mock_llm):
        """extract() 应返回 (elements, char_candidates) 元组。"""
        non_char_elements = [
            Element(id="elem_1", category="场所", name="学校", brief="b", detail="d"),
            Element(id="elem_2", category="势力", name="组织", brief="b", detail="d"),
        ]
        char_candidates = [
            {"name": "主角A", "tier": "core"},
            {"name": "配角B", "tier": "supporting"},
        ]

        with patch.object(
            service,
            "_extract_pipeline",
            new_callable=AsyncMock,
            return_value=(non_char_elements, char_candidates),
        ):
            result = await service.extract(
                title="测试",
                author="作者",
                description="描述",
                wiki_characters="角色资料" * 20,
                scale="standard",
            )

        assert isinstance(result, tuple)
        assert len(result) == 2
        elements, chars = result
        assert isinstance(elements, list)
        assert isinstance(chars, list)
        assert all(isinstance(e, Element) for e in elements)
        assert all(isinstance(c, dict) for c in chars)

    async def test_elements_not_contain_characters(self, service, mock_llm):
        """elements 中不应包含 category="characters" 的元素。"""
        non_char_elements = [
            Element(id="elem_1", category="场所", name="学校", brief="b", detail="d"),
        ]
        char_candidates = [{"name": "角色A", "tier": "core"}]

        with patch.object(
            service,
            "_extract_pipeline",
            new_callable=AsyncMock,
            return_value=(non_char_elements, char_candidates),
        ):
            elements, _ = await service.extract(
                title="T",
                author=None,
                description=None,
                scale="standard",
            )

        for e in elements:
            assert e.category != "characters", f"元素 {e.name} 不应有 characters 分类"

    async def test_char_candidates_contain_name_and_tier(self, service, mock_llm):
        """char_candidates 每项应包含 name 和 tier 字段。"""
        char_candidates = [
            {"name": "主角A", "tier": "core"},
            {"name": "配角B", "tier": "supporting"},
            {"name": "路人C", "tier": "extra"},
        ]

        with patch.object(
            service,
            "_extract_pipeline",
            new_callable=AsyncMock,
            return_value=([], char_candidates),
        ):
            _, chars = await service.extract(
                title="T",
                author=None,
                description=None,
                scale="standard",
            )

        for c in chars:
            assert "name" in c, f"角色候选缺少 name 字段: {c}"
            assert "tier" in c, f"角色候选缺少 tier 字段: {c}"
            assert c["tier"] in ("core", "supporting", "extra")


class TestFixedTabsSevenItems:
    """FIXED_TABS 应只有 7 项（不含 characters）。"""

    def test_fixed_tabs_has_seven_items(self):
        from src.services.extraction_service import FIXED_TABS

        assert len(FIXED_TABS) == 7

    def test_fixed_tabs_not_contain_characters(self):
        from src.services.extraction_service import FIXED_TABS

        assert "characters" not in FIXED_TABS

    def test_fixed_tabs_contains_expected_categories(self):
        from src.services.extraction_service import FIXED_TABS

        expected = {"场所", "势力", "规则", "事件", "物品", "文化", "其他"}
        assert set(FIXED_TABS) == expected


class TestExtractWikiSections:
    """_extract_wiki_sections() - 从 wiki 角色文本中按名字截取段落。

    返回 dict[str, tuple[str, str]]：{llm_name: (section_text, wiki_canonical_name)}
    """

    def test_basic_extraction(self):
        from src.services.generation_service import _extract_wiki_sections

        wiki = "角色A（别名）\n:   介绍A\n\n角色B（别名）\n:   介绍B"
        result = _extract_wiki_sections(wiki, ["角色A", "角色B"])
        assert "角色A" in result
        assert "角色B" in result
        assert "介绍A" in result["角色A"][0]
        assert "介绍B" in result["角色B"][0]

    def test_not_found_returns_missing(self):
        from src.services.generation_service import _extract_wiki_sections

        wiki = "角色A（别名）\n:   介绍A"
        result = _extract_wiki_sections(wiki, ["角色A", "不存在"])
        assert "角色A" in result
        assert "不存在" not in result

    def test_empty_wiki_returns_empty(self):
        from src.services.generation_service import _extract_wiki_sections

        result = _extract_wiki_sections("", ["角色A"])
        assert result == {}

    def test_empty_names_returns_empty(self):
        from src.services.generation_service import _extract_wiki_sections

        result = _extract_wiki_sections("some wiki text", [])
        assert result == {}

    def test_substring_match_on_first_line(self):
        from src.services.generation_service import _extract_wiki_sections

        # "薩布羅" 是 "斯伯諾克・薩布羅" 的子串，应匹配
        wiki = "斯伯諾克・薩布羅（别名）\n:   介绍\n\n其他角色\n:   其他介绍"
        result = _extract_wiki_sections(wiki, ["薩布羅"])
        assert "薩布羅" in result
        assert "斯伯諾克・薩布羅" in result["薩布羅"][0]

    def test_wiki_canonical_name_extraction(self):
        from src.services.generation_service import _extract_wiki_sections

        # 验证 tuple[1] 是 wiki 原文名（去掉括号）
        wiki = "奧村正宗（奥村 正宗（おくむら まさむね），聲：榎木淳彌）\n角色描述"
        result = _extract_wiki_sections(wiki, ["奧村正宗"])
        assert result["奧村正宗"][1] == "奧村正宗"

    def test_canonical_name_fallback_to_input_name(self):
        from src.services.generation_service import _extract_wiki_sections

        # 首行无括号时，canonical name 回退到输入的 name
        wiki = "Naruto\n主角描述"
        result = _extract_wiki_sections(wiki, ["Naruto"])
        assert result["Naruto"][1] == "Naruto"


# ── WikiSegment 分段提取测试 ────────────────────────────────────────────────────


class TestWikiSegmentDataclass:
    """WikiSegment dataclass 字段验证。"""

    def test_has_required_fields(self):
        from src.services.extraction_service import WikiSegment

        seg = WikiSegment(text="内容", source="主链/主要角色", index=0)
        assert seg.text == "内容"
        assert seg.source == "主链/主要角色"
        assert seg.index == 0


class TestSplitCharactersSegments:
    """_split_characters_segments() - 按 ---SOURCE_BOUNDARY--- 分隔符分割 wiki_characters。"""

    @pytest.fixture
    def service(self):
        from src.services.extraction_service import ExtractionService

        return ExtractionService(llm=AsyncMock())

    def test_split_with_source_boundary(self, service):
        """有 ---SOURCE_BOUNDARY--- 分隔符的文本 → 按来源分段，source 含 URL 短标签。"""
        text = (
            "主链角色介绍" * 20
            + "\n\n---SOURCE_BOUNDARY: https://example.com/wiki/子链人物---\n\n"
            + "子链角色介绍" * 20
        )
        segments = service._split_characters_segments(text)

        assert len(segments) == 2
        assert segments[0].source == "主链"
        assert "子链人物" in segments[1].source
        assert segments[0].index == 0
        assert segments[1].index == 1

    def test_split_without_boundary_long_text(self, service):
        """无分隔符但长度 >= 100 → 1 个 segment，source="主链"。"""
        text = "角色A是主角" * 30  # > 100 chars
        segments = service._split_characters_segments(text)

        assert len(segments) == 1
        assert segments[0].source == "主链"
        assert segments[0].index == 0
        assert segments[0].text == text

    def test_split_without_boundary_short_text(self, service):
        """无分隔符且长度 < 100 → 空列表。"""
        text = "短文本"
        segments = service._split_characters_segments(text)

        assert segments == []

    def test_split_short_section_filtered(self, service):
        """分隔符后 chunk 长度 < 100 → 该 segment 被过滤。"""
        text = (
            "长内容介绍" * 25
            + "\n\n---SOURCE_BOUNDARY: https://example.com/wiki/短页面---\n\n"
            + "短内容"
        )
        segments = service._split_characters_segments(text)

        # 只有主链被保留，子链太短被过滤
        assert len(segments) == 1
        assert segments[0].source == "主链"

    def test_split_custom_source_label(self, service):
        """传入 source_label="子链" → 主链 segment source 使用 "子链"。"""
        text = "角色详细介绍内容" * 15
        segments = service._split_characters_segments(text, source_label="子链")

        assert len(segments) == 1
        assert segments[0].source == "子链"

    def test_split_preserves_order(self, service):
        """segments 按文档顺序排列（主链 → 子链 → 子链的子链）。"""
        text = (
            "主链角色详细介绍" * 15
            + "\n\n---SOURCE_BOUNDARY: https://example.com/wiki/sub1---\n\n"
            + "子链1角色详细介绍" * 15
            + "\n\n---SOURCE_BOUNDARY: https://example.com/wiki/sub2---\n\n"
            + "子链2角色详细介绍" * 15
        )
        segments = service._split_characters_segments(text)

        assert len(segments) == 3
        assert segments[0].index < segments[1].index < segments[2].index
        assert segments[0].source == "主链"
        assert "sub1" in segments[1].source
        assert "sub2" in segments[2].source


class TestMergeSegmentResults:
    """_merge_segment_results() - 合并多片段结果。"""

    def test_merge_deduplicates_by_name(self):
        from src.services.extraction_service import ExtractionService

        seg1 = [{"name": "角色A", "tier": "core"}, {"name": "角色B", "tier": "supporting"}]
        seg2 = [{"name": "角色A", "tier": "extra"}, {"name": "角色C", "tier": "core"}]

        result = ExtractionService._merge_segment_results([seg1, seg2])

        names = [c["name"] for c in result]
        assert names == ["角色A", "角色B", "角色C"]

    def test_merge_preserves_first_tier(self):
        """同名角色在多个片段中出现时，保留第一次出现的 tier。"""
        from src.services.extraction_service import ExtractionService

        seg1 = [{"name": "角色A", "tier": "core"}]
        seg2 = [{"name": "角色A", "tier": "extra"}]

        result = ExtractionService._merge_segment_results([seg1, seg2])

        assert len(result) == 1
        assert result[0]["tier"] == "core"

    def test_merge_preserves_order(self):
        """结果顺序与输入一致（先出现的片段优先）。"""
        from src.services.extraction_service import ExtractionService

        seg1 = [{"name": "B", "tier": "core"}, {"name": "A", "tier": "supporting"}]
        seg2 = [{"name": "C", "tier": "extra"}]

        result = ExtractionService._merge_segment_results([seg1, seg2])

        names = [c["name"] for c in result]
        assert names == ["B", "A", "C"]

    def test_merge_empty_segments(self):
        """空输入 → 空输出。"""
        from src.services.extraction_service import ExtractionService

        result = ExtractionService._merge_segment_results([])
        assert result == []

    def test_merge_single_segment(self):
        """单个片段 → 原样返回。"""
        from src.services.extraction_service import ExtractionService

        seg = [{"name": "角色A", "tier": "core"}, {"name": "角色B", "tier": "extra"}]
        result = ExtractionService._merge_segment_results([seg])

        assert len(result) == 2
        assert result[0]["name"] == "角色A"
        assert result[1]["name"] == "角色B"


class TestExtractCharactersWithSegments:
    """extract_characters() with segments 参数。"""

    @pytest.fixture
    def mock_llm(self):
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_llm):
        from src.services.extraction_service import ExtractionService

        return ExtractionService(llm=mock_llm)

    async def test_extract_characters_with_segments_parallel(self, service):
        """传入 segments 列表 → _do_extract_characters 每个 segment 调用一次。"""
        from src.services.extraction_service import WikiSegment

        segments = [
            WikiSegment(text="角色A介绍" * 20, source="主链/主要角色", index=0),
            WikiSegment(text="角色B介绍" * 20, source="主链/配角", index=1),
        ]

        call_count = 0

        async def mock_do_extract(
            prompt, *, llm, valid_tiers, wiki_characters, attempt=1, max_tokens=4096
        ):
            nonlocal call_count
            call_count += 1
            return [{"name": f"角色{call_count}", "tier": "core"}]

        with patch.object(service, "_do_extract_characters", side_effect=mock_do_extract):
            result = await service.extract_characters(
                wiki_characters="角色资料内容" * 20,
                char_target=0,
                title="测试",
                segments=segments,
            )

        assert call_count == 2
        assert len(result) == 2

    async def test_extract_characters_with_segments_merges(self, service):
        """多个片段结果 → 合并去重。"""
        from src.services.extraction_service import WikiSegment

        segments = [
            WikiSegment(text="主要角色介绍" * 20, source="主链/主要角色", index=0),
            WikiSegment(text="配角介绍内容" * 20, source="主链/配角", index=1),
        ]

        async def mock_do_extract(
            prompt, *, llm, valid_tiers, wiki_characters, attempt=1, max_tokens=4096
        ):
            if "主要角色" in (wiki_characters or ""):
                return [
                    {"name": "角色A", "tier": "core"},
                    {"name": "角色B", "tier": "supporting"},
                ]
            return [
                {"name": "角色A", "tier": "extra"},  # 重复
                {"name": "角色C", "tier": "core"},
            ]

        with patch.object(service, "_do_extract_characters", side_effect=mock_do_extract):
            result = await service.extract_characters(
                wiki_characters="角色资料内容" * 20,
                char_target=0,
                title="测试",
                segments=segments,
            )

        names = [c["name"] for c in result]
        assert names == ["角色A", "角色B", "角色C"]
        # 角色A 保留第一次的 tier
        assert result[0]["tier"] == "core"

    async def test_extract_characters_segments_none_falls_back(self, service, mock_llm):
        """segments=None → 走原有单次调用逻辑。"""
        mock_llm.complete_json.return_value = [
            {"name": "角色A", "tier": "core"},
        ]

        result = await service.extract_characters(
            wiki_characters="角色资料内容" * 20,
            char_target=5,
            title="测试",
            segments=None,
        )

        assert len(result) == 1
        assert result[0]["name"] == "角色A"

    async def test_extract_characters_segments_single_skips_parallel(self, service, mock_llm):
        """只有 1 个 segment → 不走并行，走原有单次调用。"""
        from src.services.extraction_service import WikiSegment

        segments = [WikiSegment(text="角色资料内容" * 20, source="主链", index=0)]
        mock_llm.complete_json.return_value = [
            {"name": "角色A", "tier": "core"},
        ]

        result = await service.extract_characters(
            wiki_characters="角色资料内容" * 20,
            char_target=5,
            title="测试",
            segments=segments,
        )

        assert len(result) == 1
        assert result[0]["name"] == "角色A"

    async def test_extract_characters_segments_failure_handled(self, service):
        """一个 segment 抛异常 → 其他 segment 正常返回，失败的被跳过。"""
        from src.services.extraction_service import WikiSegment

        segments = [
            WikiSegment(text="角色A介绍" * 20, source="主链/主要角色", index=0),
            WikiSegment(text="角色B介绍" * 20, source="主链/配角", index=1),
        ]

        call_count = 0

        async def mock_do_extract(
            prompt, *, llm, valid_tiers, wiki_characters, attempt=1, max_tokens=4096
        ):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("LLM 调用失败")
            return [{"name": "角色B", "tier": "core"}]

        with patch.object(service, "_do_extract_characters", side_effect=mock_do_extract):
            result = await service.extract_characters(
                wiki_characters="角色资料内容" * 20,
                char_target=0,
                title="测试",
                segments=segments,
            )

        # 第一个 segment 失败，第二个成功
        assert len(result) == 1
        assert result[0]["name"] == "角色B"


class TestExtractSingleSegmentNoPrematureEnforcement:
    """_extract_single_segment() 不应在合并前对单片段强制执行层级分布。"""

    @pytest.fixture
    def service(self):
        from src.services.extraction_service import ExtractionService

        return ExtractionService(llm=AsyncMock())

    async def test_no_per_segment_tier_enforcement(self, service):
        """单片段提取结果不应被 _enforce_tier_distribution 修改。
        层级分布应仅在合并后的全局结果上执行。
        """
        from src.services.extraction_service import WikiSegment

        # 构造一个有 25 个角色的片段：3 core + 22 supporting + 0 extra
        # 如果 per-segment enforcement 运行，supporting 会被降级为 extra
        char_list = [{"name": "Core0", "tier": "core"}]
        for i in range(22):
            char_list.append({"name": f"Sup{i}", "tier": "supporting"})

        async def mock_do_extract(
            prompt, *, llm, valid_tiers, wiki_characters, attempt=1, max_tokens=4096
        ):
            return list(char_list)  # 返回副本

        segment = WikiSegment(text="x" * 200, source="test", index=0)
        with patch.object(service, "_do_extract_characters", side_effect=mock_do_extract):
            result = await service._extract_single_segment(
                segment,
                char_target=0,
                title="测试",
                llm=AsyncMock(),
                valid_tiers={"core", "supporting", "extra"},
                segment_index=0,
                segment_total=1,
            )

        # 所有角色的 tier 应保持原样，不被 per-segment enforcement 修改
        assert len(result) == 23
        core_count = sum(1 for c in result if c["tier"] == "core")
        supporting_count = sum(1 for c in result if c["tier"] == "supporting")
        extra_count = sum(1 for c in result if c["tier"] == "extra")
        assert core_count == 1
        assert supporting_count == 22
        assert extra_count == 0
