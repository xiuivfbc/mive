"""Tests for WorldService - world CRUD orchestration."""

import uuid
from unittest.mock import AsyncMock

from src.models.world import Element, WorldDoc, WorldMeta, WorldSource

_USER_ID = str(uuid.uuid4())


def _make_service(mock_repo=None, mock_extraction=None, mock_search=None):
    from src.services.world_service import WorldService

    if mock_repo is None:
        mock_repo = AsyncMock()
        mock_repo.save.return_value = str(uuid.uuid4())
    if mock_extraction is None:
        mock_extraction = AsyncMock()
        mock_extraction.extract.return_value = (
            [Element(id="e1", category="势力阵营", name="ETO", brief="...", detail="...")],
            [{"name": "角色A", "tier": "core"}],
        )
    if mock_search is None:
        mock_search = AsyncMock()
        mock_search.search.return_value = []

    mock_llm = AsyncMock()
    mock_llm.complete.return_value = "ok"

    return (
        WorldService(
            repo=mock_repo,
            extraction=mock_extraction,
            search=mock_search,
            llm=mock_llm,
        ),
        mock_repo,
        mock_extraction,
        mock_search,
        mock_llm,
    )


class TestWorldServiceCreate:
    async def test_create_world_returns_world_doc(self):
        """create_world 应返回 WorldDoc。"""
        svc, mock_repo, *_ = _make_service()
        mock_repo.save.return_value = str(uuid.uuid4())

        world = await svc.create_world(
            title="三体",
            author="刘慈欣",
            type="小说",
            description="硬科幻经典",
            urls=[],
            user_id=_USER_ID,
        )

        assert isinstance(world, WorldDoc)
        assert world.source.title == "三体"
        assert world.source.author == "刘慈欣"

    async def test_create_world_calls_extraction(self):
        """create_world 应调用 extraction_service.extract。"""
        svc, mock_repo, mock_extraction, *_ = _make_service()
        mock_repo.save.return_value = str(uuid.uuid4())

        await svc.create_world(
            title="三体",
            author="刘慈欣",
            type=None,
            description="硬科幻经典",
            urls=[],
            user_id=_USER_ID,
        )

        mock_extraction.extract.assert_called_once()

    async def test_create_world_saves_to_repo(self):
        """create_world 应调用 repo.save 存储。"""
        svc, mock_repo, *_ = _make_service()
        mock_repo.save.return_value = str(uuid.uuid4())

        await svc.create_world(
            title="三体",
            author=None,
            type=None,
            description=None,
            urls=[],
            user_id=_USER_ID,
        )

        mock_repo.save.assert_called_once()

    async def test_create_world_with_confirmed_wiki_skips_search(self):
        """传入 confirmed_wiki_url 时应直接使用，不再调 search.search。"""
        svc, mock_repo, mock_extraction, mock_search, _ = _make_service()
        mock_repo.save.return_value = str(uuid.uuid4())

        await svc.create_world(
            title="三体",
            author="刘慈欣",
            type=None,
            description=None,
            urls=[],
            user_id=_USER_ID,
            confirmed_wiki_url="https://zh.wikipedia.org/wiki/三体",
            confirmed_wiki_raw_content="三体小说正文内容...",
        )

        mock_extraction.extract.assert_called_once()


class TestWorldServiceGet:
    async def test_get_world_returns_doc(self):
        svc, mock_repo, *_ = _make_service()
        world_doc = WorldDoc(
            world_id="w-001",
            version="1.0",
            source=WorldSource(title="三体"),
            meta=WorldMeta(),
            elements=[],
        )
        mock_repo.get.return_value = world_doc

        result = await svc.get_world("w-001")

        assert result is not None
        assert result.world_id == "w-001"

    async def test_get_world_not_found(self):
        svc, mock_repo, *_ = _make_service()
        mock_repo.get.return_value = None

        result = await svc.get_world("nonexistent")

        assert result is None


