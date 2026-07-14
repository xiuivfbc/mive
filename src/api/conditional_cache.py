"""Conditional caching helpers (Last-Modified / If-Modified-Since / 304)."""

from datetime import UTC, datetime
from email.utils import format_datetime, parsedate_to_datetime

from fastapi import Request, Response


def check_not_modified(request: Request, last_modified: datetime | None) -> Response | None:
    """If-Modified-Since matches → return 304 Response, else None."""
    if last_modified is None:
        return None
    ims_header = request.headers.get("if-modified-since")
    if not ims_header:
        return None
    try:
        ims = parsedate_to_datetime(ims_header)  # tz-aware
    except (ValueError, TypeError):
        return None
    # Normalize to naive UTC for comparison (second precision)
    ims_naive = ims.astimezone(UTC).replace(tzinfo=None, microsecond=0)
    # Normalize to naive UTC: attach UTC if naive, convert if tz-aware
    if last_modified.tzinfo is None:
        lm_naive = last_modified.replace(tzinfo=None, microsecond=0)
    else:
        lm_naive = last_modified.astimezone(UTC).replace(tzinfo=None, microsecond=0)
    if lm_naive <= ims_naive:
        return Response(status_code=304)
    return None


def set_cache_headers(
    response: Response,
    last_modified: datetime,
    *,
    public: bool = False,
) -> None:
    """Set Last-Modified + Cache-Control headers.

    ``public=True`` for unauthenticated endpoints.
    """
    # format_datetime(usegmt=True) requires tz-aware UTC; attach if missing
    lm = last_modified if last_modified.tzinfo else last_modified.replace(tzinfo=UTC)
    response.headers["Last-Modified"] = format_datetime(lm, usegmt=True)
    directive = "public" if public else "private"
    response.headers["Cache-Control"] = f"{directive}, must-revalidate"
