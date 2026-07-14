"""
LLM 集成测试 conftest。
- 覆盖父级 setup_db fixture（LLM 测试不需要数据库）
- 提供 llm / wiki_content 两个 session 级 fixture
- LLM 配置直接从项目 .env 读取（通过 src.config.Settings）
"""

from pathlib import Path

import pytest
import pytest_asyncio


# ── 屏蔽父级 DB setup，LLM 测试不依赖数据库 ────────────────────────────────
@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    yield


# ── LLM provider fixture ─────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def llm():
    from src.config import Settings
    from src.llm.factory import create_llm

    s = Settings()
    api_key = s.llm_api_key
    if not api_key or s.llm_provider == "mock":
        pytest.skip("LLM_API_KEY 未配置或使用 mock，跳过 LLM 集成测试")
    if not s.llm_model:
        pytest.skip("LLM_MODEL 未配置，跳过 LLM 集成测试")
    return create_llm(
        s.llm_provider,
        api_key,
        model=s.llm_model,
        base_url=s.llm_base_url or None,
    )


# ── Wiki 素材 fixture ────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def wiki_content():
    path = Path(__file__).parent.parent / "fixtures" / "wiki_filtered.txt"
    return path.read_text(encoding="utf-8")
