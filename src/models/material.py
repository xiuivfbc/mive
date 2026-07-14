from datetime import datetime

from pydantic import BaseModel

from src.models.world import Element

# MaterialElement is just an Element used in the material context.
MaterialElement = Element


class CharacterMaterial(BaseModel):
    world_id: str
    world_version: str
    world_elements: list[Element]
    world_rules_summary: str
    generated_at: datetime
