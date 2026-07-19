"""Guide content API — public read."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.conditional_cache import check_not_modified, set_cache_headers
from src.api.deps import get_session
from src.db.models import M23GuideContent

router = APIRouter(tags=["guide"])

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class GuideResponse(BaseModel):
    all_content: str
    recent_content: str
    recent_updated_at: str | None
    context_help: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_or_create_guide(session: AsyncSession) -> M23GuideContent:
    """Return the single guide row; create one if missing (idempotent)."""
    result = await session.execute(select(M23GuideContent).limit(1))
    row = result.scalar_one_or_none()
    if row is None:
        row = M23GuideContent(all_content="", recent_content="")
        session.add(row)
        await session.flush()
    return row


# ---------------------------------------------------------------------------
# Public: GET /api/guide
# ---------------------------------------------------------------------------


@router.get("/api/guide", response_model=GuideResponse)
async def get_guide(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    row = await _get_or_create_guide(session)
    not_mod = check_not_modified(request, row.updated_at)
    if not_mod:
        return not_mod
    set_cache_headers(response, row.updated_at, public=False)
    return GuideResponse(
        all_content=row.all_content or "",
        recent_content=row.recent_content or "",
        recent_updated_at=row.recent_updated_at.isoformat() if row.recent_updated_at else None,
        context_help=row.context_help or "{}",
    )