class TestWorldServiceUpdateElement:
    async def test_update_element_found_returns_element(self):
        svc, mock_repo, *_ = _make_service()
        world_doc = WorldDoc(
            world_id="w-001",
            version="1.0",
            source=WorldSource(title="三体"),
            meta=WorldMeta(),
            elements=[
                Element(id="e1", category="势力阵营", name="ETO", brief="旧简介", detail="旧详情")
            ],
        )
        mock_repo.get.return_value = world_doc
        mock_repo.save.return_value = "w-001"

        result = await svc.update_element("w-001", "e1", brief="新简介", detail="新详情")

        assert result is not None
        assert result.brief == "新简介"

    async def test_update_element_world_not_found_returns_none(self):
        svc, mock_repo, *_ = _make_service()
        mock_repo.get.return_value = None

        result = await svc.update_element("w-001", "e1", brief="x", detail="y")

        assert result is None

    async def test_update_element_elem_not_found_returns_none(self):
        svc, mock_repo, *_ = _make_service()
        world_doc = WorldDoc(
            world_id="w-001",
            version="1.0",
            source=WorldSource(title="三体"),
            meta=WorldMeta(),
            elements=[Element(id="e1", category="势力阵营", name="ETO", brief="x", detail="y")],
        )
        mock_repo.get.return_value = world_doc

        result = await svc.update_element("w-001", "bad-id", brief="x", detail="y")

        assert result is None


class TestJudgeFastPath:
    async def test_popular_work_standard_returns_true(self):
        """知名作品+standard 档位 → can_identify=True, can_generate=True"""
        svc, _, _, _, mock_llm = _make_service()
        _chars = [f"角色{i}" for i in range(1, 11)]
        mock_llm.complete_json.side_effect = [
            # 阶段一：识别
            {
                "can_identify": True,
                "can_generate": True,
                "work_name": "火影忍者",
                "reason": "广为人知的日本漫画",
                "characters": _chars,
            },
            # 阶段二：验证
            {
                "verdict": "accept",
                "details": [{"name": c, "belongs": True} for c in _chars],
            },
        ]

        result = await svc.judge_fast_path(
            title="火影忍者",
            author="岸本齐史",
            description="少年忍者的成长故事",
            scale="standard",
        )

        assert result["can_identify"] is True
        assert result["can_generate"] is True
        assert result["work_name"] == "火影忍者"
        assert mock_llm.complete_json.call_count == 2

    async def test_vague_input_returns_false(self):
        """模糊输入 → can_identify=False"""
        svc, _, _, _, mock_llm = _make_service()
        mock_llm.complete_json.return_value = {
            "can_identify": False,
            "can_generate": False,
            "work_name": "",
            "reason": "信息不足以唯一确定作品",
        }

        result = await svc.judge_fast_path(
            title="我的故事",
            author=None,
            description=None,
            scale="standard",
        )

        assert result["can_identify"] is False
        assert result["can_generate"] is False

    async def test_high_scale_returns_false(self):
        """detailed 档位 → 直接返回 False，不调用 LLM"""
        svc, _, _, _, mock_llm = _make_service()

        result = await svc.judge_fast_path(
            title="火影忍者",
            author="岸本齐史",
            description=None,
            scale="detailed",
        )

        assert result["can_identify"] is False
        mock_llm.complete_json.assert_not_called()

    async def test_deep_scale_returns_false(self):
        """deep 档位 → 直接返回 False"""
        svc, _, _, _, mock_llm = _make_service()

        result = await svc.judge_fast_path(
            title="三体",
            author="刘慈欣",
            description=None,
            scale="deep",
        )

        assert result["can_identify"] is False
        mock_llm.complete_json.assert_not_called()

    async def test_llm_returns_non_dict(self):
        """LLM 返回非 dict → 降级为 False"""
        svc, _, _, _, mock_llm = _make_service()
        mock_llm.complete_json.return_value = ["not", "a", "dict"]

        result = await svc.judge_fast_path(
            title="测试",
            author=None,
            description=None,
            scale="standard",
        )

        assert result["can_identify"] is False
        assert result["can_generate"] is False

    async def test_llm_raises_exception(self):
        """LLM 抛异常 → 降级为 False（不应阻塞正常流程）"""
        svc, _, _, _, mock_llm = _make_service()
        mock_llm.complete_json.side_effect = Exception("LLM timeout")

        result = await svc.judge_fast_path(
            title="测试",
            author=None,
            description=None,
            scale="standard",
        )

        assert result["can_identify"] is False


