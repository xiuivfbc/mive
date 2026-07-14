import logging

from .anthropic_provider import AnthropicProvider
from .base import LLMProvider
from .mock_provider import MockLLMProvider
from .openai_provider import OpenAIProvider
from .rate_limit_gate import RateLimitGate

logger = logging.getLogger(__name__)

# OpenAI 兼容 API 的 base_url 映射（国产 LLM 加这里就行）
OPENAI_COMPATIBLE_PROVIDERS: dict[str, str] = {
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "kimi": "https://api.moonshot.cn/v1",
    "mimo": "https://token-plan-cn.xiaomimimo.com/v1",
}

# 支持 Anthropic 兼容端点的 provider → Anthropic 格式 base_url
# 优先走 Anthropic SDK（支持 prompt cache），不走 OpenAI 兼容
ANTHROPIC_COMPATIBLE_PROVIDERS: dict[str, str] = {
    "mimo": "https://token-plan-cn.xiaomimimo.com/anthropic",
    "deepseek": "https://api.deepseek.com/anthropic",
    "agnes": "https://apihub.agnes-ai.com/v1",
}

# 模型优选顺序：越靠前越优先
_ANTHROPIC_PRIORITY = [
    "claude-sonnet-4",
    "claude-sonnet-3-7",
    "claude-sonnet-3-5",
    "claude-sonnet-3",
    "claude-haiku-4",
    "claude-haiku-3-5",
    "claude-haiku-3",
    "claude-opus-4",
    "claude-opus-3",
]
_OPENAI_PRIORITY = [
    "gpt-4o",
    "gpt-4-turbo",
    "gpt-4",
    "gpt-3.5-turbo",
    "o3",
    "o1",
]
# OpenAI 模型列表里需要排除的非文本模型
_OPENAI_EXCLUDE = ("embed", "whisper", "dall", "tts", "realtime", "search")


def _pick_best(model_ids: list[str], priority_keywords: list[str]) -> str | None:
    def score(mid: str) -> tuple[int, str]:
        lower = mid.lower()
        for i, kw in enumerate(priority_keywords):
            if kw in lower:
                return (i, mid)
        return (len(priority_keywords), mid)

    candidates = sorted(model_ids, key=score)
    return candidates[0] if candidates else None


async def _list_anthropic_models(api_key: str) -> list[str]:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)
    try:
        page = await client.models.list(limit=20)
        return [m.id for m in page.data]
    except Exception as e:
        logger.warning("无法获取 Anthropic 模型列表: %s", e)
        return []


async def _list_openai_models(api_key: str, base_url: str | None) -> list[str]:
    import openai

    client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=0)
    try:
        page = await client.models.list()
        return [m.id for m in page.data if not any(kw in m.id.lower() for kw in _OPENAI_EXCLUDE)]
    except Exception as e:
        logger.warning("无法获取 OpenAI 兼容模型列表: %s", e)
        return []


def _resolve_provider_config(
    provider: str,
    base_url: str | None,
    api_format: str | None,
) -> tuple[str | None, str | None]:
    """解析 provider 的有效 api_format 和 base_url。

    - api_format：用户显式传入 > provider 类型推导（anthropic/openai compatible 表）
    - base_url：用户显式传入 > provider 默认值（查表，未命中则为 None 即官方 API）
    - 对于 anthropic / openai 这两个官方 provider，未覆盖时 api_format 由 provider 名决定
    - 当 api_format 显式覆盖了 provider 默认格式时（如 deepseek + api_format=openai），
      base_url 也从对应格式的表里查，确保格式与端点匹配
    """
    # 推导默认 api_format 和 base_url
    default_format: str | None = None
    default_url: str | None = None

    # 如果 api_format 显式指定，从对应表查默认 base_url；否则按 provider 类型推导
    if api_format:
        # 显式 api_format → 只从对应格式的表查默认 URL
        effective_format = api_format
        if base_url:
            effective_url = base_url
        elif api_format == "anthropic":
            effective_url = ANTHROPIC_COMPATIBLE_PROVIDERS.get(provider)
        elif api_format == "openai":
            effective_url = OPENAI_COMPATIBLE_PROVIDERS.get(provider)
        else:
            effective_url = None
        return effective_format, effective_url

    # api_format 未指定 → 按 provider 类型推导
    if provider in ANTHROPIC_COMPATIBLE_PROVIDERS:
        default_format = "anthropic"
        default_url = ANTHROPIC_COMPATIBLE_PROVIDERS[provider]
    elif provider in OPENAI_COMPATIBLE_PROVIDERS:
        default_format = "openai"
        default_url = OPENAI_COMPATIBLE_PROVIDERS[provider]
    elif provider == "anthropic":
        default_format = "anthropic"
    elif provider == "openai":
        default_format = "openai"

    effective_format = default_format
    effective_url = base_url or default_url

    return effective_format, effective_url


