"""Discord message sender — consumes SSE event stream and posts to a Thread."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator

import discord

logger = logging.getLogger(__name__)

_NARRATOR_COLOR = 0x5865F2  # Discord blurple


def _parse_sse(chunk: str) -> tuple[str, dict] | None:
    """Parse a single SSE chunk into (event_type, data_dict). Returns None if unparseable."""
    event_type = ""
    data_str = ""
    for line in chunk.splitlines():
        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_str = line[5:].strip()
    if not event_type or not data_str:
        return None
    try:
        return event_type, json.loads(data_str)
    except json.JSONDecodeError:
        return None


async def stream_to_thread(
    thread: discord.Thread,
    sse_generator: AsyncGenerator[str, None],
    webhook_by_character_id: dict[str, str],
    narrator_webhook_url: str | None,
) -> None:
    """Read SSE events and post each turn into the Discord Thread.

    webhook_by_character_id: {character_id_str: webhook_url}
    """
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as http:
        async for chunk in sse_generator:
            parsed = _parse_sse(chunk)
            if parsed is None:
                continue
            event_type, data = parsed

            if event_type == "speaker_turn":
                char_id = str(data.get("sender_id", ""))
                name = data.get("sender_name", "角色")
                content = data.get("content", "")
                wh_url = webhook_by_character_id.get(char_id)

                if wh_url:
                    await _post_webhook(http, wh_url, content, thread.id)
                else:
                    # Fallback: post as regular message with name prefix
                    await thread.send(f"**{name}**: {content}")

            elif event_type == "narrator_turn":
                content = data.get("content", "")
                location = data.get("location", "")
                atmosphere = data.get("atmosphere", "")
                description = content
                if location:
                    description = f"**{location}**\n{content}"
                if atmosphere:
                    description = f"{description}\n*{atmosphere}*"

                embed = discord.Embed(
                    title="旁白",
                    description=description,
                    color=_NARRATOR_COLOR,
                )

                if narrator_webhook_url:
                    payload = {
                        "embeds": [embed.to_dict()],
                        "thread_id": str(thread.id),
                    }
                    resp = await http.post(narrator_webhook_url, json=payload)
                    resp.raise_for_status()
                else:
                    await thread.send(embed=embed)

            elif event_type == "done":
                await thread.send("── 完 ──")
                break

            elif event_type == "error":
                msg = data.get("message", "未知错误")
                logger.error("SSE error event: %s", msg)
                await thread.send(f"⚠️ {msg}")
                break


async def _post_webhook(
    http,
    webhook_url: str,
    content: str,
    thread_id: int,
) -> None:
    """Post a message to a webhook, targeting a specific thread."""
    payload = {"content": content, "thread_id": str(thread_id)}
    resp = await http.post(webhook_url, json=payload)
    resp.raise_for_status()
