import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from src.models.scale import DEFAULT_SCALE

_SOURCE_BOUNDARY_RE = re.compile(r"---SOURCE_BOUNDARY:\s*(.+?)---")


class Element(BaseModel):
    id: str
    category: str
    name: str
    brief: str
    detail: str


class WorldSource(BaseModel):
    title: str | None = None
    author: str | None = None
    type: str | None = None
    references: list[str] = Field(default_factory=list)
    input_text: str | None = None
    detected_work_type: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    sub_source_urls: list[str] = Field(default_factory=list)
    wiki_text: str | None = None
    wiki_characters: str | None = None
    wiki_plot: str | None = None
    wiki_world_setting: str | None = None
    plot_summary: str | None = None  # 世界简介：用户看，不给 AI 看
    common_sense: str | None = None
    core_conflict: str | None = None  # 核心冲突/主题
    tone_and_atmosphere: str | None = None  # 整体基调/氛围
    plot_development: str | None = None  # 情节发展：默认空，用户手填，非空时注入上下文

    @field_validator("common_sense", mode="before")
    @classmethod
    def _coerce_common_sense(cls, v: object) -> object:
        """兼容旧数据：list[str] → 换行拼接为 str。"""
        if isinstance(v, list):
            return "\n".join(str(item) for item in v if item) or None
        return v

    @model_validator(mode="after")
    def _extract_sub_source_urls(self) -> "WorldSource":
        """从 wiki 文本中的 ---SOURCE_BOUNDARY: <url>--- 标记提取子链 URL。"""
        if self.sub_source_urls:
            return self
        seen: set[str] = set()
        urls: list[str] = []
        for field in (self.wiki_characters, self.wiki_world_setting):
            if not field:
                continue
            for m in _SOURCE_BOUNDARY_RE.finditer(field):
                url = m.group(1).strip()
                if url and url not in seen:
                    seen.add(url)
                    urls.append(url)
        if urls:
            self.sub_source_urls = urls
        return self


class WorldMeta(BaseModel):
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    last_analyzed_at: datetime | None = None


class WorldDoc(BaseModel):
    world_id: str
    world_base_id: str | None = None
    version: str = "1.0"
    source: WorldSource
    meta: WorldMeta
    elements: list[Element]

    # populated by list_by_user for lightweight list view
    element_count: int = 0
    character_count: int = 0
    relationship_count: int = 0

    # M6 graph alignment fields (populated from M1World row, not world_doc JSONB)
    graph_id: str | None = None
    graph_ontology: dict | None = None
    graph_status: str = "idle"
    graph_updated_at: datetime | None = None

    # M15 world user character (populated from M1World row, not world_doc JSONB)
    user_character_id: str | None = None

    # M17 legal protection (populated from M1World row, not world_doc JSONB)
    is_banned: bool = False

    # Scale (populated from M1World row, not world_doc JSONB)
    scale: str = "standard"

    # Transient field: extraction 阶段产出的角色候选（不持久化到 DB）
    char_candidates: list[dict] = Field(default_factory=list, exclude=True)


class CheckWikiRequest(BaseModel):
    title: str
    author: str | None = None
    work_language: str | None = None
    scale: str = DEFAULT_SCALE  # 规模，用于快速路径门控判断


class WikiPreviewRequest(BaseModel):
    url: str
    title: str | None = None
    author: str | None = None


class CreateWorldRequest(BaseModel):
    title: str
    author: str | None = None
    type: str | None = None
    description: str | None = None
    urls: list[str] = Field(default_factory=list)
    scale: str = DEFAULT_SCALE
    detected_work_type: str | None = None
    confirmed_wiki_url: str | None = None
    confirmed_wiki_raw_content: str | None = None
    fast_path: bool = False  # 预检通过后前端标记，跳过 wiki 直接用 LLM 知识生成
    fast_path_characters: list[str] = Field(default_factory=list)
    model_config = {"extra": "ignore"}


class CreateFromTemplateRequest(BaseModel):
    template_id: str
    scale: str = DEFAULT_SCALE


class UpdateElementRequest(BaseModel):
    name: str | None = None
    category: str | None = None
    brief: str
    detail: str


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
