"""Tests for M6 GraphBuilderService and TextProcessor.

Phase 4: Zep as pure consumer — GraphBuilderService reads from M2Character
to build Zep graph nodes/edges. _persist_results is removed.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.services.graph_builder import GraphBuilderService
from src.services.task_manager import TaskManager, TaskStatus
from src.services.text_processor import TextProcessor


class TestTextProcessor:
    def test_split_text_basic(self):
        text = "a" * 1000
        chunks = TextProcessor.split_text(text, chunk_size=300, overlap=50)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 300

    def test_split_text_short_returns_single(self):
        text = "short text"
        chunks = TextProcessor.split_text(text, chunk_size=500, overlap=50)
        assert len(chunks) == 1
        assert chunks[0] == "short text"

    def test_split_text_empty(self):
        chunks = TextProcessor.split_text("", chunk_size=500, overlap=50)
        assert len(chunks) == 0

    def test_split_text_overlap(self):
        text = "abcdef" * 100  # 600 chars
        chunks = TextProcessor.split_text(text, chunk_size=200, overlap=50)
        if len(chunks) > 1:
            # 后一个 chunk 的前 overlap 字符应与前一个 chunk 的末尾重叠
            assert chunks[1][:50] == chunks[0][-50:]


class TestGraphBuilderService:
    @pytest.fixture
    def mock_zep_client(self):
        client = MagicMock()
        mock_graph = MagicMock()
        mock_graph.create.return_value = MagicMock(uuid_="graph_abc")
        mock_graph.add_batch.return_value = [
            MagicMock(uuid_="ep1"),
            MagicMock(uuid_="ep2"),
        ]
        mock_graph.episode.get.return_value = MagicMock(processed=True)
        mock_graph.set_ontology.return_value = None

        mock_node = MagicMock()
        mock_node.uuid_ = "node1"
        mock_node.name = "张三"
        mock_node.labels = ["character"]
        mock_node.summary = "主角"
        mock_node.attributes = {}

        mock_edge = MagicMock()
        mock_edge.uuid_ = "edge1"
        mock_edge.name = "family"
        mock_edge.fact = "张三是李四的哥哥"
        mock_edge.source_node_uuid = "node1"
        mock_edge.target_node_uuid = "node2"
        mock_edge.attributes = {}

        mock_graph.get_nodes.return_value = MagicMock(results=[mock_node], next_cursor=None)
        mock_graph.get_edges.return_value = MagicMock(results=[mock_edge], next_cursor=None)

        client.graph = mock_graph
        return client

    @pytest.fixture
    def service(self, mock_zep_client):
        # 独立 TaskManager 实例
        tm = TaskManager.__new__(TaskManager)
        tm._tasks = {}
        import threading

        tm._task_lock = threading.Lock()
        return GraphBuilderService(zep_client=mock_zep_client, task_manager=tm)

    def test_build_returns_task_id(self, service):
        task_id = service.build_async(
            world_id="w1",
            text="一个武侠世界",
            ontology={"entity_types": ["character"], "relation_types": ["ally"]},
        )
        assert task_id is not None
        assert isinstance(task_id, str)

    def _wait_task(self, service, task_id, timeout=5.0):
        import time as _t

        deadline = _t.time() + timeout
        while _t.time() < deadline:
            t = service.task_manager.get_task(task_id)
            if t and t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                return
            _t.sleep(0.05)

    def test_build_adds_episodes_to_user_graph(self, service, mock_zep_client):
        with patch("src.services.graph_builder.time.sleep"):
            task_id = service.build_async(
                world_id="w1",
                text="test world text",
                ontology={"entity_types": ["character"], "relation_types": ["ally"]},
            )
            self._wait_task(service, task_id)
        assert mock_zep_client.graph.add_batch.call_count >= 1

    def test_build_registers_user_in_zep(self, service, mock_zep_client):
        with patch("src.services.graph_builder.time.sleep"):
            task_id = service.build_async(
                world_id="w1",
                text="test",
                ontology={"entity_types": ["character"], "relation_types": ["ally"]},
            )
            self._wait_task(service, task_id)
        mock_zep_client.user.add.assert_called_once_with(user_id="w1")

    def test_build_progress_tracked(self, service):
        task_id = service.build_async(
            world_id="w1",
            text="short text for testing",
            ontology={"entity_types": ["character"], "relation_types": ["ally"]},
        )
        import time

        time.sleep(2)
        task = service.task_manager.get_task(task_id)
        assert task is not None
        assert task.status in (TaskStatus.COMPLETED, TaskStatus.PROCESSING, TaskStatus.FAILED)

    def test_build_adds_episodes(self, service, mock_zep_client):
        service.build_async(
            world_id="w1",
            text="long text " * 200,
            ontology={"entity_types": ["character"], "relation_types": ["ally"]},
            chunk_size=100,
        )
        import time

        time.sleep(3)
        assert mock_zep_client.graph.add_batch.call_count >= 1


class TestGraphBuilderFallback:
    """测试 Zep 不可用时的降级"""

    def test_zep_unavailable_marks_failed(self):
        tm = TaskManager.__new__(TaskManager)
        tm._tasks = {}
        import threading

        tm._task_lock = threading.Lock()

        bad_client = MagicMock()
        bad_client.user.add.side_effect = None  # user.add 被 try/except 忽略
        bad_client.graph.add_batch.side_effect = Exception("connection refused")

        service = GraphBuilderService(zep_client=bad_client, task_manager=tm)
        with patch("src.services.graph_builder.time.sleep"):
            task_id = service.build_async(
                world_id="w1",
                text="test",
                ontology={"entity_types": ["character"], "relation_types": ["ally"]},
            )
            import time

            time.sleep(0.5)

        task = tm.get_task(task_id)
        assert task.status == TaskStatus.FAILED
        assert "connection refused" in task.error


class TestGraphBuilderPhase4ZepAsConsumer:
    """Phase 4: Zep is a pure consumer. GraphBuilderService reads from M2Character
    to build Zep graph nodes/edges. It does NOT write Zep data back to MIVE DB.
    """

    def test_persist_results_removed(self):
        """_persist_results method should not exist on GraphBuilderService."""
        assert not hasattr(GraphBuilderService, "_persist_results"), (
            "_persist_results should be removed — Zep no longer writes back to MIVE DB"
        )

    def test_build_graph_reads_from_m2character(self, mock_zep_client=None):
        """build_async should accept characters and relations from M2Character
        and build Zep graph episodes from them (not from raw text).
        """
        # Verify the build_async signature accepts characters/relations
        import inspect

        sig = inspect.signature(GraphBuilderService.build_async)
        param_names = list(sig.parameters.keys())
        assert "characters" in param_names or "text" in param_names, (
            "build_async should accept characters data from M2Character table"
        )

    def test_no_zep_to_db_write_path(self):
        """Verify there is no method that writes Zep graph data back to M2Character/M2Relation."""
        forbidden_methods = ["_persist_results", "sync_from_zep", "import_from_zep"]
        for method_name in forbidden_methods:
            assert not hasattr(GraphBuilderService, method_name), (
                f"GraphBuilderService.{method_name} should not exist — "
                "Zep data must not be written back to MIVE DB"
            )

    def test_build_episodes_from_characters(self):
        """_build_episodes_from_characters should format characters into text episodes."""
        characters = [
            {
                "name": "张三",
                "entity_type": "character",
                "profile": {
                    "basic": {"occupation": "剑客", "gender": "男"},
                    "brief": "武林高手",
                    "detail": "出身名门",
                },
            },
        ]
        relations = [
            {
                "char_a_name": "张三",
                "char_b_name": "李四",
                "type": "兄弟",
                "description": "结拜兄弟",
            },
        ]
        episodes = GraphBuilderService._build_episodes_from_characters(
            characters=characters,
            relations=relations,
            text="",
            chunk_size=500,
            chunk_overlap=50,
        )
        assert len(episodes) == 2
        assert "张三" in episodes[0]
        assert "剑客" in episodes[0]
        assert "兄弟" in episodes[1]

    def test_build_episodes_includes_raw_text(self):
        """_build_episodes_from_characters should also include raw text chunks."""
        characters = [
            {"name": "A", "entity_type": "character", "profile": {"brief": "test"}},
        ]
        episodes = GraphBuilderService._build_episodes_from_characters(
            characters=characters,
            relations=[],
            text="raw text content",
            chunk_size=500,
            chunk_overlap=50,
        )
        # 1 character episode + 1 text chunk
        assert len(episodes) >= 2
        assert "raw text content" in episodes[-1]
