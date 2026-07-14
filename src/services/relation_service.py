from src.db.repositories.character_repo import CharacterRepository
from src.db.repositories.relation_repo import RelationRepository
from src.models.relation import CreateRelationRequest, Relation, UpdateRelationRequest


class RelationService:
    def __init__(self, repo: RelationRepository, character_repo: CharacterRepository | None = None):
        self.repo = repo
        self.character_repo = character_repo

    async def create(self, world_id: str, req: CreateRelationRequest) -> Relation:
        if self.character_repo:
            char_a = await self.character_repo.get_by_id(req.character_a)
            char_b = await self.character_repo.get_by_id(req.character_b)
            if char_a is None or char_b is None:
                raise ValueError("Character not found")
        return await self.repo.create(world_id, req)

    async def get(self, relation_id: str) -> Relation | None:
        return await self.repo.get_by_id(relation_id)

    async def list_by_world(self, world_id: str, character_id: str | None = None) -> list[Relation]:
        return await self.repo.list_by_world(world_id, character_id)

    async def delete(self, relation_id: str) -> bool:
        return await self.repo.delete(relation_id)

    async def delete_by_character(self, character_id: str) -> int:
        return await self.repo.delete_by_character(character_id)

    async def update(self, relation_id: str, req: UpdateRelationRequest) -> Relation | None:
        return await self.repo.update(relation_id, req)