class TestBuildWorldContentFast:
    async def test_generates_elements_and_saves(self):
        """快速路径：调用 extraction.extract 并保存 WorldDoc。"""
        svc, mock_repo, mock_extraction, _, _ = _make_service()
        mock_extraction.extract.return_value = (
            [
                Element(id="e1", category="势力阵营", name="木叶村", brief="忍者村", detail="..."),
            ],
            [{"name": "鸣人", "tier": "core"}],
        )

        world = await svc.build_world_content_fast(
            world_id="w-fast-1",
            title="火影忍者",
            author="岸本齐史",
            type="漫画",
            description="少年忍者的成长故事",
            urls=[],
            user_id=_USER_ID,
            scale="standard",
        )

        assert isinstance(world, WorldDoc)
        assert world.world_id == "w-fast-1"
        assert world.source.title == "火影忍者"
        assert world.source.wiki_text is None  # 快速路径无 wiki
        assert len(world.elements) == 1
        mock_extraction.extract.assert_called_once()
        mock_repo.save.assert_called_once()

    async def test_uses_description_as_plot_summary(self):
        """有 description 时直接用作 plot_summary，不调用 LLM 生成。"""
        svc, mock_repo, mock_extraction, _, mock_llm = _make_service()
        mock_extraction.extract.return_value = (
            [Element(id="e1", category="规则", name="黑暗森林法则", brief="法则", detail="...")],
            [{"name": "罗辑", "tier": "core"}],
        )

        world = await svc.build_world_content_fast(
            world_id="w-fast-2",
            title="三体",
            author="刘慈欣",
            type=None,
            description="硬科幻，讲述三体文明与地球的接触",
            urls=[],
            user_id=_USER_ID,
            scale="standard",
        )

        assert world.source.plot_summary == "硬科幻，讲述三体文明与地球的接触"
        # 不应调用 LLM 的 complete（只有 extraction 调了 complete_json）
        mock_llm.complete.assert_not_called()

    async def test_no_description_falls_back_to_none(self):
        """无 description + 无上下文时 plot_summary 为 None（不硬编）。"""
        svc, mock_repo, mock_extraction, _, _ = _make_service()
        mock_extraction.extract.return_value = (
            [Element(id="e1", category="势力", name="唐门", brief="宗门", detail="...")],
            [{"name": "唐三", "tier": "core"}],
        )

        world = await svc.build_world_content_fast(
            world_id="w-fast-3",
            title="斗罗大陆",
            author="唐家三少",
            type=None,
            description=None,  # 无 description
            urls=[],
            user_id=_USER_ID,
            scale="standard",
        )

        # 并行执行：_do_plot 拿不到 _do_extract 的元素，无上下文时返回 None
        assert world.source.plot_summary is None

    async def test_fetches_reference_urls(self):
        """有参考网址时仍然抓取并通过 ref_content 传入 extract。"""
        svc, mock_repo, mock_extraction, _, _ = _make_service()
        mock_extraction.extract.return_value = (
            [Element(id="e1", category="势力", name="林家", brief="家族", detail="...")],
            [{"name": "林动", "tier": "core"}],
        )

        world = await svc.build_world_content_fast(
            world_id="w-fast-4",
            title="武动乾坤",
            author="天蚕土豆",
            type=None,
            description="修炼题材小说",
            urls=["https://example.com/reference"],
            user_id=_USER_ID,
            scale="standard",
        )

        # 有 urls 时会尝试抓取，ref_content 通过 extract 传入流水线
        assert isinstance(world, WorldDoc)
        mock_extraction.extract.assert_called_once()

    async def test_empty_extraction_still_saves(self):
        """extraction 返回空列表时仍保存世界（不报错）。"""
        svc, mock_repo, mock_extraction, _, _ = _make_service()
        mock_extraction.extract.return_value = ([], [])

        world = await svc.build_world_content_fast(
            world_id="w-fast-5",
            title="未知作品",
            author=None,
            type=None,
            description="一些描述",
            urls=[],
            user_id=_USER_ID,
            scale="standard",
        )

        assert isinstance(world, WorldDoc)
        assert len(world.elements) == 0
        mock_repo.save.assert_called_once()


