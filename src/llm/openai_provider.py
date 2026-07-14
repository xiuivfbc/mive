import asyncio
import logging as _logging
import re
import time
from typing import cast

import openai
from openai.types.chat import ChatCompletionMessageParam

from .base import (
    LLMPriority,
    LLMProvider,
    LLMQuotaExhaustedError,
    LLMResponse,
    _log_token_usage,
    extract_json,
    llm_operation,
)
from .rate_limit_gate import RateLimitGate

_log = _logging.getLogger(__name__)


def _is_quota_error(exc: openai.APIStatusError) -> bool:
    msg = str(exc).lower()
    # OpenAI 的额度耗尽通常是 429 + error.code="insufficient_quota"，或 402
    if exc.status_code in (402, 429):
        if any(kw in msg for kw in ("insufficient_quota", "credit", "billing", "quota", "balance")):
            return True
    return False


def _get_retry_after(exc: openai.RateLimitError) -> float | None:
    """从 429 异常的响应头里提取 Retry-After 秒数。"""
    try:
        headers = exc.response.headers if exc.response else {}
        val = headers.get("retry-after")
        if val:
            return float(val)
    except Exception:
        pass
    return None


_THOUGHT_RE = re.compile(r"^(\s*<thought>.*?</thought>\s*)+", re.DOTALL)


def _strip_thinking_content(content: str) -> str:
    """剥离 Google Gemma 等模型返回的 <thought>...</thought> 前缀。

    只移除 content 开头连续的 thought 块，不影响正文及 content 中间出现的标签。
    """
    return _THOUGHT_RE.sub("", content)


def _build_gate(
    rpm: int | None, max_retries: int = 2, max_inflight: int | None = None
) -> RateLimitGate:
    """构建 Gate 实例（rpm=0 或 None 时不限速）。"""
    effective_rpm = rpm if (rpm and rpm > 0) else None
    return RateLimitGate(rpm=effective_rpm, max_retries=max_retries, max_inflight=max_inflight)


# 模块级 Gate 单例（懒初始化，第一次调 _get_gate() 时创建并 start）
_gate: RateLimitGate | None = None
_gate_started = False
_gate_lock = asyncio.Lock()


async def _get_gate() -> RateLimitGate:
    global _gate, _gate_started
    if _gate is None:
        from src.config import settings  # 延迟导入避免循环

        _gate = _build_gate(
            settings.llm_rpm,
            max_retries=settings.llm_max_retries if settings.llm_max_retries is not None else 2,
            max_inflight=settings.llm_max_inflight if settings.llm_max_inflight > 0 else None,
        )
    if not _gate_started:
        async with _gate_lock:
            if not _gate_started:
                await _gate.start()
                _gate_started = True
    return _gate


class OpenAIProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        max_retries: int = 0,  # 重试由 Gate 统一管理
        gate: RateLimitGate | None = None,
    ):
        self.client = openai.AsyncOpenAI(
            api_key=api_key, base_url=base_url, max_retries=max_retries
        )
        self.model = model
        self._gate = gate

    # ─────────────────── _do_request（HTTP 层） ───────────────────

    async def _do_request_complete(
        self,
        *,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> dict:
        """发一次 complete 请求，返回 {status, resp, retry_after}。
        quota 错误直接抛出，不经 gate 处理。
        """
        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=cast(list[ChatCompletionMessageParam], messages),
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return {"status": 200, "resp": resp, "retry_after": None}
        except openai.APIStatusError as e:
            if _is_quota_error(e):
                raise LLMQuotaExhaustedError("openai", self.model) from e
            retry_after = None
            if isinstance(e, openai.RateLimitError):
                retry_after = _get_retry_after(e)
            return {"status": e.status_code, "resp": None, "retry_after": retry_after}
        except (TimeoutError, ConnectionError, OSError, openai.APIConnectionError) as e:
            _log.warning("complete 网络错误: %s", e)
            return {"status": 0, "resp": None, "retry_after": None}

    async def _do_request_json(
        self,
        *,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        prefill: str,
    ) -> dict:
        """发一次 complete_json 请求（含 3 次 JSON 解析重试），返回 {status, text, retry_after}。"""
        last_exc: Exception | None = None
        total_input = total_output = 0
        t0 = time.monotonic()
        resp = None
        for attempt in range(3):
            try:
                resp = await self.client.chat.completions.create(
                    model=self.model,
                    messages=cast(list[ChatCompletionMessageParam], messages),
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except openai.APIStatusError as e:
                if _is_quota_error(e):
                    raise LLMQuotaExhaustedError("openai", self.model) from e
                retry_after = None
                if isinstance(e, openai.RateLimitError):
                    retry_after = _get_retry_after(e)
                return {
                    "status": e.status_code,
                    "text": "",
                    "retry_after": retry_after,
                    "_meta": None,
                }
            except (TimeoutError, ConnectionError, OSError, openai.APIConnectionError) as e:
                _log.warning("complete_json 网络错误: %s", e)
                return {"status": 0, "text": "", "retry_after": None, "_meta": None}

            usage = resp.usage
            total_input += usage.prompt_tokens if usage else 0
            total_output += usage.completion_tokens if usage else 0

            content = _strip_thinking_content(resp.choices[0].message.content or "")
            stripped = content.lstrip()
            if not stripped:
                _log.warning("complete_json 第 %d 次返回空响应，重试", attempt + 1)
                last_exc = ValueError("模型返回空响应")
                continue

            # 兼容裸数组响应直接用不拼前缀
            if stripped.startswith(prefill.lstrip()) or stripped.startswith("["):
                raw = stripped
            else:
                raw = prefill + content

            try:
                result = extract_json(raw)
                latency_ms = int((time.monotonic() - t0) * 1000)
                _log_token_usage(
                    provider="openai",
                    model=resp.model,
                    call_type="complete_json",
                    input_tokens=total_input,
                    output_tokens=total_output,
                    latency_ms=latency_ms,
                    max_tokens=max_tokens,
                )
                return {
                    "status": 200,
                    "text": raw,
                    "retry_after": None,
                    "_parsed": result,
                    "_meta": {
                        "model": resp.model,
                        "total_input": total_input,
                        "total_output": total_output,
                        "latency_ms": latency_ms,
                        "max_tokens": max_tokens,
                    },
                }
            except ValueError as e:
                last_exc = e
                _log.warning("complete_json 第 %d 次解析失败，重试: %s", attempt + 1, raw[:50])

        # 3 次 JSON 解析全失败 → 直接抛
        if resp is not None:
            latency_ms = int((time.monotonic() - t0) * 1000)
            _log_token_usage(
                provider="openai",
                model=resp.model,
                call_type="complete_json",
                input_tokens=total_input,
                output_tokens=total_output,
                latency_ms=latency_ms,
                max_tokens=max_tokens,
            )
        raise last_exc  # type: ignore[misc]

    # ─────────────────── 公共接口 ───────────────────

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
    ) -> LLMResponse:
        t0 = time.monotonic()
        # cacheable_system_prefix 对 OpenAI 无意义，忽略
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

        gate = self._gate or await _get_gate()

        async def do_req() -> dict:
            return await self._do_request_complete(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        result = await gate.run_with_retry(priority=priority, do_request=do_req)
        resp = result["resp"]
        latency_ms = int((time.monotonic() - t0) * 1000)
        choice = resp.choices[0]
        llm_resp = LLMResponse(
            content=_strip_thinking_content(choice.message.content or ""),
            model=resp.model,
            input_tokens=resp.usage.prompt_tokens,
            output_tokens=resp.usage.completion_tokens,
        )
        _log_token_usage(
            provider="openai",
            model=llm_resp.model,
            call_type="complete",
            input_tokens=llm_resp.input_tokens,
            output_tokens=llm_resp.output_tokens,
            latency_ms=latency_ms,
            max_tokens=max_tokens,
        )
        return llm_resp

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
    ) -> dict | list:
        # 自动设 llm_operation ContextVar
        if operation is not None:
            llm_operation.set(operation)
        # expect=list 时自动覆盖 prefill
        if expect is list:
            prefill = "["
        json_system = system + "\n\n请严格返回合法的 JSON，不要包含 markdown 代码块标记。"
        messages = [
            {"role": "system", "content": json_system},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": prefill},
        ]

        gate = self._gate or await _get_gate()

        async def do_req() -> dict:
            return await self._do_request_json(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                prefill=prefill,
            )

        result = await gate.run_with_retry(priority=priority, do_request=do_req)
        return result["_parsed"]
