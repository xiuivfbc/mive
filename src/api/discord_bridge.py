from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_session
from src.models.discord_bridge import DiscordBinding, DiscordBindingCreate
from src.services.discord_bridge_service import DiscordBridgeService

router = APIRouter(prefix="/api/worlds/{world_id}/discord-binding", tags=["discord-bridge"])


def _get_service(request: Request, session: AsyncSession) -> DiscordBridgeService:
    override = getattr(request.app.state, "discord_bridge_service", None)
    if override is not None:
        return override
    from src.db.repositories.discord_bridge_repo import DiscordBridgeRepository

    return DiscordBridgeService(repo=DiscordBridgeRepository(session))


def _get_service_with_wm(request: Request, session: AsyncSession) -> DiscordBridgeService:
    """Service variant that includes WebhookManager (requires DISCORD_BOT_TOKEN)."""
    override = getattr(request.app.state, "discord_bridge_service", None)
    if override is not None:
        return override
    from src.config import settings
    from src.db.repositories.discord_bridge_repo import DiscordBridgeRepository
    from src.discord_bot.webhook_manager import WebhookManager

    repo = DiscordBridgeRepository(session)
    wm = (
        WebhookManager(bot_token=settings.discord_bot_token, repo=repo)
        if settings.discord_bot_token
        else None
    )
    return DiscordBridgeService(repo=repo, webhook_manager=wm)


@router.get("", response_model=DiscordBinding)
async def get_binding(
    world_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    svc = _get_service(request, session)
    binding = await svc.get_binding(world_id)
    if binding is None:
        raise HTTPException(status_code=404, detail="No Discord binding")
    return binding


@router.post("", response_model=DiscordBinding, status_code=201)
async def create_binding(
    world_id: str,
    body: DiscordBindingCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Store guild_id. Use /setup to create channels + webhooks."""
    svc = _get_service(request, session)
    binding = await svc.create_binding(world_id, body.guild_id)
    await session.commit()
    return binding


class SetupRequest(BaseModel):
    guild_id: str
    base_url: str = "http://localhost:2658"


@router.post("/setup", response_model=DiscordBinding, status_code=201)
async def setup_binding(
    world_id: str,
    body: SetupRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Create Discord channels + character webhooks, then save binding.

    base_url: public URL of this backend (e.g. from ngrok) so Discord can fetch avatars.
    """
    from src.db.repositories.character_repo import CharacterRepository
    from src.services.character_service import CharacterService

    svc = _get_service_with_wm(request, session)
    char_svc = CharacterService(repo=CharacterRepository(session))
    characters = await char_svc.list_by_world(world_id)

    try:
        binding = await svc.setup_binding(
            world_id=world_id,
            guild_id=body.guild_id,
            characters=characters,
            base_url=body.base_url.rstrip("/"),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Discord API error: {e}") from e

    await session.commit()
    return binding


@router.delete("", status_code=204)
async def delete_binding(
    world_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    svc = _get_service_with_wm(request, session)
    deleted = await svc.delete_binding(world_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="No Discord binding")
    await session.commit()