class TestPopulateEventIndex:
    """Tests for WorldService._populate_event_index."""

    async def test_populates_event_elements(self):
        """事件元素应写入事件索引。"""
        svc, mock_repo, *_ = _make_service()
        mock_session = AsyncMock()
        mock_repo.session = mock_session

        w_id = str(uuid.uuid4())
        elements = [
            Element(
                id="e1",
                category="事件",
                name="王城之变",
                brief="叛军攻入王城",
                detail="详细描述",
            ),
            Element(
                id="e2",
                category="事件",
                name="黑森林发现",
                brief="发现古代遗迹",
                detail="详细描述",
            ),
            Element(
                id="e3",
                category="势力",
                name="ETO",
                brief="地球三体组织",
                detail="详细描述",
            ),
        ]

        from unittest.mock import patch

        with patch("src.db.repositories.event_index_repo.EventIndexRepository") as mock_repo_cls:
            mock_event_repo = AsyncMock()
            mock_repo_cls.return_value = mock_event_repo

            count = await svc._populate_event_index(w_id, elements)

        assert count == 2
        assert mock_event_repo.add.call_count == 2

    async def test_skips_non_event_elements(self):
        """非事件元素不应写入索引。"""
        svc, mock_repo, *_ = _make_service()
        mock_session = AsyncMock()
        mock_repo.session = mock_session

        w_id = str(uuid.uuid4())
        elements = [
            Element(id="e1", category="势力", name="ETO", brief="组织", detail="..."),
            Element(id="e2", category="场所", name="王城", brief="城堡", detail="..."),
        ]

        from unittest.mock import patch

        with patch("src.db.repositories.event_index_repo.EventIndexRepository") as mock_repo_cls:
            mock_event_repo = AsyncMock()
            mock_repo_cls.return_value = mock_event_repo

            count = await svc._populate_event_index(w_id, elements)

        assert count == 0
        mock_event_repo.add.assert_not_called()

    async def test_empty_elements_returns_zero(self):
        """空元素列表应返回 0。"""
        svc, mock_repo, *_ = _make_service()
        mock_session = AsyncMock()
        mock_repo.session = mock_session

        count = await svc._populate_event_index(str(uuid.uuid4()), [])

        assert count == 0

    async def test_brief_truncated_to_200_chars(self):
        """超过 200 字的 brief 应被截断。"""
        svc, mock_repo, *_ = _make_service()
        mock_session = AsyncMock()
        mock_repo.session = mock_session

        w_id = str(uuid.uuid4())
        long_brief = "A" * 300
        elements = [
            Element(id="e1", category="事件", name="长事件", brief=long_brief, detail="..."),
        ]

        from unittest.mock import patch

        with patch("src.db.repositories.event_index_repo.EventIndexRepository") as mock_repo_cls:
            mock_event_repo = AsyncMock()
            mock_repo_cls.return_value = mock_event_repo

            await svc._populate_event_index(w_id, elements)

        call_args = mock_event_repo.add.call_args
        assert len(call_args.kwargs["brief"]) == 200

    async def test_uses_detail_as_fallback_brief(self):
        """brief 为空时应使用 detail 作为 fallback。"""
        svc, mock_repo, *_ = _make_service()
        mock_session = AsyncMock()
        mock_repo.session = mock_session

        w_id = str(uuid.uuid4())
        elements = [
            Element(id="e1", category="事件", name="事件A", brief="", detail="事件详情描述"),
        ]

        from unittest.mock import patch

        with patch("src.db.repositories.event_index_repo.EventIndexRepository") as mock_repo_cls:
            mock_event_repo = AsyncMock()
            mock_repo_cls.return_value = mock_event_repo

            await svc._populate_event_index(w_id, elements)

        call_args = mock_event_repo.add.call_args
        assert call_args.kwargs["brief"] == "事件详情描述"

    async def test_dissemination_defaults_to_half(self):
        """dissemination 应默认为 0.5。"""
        svc, mock_repo, *_ = _make_service()
        mock_session = AsyncMock()
        mock_repo.session = mock_session

        w_id = str(uuid.uuid4())
        elements = [
            Element(id="e1", category="事件", name="事件A", brief="简介", detail="..."),
        ]

        from unittest.mock import patch

        with patch("src.db.repositories.event_index_repo.EventIndexRepository") as mock_repo_cls:
            mock_event_repo = AsyncMock()
            mock_repo_cls.return_value = mock_event_repo

            await svc._populate_event_index(w_id, elements)

        call_args = mock_event_repo.add.call_args
        assert call_args.kwargs["dissemination"] == 0.5
        assert call_args.kwargs["core_participants"] is None

    async def test_build_fast_calls_populate_event_index(self):
        """快速路径应在 repo.save 后调用 _populate_event_index。"""
        svc, mock_repo, mock_extraction, _, _ = _make_service()
        mock_extraction.extract.return_value = (
            [
                Element(id="e1", category="事件", name="大战", brief="决战", detail="..."),
                Element(id="e2", category="势力", name="阵营", brief="组织", detail="..."),
            ],
            [{"name": "角色A", "tier": "core"}],
        )

        svc._populate_event_index = AsyncMock(return_value=1)
        w_id = str(uuid.uuid4())

        await svc.build_world_content_fast(
            world_id=w_id,
            title="测试作品",
            author=None,
            type=None,
            description="描述",
            urls=[],
            user_id=_USER_ID,
            scale="standard",
        )

        svc._populate_event_index.assert_called_once_with(
            w_id,
            mock_extraction.extract.return_value[0],
        )

    async def test_build_normal_calls_populate_event_index(self):
        """正常路径应在 repo.save 后调用 _populate_event_index。"""
        svc, mock_repo, mock_extraction, _, _ = _make_service()
        mock_extraction.extract.return_value = (
            [
                Element(id="e1", category="事件", name="大战", brief="决战", detail="..."),
            ],
            [{"name": "角色A", "tier": "core"}],
        )

        svc._populate_event_index = AsyncMock(return_value=1)
        w_id = str(uuid.uuid4())

        await svc.build_world_content(
            world_id=w_id,
            title="测试作品",
            author=None,
            type=None,
            description="描述",
            urls=[],
            user_id=_USER_ID,
            scale="standard",
        )

        svc._populate_event_index.assert_called_once()

    async def test_populate_failure_does_not_block_world_creation(self):
        """事件索引填充失败不应阻塞世界创建。"""
        svc, mock_repo, mock_extraction, _, _ = _make_service()
        mock_extraction.extract.return_value = (
            [
                Element(id="e1", category="事件", name="大战", brief="决战", detail="..."),
            ],
            [{"name": "角色A", "tier": "core"}],
        )

        svc._populate_event_index = AsyncMock(side_effect=Exception("DB error"))

        # 不应抛异常
        world = await svc.build_world_content_fast(
            world_id=str(uuid.uuid4()),
            title="测试作品",
            author=None,
            type=None,
            description="描述",
            urls=[],
            user_id=_USER_ID,
            scale="standard",
        )

        assert isinstance(world, WorldDoc)
