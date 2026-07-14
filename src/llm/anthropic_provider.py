import asyncio
import logging as _logging
import time

import anthropic

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

_THINKING_DISABLED = {"type": "disabled"}

_log = _logging.getLogger(__name__)


def _is_quota_error(exc: anthropic.APIStatusError) -> bool:
    msg = str(exc).lower()
    return exc.status_code in (402, 429) and any(
        kw in msg for kw in ("credit", "quota", "billing", "balance", "insufficient")
    )


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


def _get_retry_after(exc: anthropic.RateLimitError) -> float | None:
    """从 429 异常的响应头里提取 Retry-After 秒数。"""
    try:
        headers = exc.response.headers if exc.response else {}
        val = headers.get("retry-after")
        if val:
            return float(val)
    except Exception:
        pass
    return None


class AnthropicProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        max_retries: int = 0,
        gate: RateLimitGate | None = None,
    ):
        self.client = anthropic.AsyncAnthropic(
            api_key=api_key, base_url=base_url, max_retries=max_retries
        )
        self.model = model
        self._gate = gate

    # ─────────────────── _do_request（HTTP 层） ───────────────────

    async def _do_request_complete(
        self,
        *,
        system_param,
        prompt: str,
        temperature: float,
        max_tokens: int,
        thinking: dict | None,
    ) -> dict:
        """发一次 complete 请求，返回 {status, resp, retry_after}。
        quota 错误直接抛出，不经 gate 处理。
        """
        try:
            _kwargs: dict = dict(
                model=self.model,
                system=system_param,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if thinking is not None:
                _kwargs["thinking"] = thinking
            resp = await self.client.messages.create(**_kwargs)
            return {"status": 200, "resp": resp, "retry_after": None}
        except anthropic.APIStatusError as e:
            if _is_quota_error(e):
                raise LLMQuotaExhaustedError("anthropic", self.model) from e
            if e.status_code == 421:
                _log.warning("complete 421 内容审核拦截")
                raise
            retry_after = None
            if isinstance(e, anthropic.RateLimitError):
                retry_after = _get_retry_after(e)
            return {"status": e.status_code, "resp": None, "retry_after": retry_after}
        except (TimeoutError, ConnectionError, OSError, anthropic.APIConnectionError) as e:
            _log.warning("complete 网络错误: %s", e)
            return {"status": 0, "resp": None, "retry_after": None}

    async def _do_request_json(
        self,
        *,
        system_param,
        prompt: str,
        temperature: float,
        max_tokens: int,
        prefill: str,
        thinking: dict | None,
    ) -> dict:
        """发一次 complete_json 请求（含 3 次 JSON 解析重试），返回 {status, text, retry_after}。"""
        last_exc: Exception | None = None
        total_input = total_output = total_cache_read = total_cache_write = 0
        t0 = time.monotonic()
        resp = None
        for attempt in range(3):
            try:
                _kwargs: dict = dict(
                    model=self.model,
                    system=system_param,
                    messages=[
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": prefill},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if thinking is not None:
                    _kwargs["thinking"] = thinking
                resp = await self.client.messages.create(**_kwargs)
            except anthropic.APIStatusError as e:
                if _is_quota_error(e):
                    raise LLMQuotaExhaustedError("anthropic", self.model) from e
                if e.status_code == 421:
                    _log.warning("complete_json 421 内容审核拦截")
                    raise
                retry_after = None
                if isinstance(e, anthropic.RateLimitError):
                    retry_after = _get_retry_after(e)
                return {
                    "status": e.status_code,
                    "text": "",
                    "retry_after": retry_after,
                    "_meta": None,
                }
            except (TimeoutError, ConnectionError, OSError, anthropic.APIConnectionError) as e:
                _log.warning("complete_json 网络错误: %s", e)
                return {"status": 0, "text": "", "retry_after": None, "_meta": None}

            total_input += resp.usage.input_tokens
            total_output += resp.usage.output_tokens
            total_cache_read += getattr(resp.usage, "cache_read_input_tokens", 0) or 0
            total_cache_write += getattr(resp.usage, "cache_creation_input_tokens", 0) or 0

            if resp.stop_reason == "repetition_truncation":
                _log.warning("complete_json 第 %d 次触发重复截断，重试", attempt + 1)
                last_exc = ValueError("模型触发重复截断")
                continue

            resp_text = next((b.text for b in resp.content if hasattr(b, "text")), "")
            if not resp_text.strip():
                _log.warning("complete_json 第 %d 次返回空响应，重试", attempt + 1)
                last_exc = ValueError("模型返回空响应")
                continue

            stripped = resp_text.strip()
            # 兼容 Anthropic 兼容接口（如 Mimo）回显 prefill；裸数组响应直接用不拼前缀
            if (prefill and stripped.startswith(prefill)) or stripped.startswith("["):
                raw = stripped
            else:
                raw = prefill + resp_text

            try:
                result = extract_json(raw)
                latency_ms = int((time.monotonic() - t0) * 1000)
                _log_token_usage(
                    provider="anthropic",
                    model=resp.model,
                    call_type="complete_json",
                    input_tokens=total_input,
                    output_tokens=total_output,
                    cache_read_tokens=total_cache_read,
                    cache_write_tokens=total_cache_write,
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
                        "total_cache_read": total_cache_read,
                        "total_cache_write": total_cache_write,
                        "latency_ms": latency_ms,
                        "max_tokens": max_tokens,
                    },
                }
            except ValueError as e:
                last_exc = e
                _log.warning("complete_json 第 %d 次解析失败，重试: %s", attempt + 1, raw[:80])

        # 3 次 JSON 解析全失败 → 直接抛（JSON 解析问题重发 HTTP 也无意义）
        if resp is not None:
            latency_ms = int((time.monotonic() - t0) * 1000)
            _log_token_usage(
                provider="anthropic",
                model=resp.model,
                call_type="complete_json",
                input_tokens=total_input,
                output_tokens=total_output,
                cache_read_tokens=total_cache_read,
                cache_write_tokens=total_cache_write,
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
        thinking: dict | None = _THINKING_DISABLED,
        priority: int = LLMPriority.BACKGROUND,
    ) -> LLMResponse:
        t0 = time.monotonic()
        if cacheable_system_prefix is not None:
            system_param = [
                {
                    "type": "text",
                    "text": cacheable_system_prefix,
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": system,
                },
            ]
        else:
            system_param = system

        gate = self._gate or await _get_gate()

        async def do_req() -> dict:
            r = await self._do_request_complete(
                system_param=system_param,
                prompt=prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                thinking=thinking,
            )
            return r

        result = await gate.run_with_retry(priority=priority, do_request=do_req)
        resp = result["resp"]
        latency_ms = int((time.monotonic() - t0) * 1000)
        text = next((b.text for b in resp.content if hasattr(b, "text")), "")
        llm_resp = LLMResponse(
            content=text,
            model=resp.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )
        _log_token_usage(
            provider="anthropic",
            model=llm_resp.model,
            call_type="complete",
            input_tokens=llm_resp.input_tokens,
            output_tokens=llm_resp.output_tokens,
            cache_read_tokens=getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
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
        thinking: dict | None = _THINKING_DISABLED,
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
        json_suffix = "\n\n请严格返回合法的 JSON，不要包含 markdown 代码块标记。"
        if cacheable_system_prefix is not None:
            system_param = [
                {
                    "type": "text",
                    "text": cacheable_system_prefix,
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": system + json_suffix,
                },
            ]
        else:
            system_param = system + json_suffix

        gate = self._gate or await _get_gate()

        async def do_req() -> dict:
            return await self._do_request_json(
                system_param=system_param,
                prompt=prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                prefill=prefill,
                thinking=thinking,
            )

        result = await gate.run_with_retry(priority=priority, do_request=do_req)
        return result["_parsed"]
