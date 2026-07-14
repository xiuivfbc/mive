"""Import API — parse user-supplied JSON and bulk-insert into a world."""

from __future__ import annotations

import logging
import uuid as _uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.deps import (
    build_element_retrieval_from_session,
    get_character_service,
    get_element_retrieval_service,
    get_relation_service,
    get_session,
    get_world_service,
)
from src.db.session import async_session
from src.models.character import Character, CreateCharacterRequest, UpdateCharacterRequest
from src.models.relation import CreateRelationRequest
from src.services.character_service import CharacterService
from src.services.relation_service import RelationService
from src.services.snapshot_sync_service import bump_generation_sql, publish_snapshot_dirty
from src.services.world_service import WorldService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/worlds", tags=["import"])


# ── World fields import ────────────────────────────────────────────────────


class ImportWorldFieldsPreviewRequest(BaseModel):
    """Preview world field import."""

    data: dict[str, str] = Field(default_factory=dict)
    strategies: dict[str, str] = Field(default_factory=dict)


class ImportWorldFieldsConfirmRequest(BaseModel):
    """Confirm world field import with new values and strategies."""

    data: dict[str, str] = Field(default_factory=dict)
    strategies: dict[str, str] = Field(default_factory=dict)


@router.post("/{world_id}/import/preview-world-fields", response_model=dict)
async def preview_world_fields(
    world_id: str,
    req: ImportWorldFieldsPreviewRequest,
    world_service: WorldService = Depends(get_world_service),
):
    """Preview world field import. Returns old values + new values for comparison."""
    world = await world_service.get_world(world_id)
    if not world:
        raise HTTPException(404, "World not found")

    source = world.source
    preview_fields: dict[str, dict] = {}
    valid_fields = {
        "plot_summary",
        "common_sense",
        "core_conflict",
        "tone_and_atmosphere",
        "plot_development",
    }
    for key, new_val in req.data.items():
        if key not in valid_fields:
            continue
        old_val = getattr(source, key, None) or ""
        strategy = req.strategies.get(key, "overwrite")
        merged = _merge_field(old_val, new_val, strategy)
        preview_fields[key] = {
            "old": old_val,
            "new": new_val,
            "merged": merged,
            "strategy": strategy,
        }

    return {"world_fields": preview_fields}


@router.post("/{world_id}/import/world-fields", status_code=204)
async def confirm_world_fields_import(
    world_id: str,
    req: ImportWorldFieldsConfirmRequest,
    bg_tasks: BackgroundTasks,
    request: Request,
    world_service: WorldService = Depends(get_world_service),
    session=Depends(get_session),
):
    """Apply world field import after confirmation."""
    valid_fields = {
        "plot_summary",
        "common_sense",
        "core_conflict",
        "tone_and_atmosphere",
        "plot_development",
    }
    for key, new_val in req.data.items():
        if key not in valid_fields:
            continue
        strategy = req.strategies.get(key, "overwrite")
        if strategy == "skip":
            continue

        # Directly use the service methods
        merged = new_val
        if strategy == "append":
            world = await world_service.get_world(world_id)
            if world:
                current = getattr(world.source, key, None) or ""
                merged = f"{current}\n\n{new_val}" if current else new_val

        # Apply via the appropriate service method
        if key == "plot_summary":
            await world_service.update_plot_summary(world_id, merged)
        elif key == "common_sense":
            await world_service.update_common_sense(world_id, merged)
        elif key == "core_conflict":
            await world_service.update_core_conflict(world_id, merged)
        elif key == "tone_and_atmosphere":
            await world_service.update_tone_and_atmosphere(world_id, merged)
        elif key == "plot_development":
            await world_service.update_plot_development(world_id, merged)

    await bump_generation_sql(world_id, session)
    bg_tasks.add_task(publish_snapshot_dirty, request.app.state.redis, world_id, "world_fields")


# ── Graph (characters + relations) import ──────────────────────────────────