def create_llm(
    provider: str,
    api_key: str,
    model: str | None = None,
    base_url: str | None = None,
    max_retries: int = 0,
    gate: RateLimitGate | None = None,
    api_format: str | None = None,
) -> LLMProvider:
    """创建 LLM provider 实例。

    model 和 api_key 对所有非 mock provider 均为必填。
    base_url / api_format 填了会覆盖 provider 内置默认值。
    """
    match provider:
        case "mock":
            return MockLLMProvider(gate=gate)
        case "custom":
            if not base_url:
                raise ValueError("Custom provider requires base_url")
            if not model:
                raise ValueError("Custom provider requires model")
            if not api_format:
                raise ValueError("Custom provider requires api_format ('anthropic' or 'openai')")
            effective_format = api_format
            effective_url = base_url
        case _:
            if not model:
                raise ValueError(f"Provider '{provider}' requires model")
            effective_format, effective_url = _resolve_provider_config(
                provider, base_url, api_format
            )
            if not effective_format:
                raise ValueError(
                    f"Unknown LLM provider: {provider}. "
                    f"Supported: anthropic, openai, custom, "
                    f"{', '.join(OPENAI_COMPATIBLE_PROVIDERS)}"
                )

    if effective_format == "anthropic":
        return AnthropicProvider(
            api_key,
            model,
            effective_url,
            max_retries=max_retries,
            gate=gate,
        )
    elif effective_format == "openai":
        return OpenAIProvider(
            api_key,
            model,
            effective_url,
            max_retries=max_retries,
            gate=gate,
        )
    else:
        raise ValueError(
            f"Unknown api_format: {effective_format}. Must be 'anthropic' or 'openai'."
        )


async def create_llm_auto(
    provider: str,
    api_key: str,
    model: str | None = None,
    base_url: str | None = None,
    max_retries: int = 2,
    gate: RateLimitGate | None = None,
    api_format: str | None = None,
) -> LLMProvider:
    """create_llm 的异步版本，model 为空时自动探测并选择最优模型。

    自动探测失败时抛出 ValueError（不再回退到硬编码默认模型）。
    """
    if provider == "mock":
        return create_llm(
            provider, api_key, model, base_url, max_retries, gate=gate, api_format=api_format
        )
    if model:
        return create_llm(
            provider, api_key, model, base_url, max_retries, gate=gate, api_format=api_format
        )
    # custom provider 必须指定 model，不走自动探测
    if provider == "custom":
        return create_llm(
            provider, api_key, model, base_url, max_retries, gate=gate, api_format=api_format
        )

    # 解析有效的 api_format 和 base_url，用于模型列表探测
    effective_format, effective_url = _resolve_provider_config(provider, base_url, api_format)

    selected: str | None = None
    if effective_format == "anthropic":
        models = await _list_anthropic_models(api_key)
        selected = _pick_best(models, _ANTHROPIC_PRIORITY)
    elif effective_format == "openai":
        models = await _list_openai_models(api_key, effective_url)
        selected = _pick_best(models, _OPENAI_PRIORITY)

    if selected:
        logger.info("LLM 模型自动选择: provider=%s model=%s", provider, selected)
    else:
        raise ValueError(f"无法为 provider '{provider}' 自动探测可用模型，请显式指定 model。")

    return create_llm(
        provider, api_key, selected, base_url, max_retries, gate=gate, api_format=api_format
    )
