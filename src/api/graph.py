from fastapi import APIRouter, Depends, Request

from src.api.characters import redact_portrait_urls
from src.api.deps import get_character_service, get_relation_service, get_world_service
from src.services.character_service import CharacterService
from src.services.relation_service import RelationService
from src.services.world_service import WorldService

router = APIRouter(prefix="/api/worlds/{world_id}/graph", tags=["graph"])


@router.get("/data")
async def get_graph_data(
    world_id: str,
    request: Request,
    char_service: CharacterService = Depends(get_character_service),
    rel_service: RelationService = Depends(get_relation_service),
    world_service: WorldService = Depends(get_world_service),
):
    characters = await char_service.list_by_world(world_id)
    redact_portrait_urls(characters)
    relations = await rel_service.list_by_world(world_id)

    world = await world_service.get_world(world_id)

    # M6 graph fields from app.state task_manager (if configured)
    graph_status = "idle"
    graph_ontology = None
    if world is not None:
        graph_status = getattr(world, "graph_status", None) or "idle"
        graph_ontology = getattr(world, "graph_ontology", None)

    return {
        "characters": [c.model_dump() for c in characters],
        "relations": [r.model_dump() for r in relations],
        "graph_status": graph_status,
        "graph_ontology": graph_ontology,
    }
