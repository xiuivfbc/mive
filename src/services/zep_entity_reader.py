"""M6 ZepEntityReader — 从 Zep 图谱读取实体和边，过滤并映射为 MIVE 数据结构。"""


class ZepEntityReader:
    def __init__(self, zep_client):
        self.zep = zep_client

    def _fetch_all_nodes(self, graph_id: str) -> list[dict]:
        results = self.zep.graph.node.get_by_user_id(graph_id, limit=2000)
        return [
            {
                "uuid": n.uuid_,
                "name": n.name or "",
                "labels": n.labels or [],
                "summary": n.summary or "",
                "attributes": n.attributes or {},
            }
            for n in (results or [])
        ]

    def _fetch_all_edges(self, graph_id: str) -> list[dict]:
        results = self.zep.graph.edge.get_by_user_id(graph_id, limit=2000)
        return [
            {
                "uuid": e.uuid_,
                "name": e.name or "",
                "fact": e.fact or "",
                "source_node_uuid": e.source_node_uuid,
                "target_node_uuid": e.target_node_uuid,
                "attributes": e.attributes or {},
            }
            for e in (results or [])
        ]

    def read_entities(
        self,
        graph_id: str,
        entity_types: list[str] | None = None,
        enrich_with_edges: bool = False,
    ) -> list[dict]:
        nodes = self._fetch_all_nodes(graph_id)
        edges = self._fetch_all_edges(graph_id) if enrich_with_edges else []

        _node_map = {n["uuid"]: n for n in nodes}
        result = []

        for node in nodes:
            labels = node["labels"]
            custom_labels = [label for label in labels if label not in ("Entity", "Node", "User")]
            if not custom_labels:
                continue

            entity_type = custom_labels[0]
            if entity_types and entity_type not in entity_types:
                continue

            entry = {
                "uuid": node["uuid"],
                "name": node["name"],
                "entity_type": entity_type,
                "labels": labels,
                "summary": node["summary"],
                "attributes": node["attributes"],
                "related_edges": [],
            }

            if enrich_with_edges:
                for edge in edges:
                    if edge["source_node_uuid"] == node["uuid"]:
                        entry["related_edges"].append(
                            {
                                "direction": "outgoing",
                                "edge_name": edge["name"],
                                "fact": edge["fact"],
                                "target_node_uuid": edge["target_node_uuid"],
                            }
                        )
                    elif edge["target_node_uuid"] == node["uuid"]:
                        entry["related_edges"].append(
                            {
                                "direction": "incoming",
                                "edge_name": edge["name"],
                                "fact": edge["fact"],
                                "source_node_uuid": edge["source_node_uuid"],
                            }
                        )

            result.append(entry)
        return result

    def read_as_characters(self, graph_id: str) -> list[dict]:
        entities = self.read_entities(graph_id)
        return [
            {
                "name": e["name"],
                "entity_type": e["entity_type"],
                "graph_node_uuid": e["uuid"],
                "profile": {
                    "basic": {"name": e["name"]},
                    "brief": e["summary"],
                },
            }
            for e in entities
        ]

    def read_as_relations(self, graph_id: str) -> list[dict]:
        edges = self._fetch_all_edges(graph_id)
        return [
            {
                "type": e["name"],
                "description": e["fact"],
                "graph_edge_uuid": e["uuid"],
                "_source_uuid": e["source_node_uuid"],
                "_target_uuid": e["target_node_uuid"],
            }
            for e in edges
        ]
