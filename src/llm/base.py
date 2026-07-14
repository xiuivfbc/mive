import json
import logging
from abc import ABC, abstractmethod

# 当前 LLM 调用的业务操作名，由各 service 入口 set
from contextvars import ContextVar
from dataclasses import dataclass

# ── re-export：保持 from src.llm.base import xxx 的兼容性 ──
from .json_repair import extract_json  # noqa: F401
from .language import get_lang_hint, user_language  # noqa: F401

llm_operation: ContextVar[str] = ContextVar("llm_operation", default="未知操作")

# Token usage accumulator for the current request
_token_usage_accumulator: ContextVar[int] = ContextVar("_token_usage_accumulator", default=0)


def reset_token_usage() -> None:
    """Reset the token usage accumulator. Call at the start of each request."""
    _token_usage_accumulator.set(0)


def get_and_reset_token_usage() -> int:
    """Get accumulated token usage and reset. Call at the end of a request."""
    total = _token_usage_accumulator.get()
    _token_usage_accumulator.set(0)
    return total


_token_logger = logging.getLogger("llm.tokens")


def _log_token_usage(
    *,
    provider: str,
    model: str,
    call_type: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    latency_ms: int,
    max_tokens: int,
) -> None:
    record = {
        "operation": llm_operation.get(),
        "provider": provider,
        "model": model,
        "call_type": call_type,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "latency_ms": latency_ms,
        "max_tokens": max_tokens,
    }
    _token_logger.info(json.dumps(record, ensure_ascii=False))
    # Accumulate actual token usage (input + output, cache already in input)
    _token_usage_accumulator.set(_token_usage_accumulator.get() + input_tokens + output_tokens)


@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int


class LLMPriority:
    """LLM 调用优先级常量。数字越小优先级越高。"""

    CHAT = 0  # 聊天发消息（最高优先级）
    EVENT = 1  # 事件推演
    BACKGROUND = 2  # 世界创建、角色生成（最低优先级）


class LLMQuotaExhaustedError(Exception):
    """API key 额度/Credits 耗尽，需用户介入处理。"""

    def __init__(self, provider: str, model: str):
        self.provider = provider
        self.model = model
        super().__init__(f"LLM quota exhausted: provider={provider}, model={model}")


class LLMProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        system: str,
        prompt: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        cacheable_system_prefix: str | None = None,
        thinking: dict | None = None,
        priority: int = LLMPriority.BACKGROUND,
    ) -> LLMResponse: ...

    @abstractmethod
    async def complete_json(
        self,
        system: str,
        prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        prefill: str = "{",
        cacheable_system_prefix: str | None = None,
        thinking: dict | None = None,
        priority: int = LLMPriority.BACKGROUND,
        operation: str | None = None,
        expect: type[dict] | type[list] = dict,
    ) -> dict | list: ...