class ImportCharacterItem(BaseModel):
    name: str = Field(min_length=1)
    tier: str = Field(default="extra")
    brief: str = ""
    detail: str = ""
    personality: str = ""
    speech_style: str = ""


class ImportRelationItem(BaseModel):
    character_a: str = Field(min_length=1)
    character_b: str = Field(min_length=1)
    type: str | None = None
    description: str | None = None
    direction: str = "bidirectional"


class ImportGraphPreviewRequest(BaseModel):
    characters: list[ImportCharacterItem] = Field(default_factory=list)
    relations: list[ImportRelationItem] = Field(default_factory=list)


class ImportGraphConfirmRequest(BaseModel):
    characters: list[ImportCharacterItem] = Field(default_factory=list)
    relations: list[ImportRelationItem] = Field(default_factory=list)


@router.post("/{world_id}/import/preview-graph", response_model=dict)
async def preview_graph_import(
    world_id: str,
    req: ImportGraphPreviewRequest,
    character_service: CharacterService = Depends(get_character_service),
    relation_service: RelationService = Depends(get_relation_service),
):
    """Preview character + relation import. Resolves existing characters."""
    existing = await character_service.list_by_world(world_id)
    existing_map: dict[str, Character] = {str(c.id): c for c in existing}
    name_to_id: dict[str, str] = {}
    for c in existing:
        name_to_id[c.name.lower()] = str(c.id)

    # Load existing active relations for duplicate detection
    existing_relations = await relation_service.list_by_world(world_id)
    existing_rel_set: set[tuple[str, str, str]] = {
        (r.character_a, r.character_b, r.direction)
        for r in existing_relations
        if r.status == "active"
    }

    imported_chars: list[dict] = []
    new_count = 0
    existing_count = 0
    name_to_placeholder: dict[str, str] = {}

    for i, char_req in enumerate(req.characters):
        lower_name = char_req.name.lower()
        if lower_name in name_to_id:
            c = existing_map[name_to_id[lower_name]]
            imported_chars.append(
                {
                    "index": i,
                    "id": str(c.id),
                    "name": c.name,
                    "tier": char_req.tier,
                    "brief": char_req.brief,
                    "detail": char_req.detail,
                    "personality": char_req.personality,
                    "speech_style": char_req.speech_style,
                    "status": "existing",
                }
            )
            existing_count += 1
        else:
            new_count += 1
            placeholder_id = f"_new_{i}"
            imported_chars.append(
                {
                    "index": i,
                    "id": placeholder_id,
                    "name": char_req.name,
                    "tier": char_req.tier,
                    "brief": char_req.brief,
                    "detail": char_req.detail,
                    "personality": char_req.personality,
                    "speech_style": char_req.speech_style,
                    "status": "new",
                }
            )
            name_to_placeholder[lower_name] = placeholder_id

    # Preview relations (resolve IDs + detect existing)
    relation_previews: list[dict] = []
    valid_rel = 0
    skipped_rel = 0
    for rel_req in req.relations:
        a_id = _resolve_character_ref(
            rel_req.character_a, existing_map, name_to_id, name_to_placeholder
        )
        b_id = _resolve_character_ref(
            rel_req.character_b, existing_map, name_to_id, name_to_placeholder
        )
        entry = {
            "character_a": rel_req.character_a,
            "character_b": rel_req.character_b,
            "resolved_a": a_id,
            "resolved_b": b_id,
            "type": rel_req.type,
            "description": rel_req.description,
            "direction": rel_req.direction,
        }
        if a_id and b_id:
            # Check if this relation already exists
            rel_key = (a_id, b_id, rel_req.direction or "bidirectional")
            if rel_key in existing_rel_set:
                entry["status"] = "skipped"
                skipped_rel += 1
            else:
                entry["status"] = "valid"
                valid_rel += 1
        else:
            entry["status"] = "skipped"
            skipped_rel += 1
        relation_previews.append(entry)

    return {
        "characters": imported_chars,
        "relations": relation_previews,
        "new_characters": new_count,
        "existing_characters": existing_count,
        "valid_relations": valid_rel,
        "skipped_relations": skipped_rel,
    }


