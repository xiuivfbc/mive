"""M6 图谱 API — 本体生成、图谱构建、任务查询、实体读取。"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.api.deps import get_world_service
from src.services.world_service import WorldService

router = APIRouter(prefix="/api/worlds/{world_id}/graph", tags=["m6-graph"])


@router.get("/config")
async def graph_config(request: Request):
    """返回图谱功能可用状态。"""
    available = getattr(request.app.state, "graph_builder", None) is not None
    return {"zep_available": available}


def _svc(request: Request, name: str):
    val = getattr(request.app.state, name, None)
    if val is None:
        raise HTTPException(
            500, f"Service '{name}' not available. Check ZEP_API_KEY configuration."
        )
    return val


@router.post("/ontology/generate")
async def generate_ontology(
    world_id: str,
    request: Request,
    body: dict | None = None,
    world_service: WorldService = Depends(get_world_service),
):
    ontology_gen = _svc(request, "ontology_generator")
    world = await world_service.get_world(world_id)
    if world is None:
        raise HTTPException(404, "World not found")

    world_doc = ""
    if world.elements:
        world_doc = "\n".join(f"[{e.category}] {e.name}: {e.brief}" for e in world.elements)

    preference = body.get("entity_types") if body else None
    result = await ontology_gen.generate(world_doc=world_doc, entity_types_preference=preference)
    return result


@router.post("/build")
async def build_graph(
    world_id: str,
    request: Request,
    body: dict,
    world_service: WorldService = Depends(get_world_service),
):
    builder = _svc(request, "graph_builder")
    world = await world_service.get_world(world_id)
    if world is None:
        raise HTTPException(404, "World not found")

    ontology = body.get("ontology", {})
    text = ""
    if world.elements:
        text = "\n".join(f"{e.name}: {e.detail or e.brief}" for e in world.elements)
    if not text and world.source and world.source.input_text:
        text = world.source.input_text

    task_id = builder.build_async(world_id=world_id, text=text, ontology=ontology)
    return {"task_id": task_id}


@router.get("/task/{task_id}")
async def get_task(
    world_id: str,
    task_id: str,
    request: Request,
):
    tm = _svc(request, "task_manager")
    task = tm.get_task(task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    return task.to_dict()


@router.get("/entities")
async def get_entities(
    world_id: str,
    request: Request,
    entity_types: str | None = Query(None),
    enrich_with_edges: bool = Query(False),
    world_service: WorldService = Depends(get_world_service),
):
    reader = _svc(request, "entity_reader")
    world = await world_service.get_world(world_id)
    if world is None or not getattr(world, "graph_id", None):
        raise HTTPException(404, "Graph not built for this world")

    types = entity_types.split(",") if entity_types else None
    entities = reader.read_entities(
        graph_id=world.graph_id,
        entity_types=types,
        enrich_with_edges=enrich_with_edges,
    )
    return {"entities": entities}
