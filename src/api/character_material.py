from fastapi import APIRouter, Depends, HTTPException

from src.api.deps import get_material_service, get_world_service
from src.services.material_service import MaterialService
from src.services.world_service import WorldService

router = APIRouter(prefix="/api/worlds", tags=["character-material"])


@router.get("/{world_id}/character-material")
async def get_character_material(
    world_id: str,
    world_service: WorldService = Depends(get_world_service),
    material_service: MaterialService = Depends(get_material_service),
):
    world = await world_service.get_world(world_id)
    if world is None:
        raise HTTPException(status_code=404, detail="World not found")
    return material_service.generate(world)
