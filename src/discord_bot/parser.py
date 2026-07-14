from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ParsedCommand:
    mode: Literal["event", "chat"]
    content: str
    inclusions: list[str] = field(default_factory=list)
    exclusive: bool = False


def parse_command(text: str) -> ParsedCommand:
    """Parse a Discord message into a structured command.

    Syntax:
        !{content}              → event mode, LLM selects characters
        !+{name} {content}      → event, include character (LLM may add more)
        !=+{name} {content}     → event, exclusive character list
        {content}               → chat mode, LLM selects characters
        +{name} {content}       → chat, include character
        ={name} {content}       → chat, exclusive character
    """
    text = text.strip()
    if not text:
        raise ValueError("Empty command")

    mode: Literal["event", "chat"]
    if text.startswith("!"):
        mode = "event"
        text = text[1:]
    else:
        mode = "chat"

    inclusions: list[str] = []
    exclusive = False
    content_parts: list[str] = []

    for token in text.split():
        if token.startswith("=") and len(token) > 1:
            exclusive = True
            inclusions.append(token[1:])
        elif token.startswith("+") and len(token) > 1:
            inclusions.append(token[1:])
        else:
            content_parts.append(token)

    return ParsedCommand(
        mode=mode,
        content=" ".join(content_parts),
        inclusions=inclusions,
        exclusive=exclusive,
    )
