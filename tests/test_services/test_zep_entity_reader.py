"""Tests for M6 ZepEntityReader.

Phase 4: ZepEntityReader is read-only. It reads from Zep for display purposes
but never writes data back to M2Character.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.services.zep_entity_reader import ZepEntityReader


@pytest.fixture
def mock_zep_client():
    return MagicMock()


@pytest.fixture
def reader(mock_zep_client):
    return ZepEntityReader(zep_client=mock_zep_client)


def _make_node(uuid_, name, labels, summary=""):
    n = MagicMock()
    n.uuid_ = uuid_
    n.name = name
    n.labels = labels
    n.summary = summary
    n.attributes = {}
    return n


def _make_edge(uuid_, name, fact, src, tgt):
    e = MagicMock()
    e.uuid_ = uuid_
    e.name = name
    e.fact = fact
    e.source_node_uuid = src
    e.target_node_uuid = tgt
    e.attributes = {}
    return e


def _setup(mock_zep_client, nodes, edges=None):
    """配置 SDK 3.22+ 风格 mock：get_by_user_id 直接返回列表。"""
    mock_zep_client.graph.node.get_by_user_id.return_value = nodes
    mock_zep_client.graph.edge.get_by_user_id.return_value = edges or []


class TestZepEntityReader:
    def test_filter_excludes_generic_entity_nodes(self, reader, mock_zep_client):
        _setup(
            mock_zep_client,
            [
                _make_node("n1", "张三", ["Entity", "character"]),
                _make_node("n2", "generic", ["Entity"]),
                _make_node("n3", "also_generic", ["Node"]),
            ],
        )

        result = reader.read_entities("graph1")
        names = [e["name"] for e in result]
        assert "张三" in names
        assert "generic" not in names
        assert "also_generic" not in names

    def test_filter_by_entity_type(self, reader, mock_zep_client):
        _setup(
            mock_zep_client,
            [
                _make_node("n1", "张三", ["character"]),
                _make_node("n2", "少林寺", ["organization"]),
                _make_node("n3", "华山", ["location"]),
            ],
        )

        result = reader.read_entities("graph1", entity_types=["character"])
        assert len(result) == 1
        assert result[0]["name"] == "张三"

    def test_enrich_with_edges(self, reader, mock_zep_client):
        _setup(
            mock_zep_client,
            nodes=[
                _make_node("n1", "张三", ["character"]),
                _make_node("n2", "李四", ["character"]),
            ],
            edges=[
                _make_edge("e1", "family", "张三是李四的哥哥", "n1", "n2"),
            ],
        )

        result = reader.read_entities("graph1", enrich_with_edges=True)
        zhang = next(e for e in result if e["name"] == "张三")
        assert len(zhang["related_edges"]) == 1
        assert zhang["related_edges"][0]["edge_name"] == "family"

    def test_map_to_characters(self, reader, mock_zep_client):
        _setup(
            mock_zep_client,
            [
                _make_node("n1", "张三", ["character"], "主角"),
                _make_node("n2", "少林寺", ["organization"], "武林大派"),
            ],
        )

        chars = reader.read_as_characters("graph1")
        assert len(chars) == 2
        assert chars[0]["name"] == "张三"
        assert chars[0]["entity_type"] == "character"
        assert chars[0]["graph_node_uuid"] == "n1"
        assert chars[1]["entity_type"] == "organization"

    def test_map_to_relations(self, reader, mock_zep_client):
        _setup(
            mock_zep_client,
            nodes=[
                _make_node("n1", "张三", ["character"]),
                _make_node("n2", "李四", ["character"]),
            ],
            edges=[
                _make_edge("e1", "family", "张三是李四的哥哥", "n1", "n2"),
            ],
        )

        rels = reader.read_as_relations("graph1")
        assert len(rels) == 1
        assert rels[0]["type"] == "family"
        assert rels[0]["description"] == "张三是李四的哥哥"
        assert rels[0]["graph_edge_uuid"] == "e1"

    def test_empty_graph(self, reader, mock_zep_client):
        _setup(mock_zep_client, nodes=[])

        result = reader.read_entities("graph1")
        assert result == []


class TestZepEntityReaderPhase4ReadOnly:
    """Phase 4: ZepEntityReader is read-only — it must not write to M2Character."""

    def test_read_only_not_write_to_db(self, reader, mock_zep_client):
        """Reading Zep entities should not trigger any DB write operations."""
        _setup(
            mock_zep_client,
            [
                _make_node("n1", "张三", ["character"], "主角"),
                _make_node("n2", "李四", ["character"], "配角"),
            ],
            edges=[
                _make_edge("e1", "friend", "朋友关系", "n1", "n2"),
            ],
        )

        # Patch any DB write methods to ensure they are never called
        with (
            patch("src.db.repositories.character_repo.CharacterRepository") as mock_char_repo,
            patch("src.db.repositories.relation_repo.RelationRepository") as mock_rel_repo,
        ):
            # Read entities — this should be purely read-only
            entities = reader.read_entities("graph1", enrich_with_edges=True)
            assert len(entities) == 2

            # Also test read_as_characters and read_as_relations
            chars = reader.read_as_characters("graph1")
            assert len(chars) == 2

            rels = reader.read_as_relations("graph1")
            assert len(rels) == 1

            # Verify no DB write methods were called
            mock_char_repo.assert_not_called()
            mock_rel_repo.assert_not_called()

    def test_no_write_methods_exist(self, reader):
        """ZepEntityReader should not have any methods that write to DB."""
        db_write_methods = [
            "write_to_db",
            "persist",
            "save_characters",
            "save_relations",
            "sync_to_db",
            "import_to_db",
            "_persist",
        ]
        for method_name in db_write_methods:
            assert not hasattr(reader, method_name), (
                f"ZepEntityReader.{method_name} should not exist — ZepEntityReader is read-only"
            )