@router.post("/{world_id}/import/graph", status_code=200, response_model=dict)
async def confirm_graph_import(
    world_id: str,
    req: ImportGraphConfirmRequest,
    bg_tasks: BackgroundTasks,
    request: Request,
    character_service: CharacterService = Depends(get_character_service),
    relation_service: RelationService = Depends(get_relation_service),
    world_service: WorldService = Depends(get_world_service),
    session=Depends(get_session),
):
    """Actually import characters and relations."""
    world = await world_service.get_world(world_id)
    if not world:
        raise HTTPException(404, "World not found")

    existing = await character_service.list_by_world(world_id)
    existing_map: dict[str, Character] = {str(c.id): c for c in existing}
    name_to_id: dict[str, str] = {c.name.lower(): str(c.id) for c in existing}

    created_chars: dict[str, str] = {}  # name_lower -> char_id

    # 1. Create / update characters
    for char_req in req.characters:
        lower_name = char_req.name.lower()
        if lower_name in name_to_id:
            cid = name_to_id[lower_name]
            profile: dict = {
                "brief": char_req.brief,
                "detail": char_req.detail,
                "personality": char_req.personality,
                "speech_style": char_req.speech_style,
            }
            await character_service.update(
                cid,
                UpdateCharacterRequest(tier=char_req.tier, profile=profile),
                fields_set={"tier", "profile"},
            )
            created_chars[lower_name] = cid
        else:
            resp = await character_service.create(
                world_id,
                CreateCharacterRequest(
                    name=char_req.name,
                    profile={
                        "brief": char_req.brief,
                        "detail": char_req.detail,
                        "personality": char_req.personality,
                        "speech_style": char_req.speech_style,
                    },
                ),
            )
            if char_req.tier and char_req.tier != "extra":
                await character_service.update(
                    str(resp.id),
                    UpdateCharacterRequest(tier=char_req.tier),
                    fields_set={"tier"},
                )
            created_chars[lower_name] = str(resp.id)

    # 2. Create relations (skip existing to avoid unique constraint violation)
    created_rels: int = 0
    existing_relations = await relation_service.list_by_world(world_id)
    existing_rel_set: set[tuple[str, str, str]] = {
        (r.character_a, r.character_b, r.direction)
        for r in existing_relations
        if r.status == "active"
    }
    for rel_req in req.relations:
        a_id = _resolve_character_ref(rel_req.character_a, existing_map, name_to_id, created_chars)
        b_id = _resolve_character_ref(rel_req.character_b, existing_map, name_to_id, created_chars)
        if not (a_id and b_id):
            continue
        # Skip if an active relation with the same pair + direction already exists
        rel_key = (a_id, b_id, rel_req.direction or "bidirectional")
        if rel_key in existing_rel_set:
            continue
        cr = CreateRelationRequest(
            character_a=a_id,
            character_b=b_id,
            type=rel_req.type,
            description=rel_req.description,
            direction=rel_req.direction,
        )
        await relation_service.create(world_id, cr)
        created_rels += 1

    # 3. Side effects
    await bump_generation_sql(world_id, session)
    bg_tasks.add_task(publish_snapshot_dirty, request.app.state.redis, world_id, "character")

    return {"characters": len(created_chars), "relations": created_rels}


# ── Elements import ────────────────────────────────────────────────────────


class ImportElementItem(BaseModel):
    name: str = Field(min_length=1)
    category: str = ""
    brief: str = ""
    detail: str = ""


class ImportElementsPreviewRequest(BaseModel):
    elements: list[ImportElementItem] = Field(default_factory=list)


class ImportElementsConfirmRequest(BaseModel):
    elements: list[ImportElementItem] = Field(default_factory=list)


