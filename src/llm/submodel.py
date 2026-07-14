"""副模型（SUB_LLM）基础设施。

判断/分类类的"简单调用"切到更便宜的副模型，主模型只做创作类"复杂调用"。

核心是**回退链**：
- 副模型未配置（空 key）→ 直接用主模型；
- 配了但调用失败（连接/鉴权/超时）→ catch 后回退主模型重试一次。

副模型走**独立或共享的 RateLimitGate**（主副共用同一 API key 时共享，避免合计超限）。
"""

from __future__ import annotations

import logging

from .base import LLMProvider, LLMResponse
from .rate_limit_gate import RateLimitGate

logger = logging.getLogger(__name__)


class FallbackLLMProvider(LLMProvider):
    """包装一个主（副模型）+ 备（主模型）provider。

    每次调用先试 primary（副模型）；任何异常 → catch 后回退 fallback（主模型）
    重试一次。两者都失败时异常向上传播，由调用方决定降级。

    fallback_count 用于监控回退率——过高说明副模型配置有问题。
    """

    def __init__(self, primary: LLMProvider, fallback: LLMProvider) -> None:
        self.primary = primary
        self.fallback = fallback
        self.fallback_count = 0

    async def complete(self, system: str, prompt: str, **kwargs) -> LLMResponse:
        try:
            return await self.primary.complete(system, prompt, **kwargs)
        except Exception as e:
            self.fallback_count += 1
            logger.warning(
                "[sub_llm] complete 副模型失败，回退主模型重试: %s (累计回退 %d 次)",
                e,
                self.fallback_count,
            )
            return await self.fallback.complete(system, prompt, **kwargs)

    async def complete_json(self, system: str, prompt: str, **kwargs) -> dict | list:
        try:
            return await self.primary.complete_json(system, prompt, **kwargs)
        except Exception as e:
            self.fallback_count += 1
            logger.warning(
                "[sub_llm] complete_json 副模型失败，回退主模型重试: %s (累计回退 %d 次)",
                e,
                self.fallback_count,
            )
            return await self.fallback.complete_json(system, prompt, **kwargs)


async def build_sub_llm(
    *,
    main_llm: LLMProvider | None,
    api_key: str,
    base_url: str,
    model: str,
    provider: str,
    rpm: int = 0,
    max_inflight: int = 5,
    gate: RateLimitGate | None = None,
    api_format: str | None = None,
) -> LLMProvider | None:
    """构建副模型客户端（含回退链）。

    - main_llm 为 None（主模型未配置）→ 返回 None；
    - api_key 为空（副模型未启用）→ 返回 main_llm（短路）；
    - 配置齐全 → 返回 FallbackLLMProvider(副模型, main_llm)。

    gate 参数：传入时直接使用（主副共享同一 gate），不传时内部新建。
    """
    if main_llm is None:
        return None
    if not api_key:
        return main_llm

    from .factory import create_llm_auto

    sub_gate = gate or RateLimitGate(rpm=rpm or None, max_inflight=max_inflight)
    try:
        sub = await create_llm_auto(
            provider=provider,
            api_key=api_key,
            model=model or None,
            base_url=base_url or None,
            max_retries=0,
            gate=sub_gate,
            api_format=api_format,
        )
    except Exception as e:
        logger.warning("[sub_llm] 副模型初始化失败，回落主模型: %s", e)
        return main_llm
    return FallbackLLMProvider(primary=sub, fallback=main_llm)