@router.post("/{world_id}/import/preview-elements", response_model=dict)
async def preview_elements_import(
    world_id: str,
    req: ImportElementsPreviewRequest,
    world_service: WorldService = Depends(get_world_service),
):
    """Preview element import. Checks for duplicates by name."""
    world = await world_service.get_world(world_id)
    if not world:
        raise HTTPException(404, "World not found")

    existing_names = {e.name.lower() for e in world.elements}
    imported: list[dict] = []
    new_count = 0
    existing_count = 0

    for elem_req in req.elements:
        lower_name = elem_req.name.lower()
        status = "existing" if lower_name in existing_names else "new"
        if status == "existing":
            existing_count += 1
        else:
            new_count += 1
        imported.append(
            {
                "name": elem_req.name,
                "category": elem_req.category,
                "brief": elem_req.brief,
                "detail": elem_req.detail,
                "status": status,
            }
        )

    return {
        "elements": imported,
        "new_elements": new_count,
        "existing_elements": existing_count,
    }


@router.post("/{world_id}/import/elements", status_code=200, response_model=dict)
async def confirm_elements_import(
    world_id: str,
    req: ImportElementsConfirmRequest,
    bg_tasks: BackgroundTasks,
    request: Request,
    world_service: WorldService = Depends(get_world_service),
    retrieval_service=Depends(get_element_retrieval_service),
    session=Depends(get_session),
):
    """Actually import elements (overwrite duplicates)."""
    world = await world_service.get_world(world_id)
    if not world:
        raise HTTPException(404, "World not found")

    existing_names = {e.name.lower(): e for e in world.elements}
    created_count = 0

    for elem_req in req.elements:
        lower_name = elem_req.name.lower()
        if lower_name in existing_names:
            existing_elem = existing_names[lower_name]
            await world_service.update_element(
                world_id,
                existing_elem.id,
                brief=elem_req.brief,
                detail=elem_req.detail,
                name=elem_req.name,
                category=elem_req.category,
            )
            created_count += 1
        else:
            result = await world_service.add_element(
                world_id,
                category=elem_req.category,
                name=elem_req.name,
                brief=elem_req.brief,
                detail=elem_req.detail,
            )
            if result:
                created_count += 1

    await bump_generation_sql(world_id, session)
    bg_tasks.add_task(publish_snapshot_dirty, request.app.state.redis, world_id, "element")

    # Trigger embedding rebuilds
    if retrieval_service and created_count > 0:
        provider = getattr(request.app.state, "embedding_provider", None)
        if provider:
            async def _rebuild_all_embeddings():
                try:
                    async with async_session() as emb_session:
                        svc = build_element_retrieval_from_session(emb_session, provider)
                        if svc:
                            await svc.rebuild_embeddings(world_id)
                            await emb_session.commit()
                except Exception:
                    logger.warning(
                        "import embedding rebuild failed (non-fatal) world=%s",
                        world_id,
                        exc_info=True,
                    )

            bg_tasks.add_task(_rebuild_all_embeddings)

    return {"created": created_count}


# ── Shared helpers ─────────────────────────────────────────────────────────


def _resolve_character_ref(
    ref: str,
    existing_chars: dict[str, Character],
    name_to_id: dict[str, str],
    new_chars: dict[str, str],
) -> str | None:
    """Return the resolved character ID, or None if not found."""
    ref = ref.strip()
    if not ref:
        return None

    # 1. Try as UUID
    try:
        cid = _uuid.UUID(ref)
        if str(cid) in existing_chars:
            return str(cid)
        if str(cid) in new_chars:
            return new_chars[str(cid)]
        return None
    except (ValueError, TypeError):
        pass

    # 2. Try as name (existing)
    lower = ref.lower()
    if lower in name_to_id:
        return name_to_id[lower]

    # 3. Try as name (newly created in this batch)
    if lower in new_chars:
        return new_chars[lower]

    return None


def _merge_field(old: str, new: str, strategy: str) -> str:
    """Merge old and new text based on strategy."""
    if strategy == "overwrite":
        return new
    elif strategy == "append":
        parts = [p for p in [old, new] if p and p.strip()]
        return "\n\n".join(parts)
    else:  # skip
        return old
