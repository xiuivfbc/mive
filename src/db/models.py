import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    """返回无时区的 UTC 时间（等价于已弃用的 datetime.utcnow()）。"""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class M1World(Base):
    __tablename__ = "m1_worlds"
    __table_args__ = (Index("idx_m1_worlds_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID, nullable=False)
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_info: Mapped[dict | None] = mapped_column(JSONB)
    world_doc: Mapped[dict] = mapped_column(JSONB, nullable=False)
    element_summary: Mapped[dict | None] = mapped_column(JSONB)
    character_summary: Mapped[dict | None] = mapped_column(JSONB)
    relationship_summary: Mapped[dict | None] = mapped_column(JSONB)
    world_base_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    # M6 graph alignment
    graph_id: Mapped[str | None] = mapped_column(String(255))
    graph_ontology: Mapped[dict | None] = mapped_column(JSONB)
    graph_status: Mapped[str] = mapped_column(String(20), default="idle")
    graph_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # M14 world user character (use_alter breaks the m1_worlds↔m2_characters circular FK)
    user_character_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID,
        ForeignKey(
            "m2_characters.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_m1worlds_user_character_id",
        ),
        nullable=True,
    )

    # Snapshot reform: tracks mutation count for async snapshot sync
    snapshot_generation: Mapped[int] = mapped_column(default=0, server_default="0")

    # Scale: world creation scale (standard/detailed/deep/all)
    scale: Mapped[str] = mapped_column(String(20), default="standard")


class M2Character(Base):
    __tablename__ = "m2_characters"
    __table_args__ = (Index("idx_m2_characters_world_id", "world_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("m1_worlds.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    portrait_url: Mapped[str | None] = mapped_column(Text)
    profile: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    # M6 graph alignment
    graph_node_uuid: Mapped[str | None] = mapped_column(String(255))
    entity_type: Mapped[str] = mapped_column(String(50), default="character")
    tier: Mapped[str | None] = mapped_column(String(20))


class M2Relation(Base):
    __tablename__ = "m2_relations"
    __table_args__ = (
        Index(
            "uq_m2_relations_active",
            "character_a",
            "character_b",
            "direction",
            unique=True,
            postgresql_where="status = 'active'",
        ),
        Index("idx_m2_relations_world_id", "world_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("m1_worlds.id"), nullable=False)
    character_a: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("m2_characters.id"), nullable=False
    )
    character_b: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("m2_characters.id"), nullable=False
    )
    type: Mapped[str | None] = mapped_column(String(50))
    direction: Mapped[str] = mapped_column(String(20), default="bidirectional")
    description: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="active")
    historical_changes: Mapped[list | None] = mapped_column(JSONB)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    # M6 graph alignment
    graph_edge_uuid: Mapped[str | None] = mapped_column(String(255))


class M2WorldVersion(Base):
    __tablename__ = "m2_world_versions"
    __table_args__ = (Index("idx_m2_world_versions_world_id", "world_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("m1_worlds.id"), nullable=False)
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("m2_world_versions.id")
    )
    created_by: Mapped[str | None] = mapped_column(String(20))
    summary: Mapped[str | None] = mapped_column(String(500))
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    # Snapshot reform: generation number at snapshot creation time
    synced_generation: Mapped[int] = mapped_column(default=0, server_default="0")


class M3Event(Base):
    __tablename__ = "m3_events"
    __table_args__ = (Index("idx_m3_events_status", "world_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("m1_worlds.id"), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(50))
    name: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    is_key_event: Mapped[bool] = mapped_column(Boolean, default=False)
    user_marked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime)


class M4ChatSession(Base):
    __tablename__ = "m4_chat_sessions"
    __table_args__ = (Index("idx_m4_chat_sessions_world_id", "world_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("m1_worlds.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # event | character
    title: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    participants: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    participant_mode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    memories_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Snapshot reform: link session to the world version active when it was created
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID,
        ForeignKey("m2_world_versions.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Memory flush tracking: last sequence at which memories were flushed
    last_flushed_sequence: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Session activity tracking
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Session options: element injection and constraint text
    element_injection_ids: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    constraints: Mapped[str] = mapped_column(String(100), nullable=False, server_default="")


class M4Message(Base):
    __tablename__ = "m4_messages"
    __table_args__ = (
        Index("idx_m4_messages_sender", "sender_id"),
        # Issue 2: unique constraint on (session_id, sequence) prevents duplicate sequences
        Index(
            "uq_m4_messages_session_sequence",
            "session_id",
            "sequence",
            unique=True,
            postgresql_where="session_id IS NOT NULL AND sequence IS NOT NULL",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("m1_worlds.id"), nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("m4_chat_sessions.id", ondelete="CASCADE"), nullable=True
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    sender_type: Mapped[str] = mapped_column(String(20), nullable=False)
    sender_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    real_time: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    is_key_message: Mapped[bool] = mapped_column(Boolean, default=False)
    user_participated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    # Queue system: sequence ordering + idempotency
    sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Message status: normal / hidden / deleted
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="normal")


# ---------------------------------------------------------------------------
# M8: Discord Bridge
# ---------------------------------------------------------------------------


class M8DiscordBinding(Base):
    __tablename__ = "m8_discord_bindings"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("m1_worlds.id"), nullable=False, unique=True
    )
    guild_id: Mapped[str] = mapped_column(Text, nullable=False)
    channel_daily: Mapped[str | None] = mapped_column(Text)
    channel_event: Mapped[str | None] = mapped_column(Text)
    channel_chat: Mapped[str | None] = mapped_column(Text)
    narrator_webhook_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class M8CharacterWebhook(Base):
    __tablename__ = "m8_character_webhooks"
    __table_args__ = (Index("idx_m8_char_webhooks_world", "world_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("m1_worlds.id"), nullable=False)
    character_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("m2_characters.id"), nullable=False, unique=True
    )
    webhook_id: Mapped[str] = mapped_column(Text, nullable=False)
    webhook_url: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# ---------------------------------------------------------------------------
# M20: Matterbridge Bridge
# ---------------------------------------------------------------------------


class M20MatterbridgeBinding(Base):
    __tablename__ = "m20_matterbridge_bindings"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("m1_worlds.id"), nullable=False, unique=True
    )
    api_url: Mapped[str] = mapped_column(Text, nullable=False)
    api_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    api_token_iv: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    config_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class M9User(Base):
    __tablename__ = "m9_users"
    __table_args__ = (
        Index("idx_users_username", "username"),
        Index("idx_users_email", "email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    preferred_language: Mapped[str] = mapped_column(String(10), nullable=False, default="zh-CN")
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class M10ApiKey(Base):
    __tablename__ = "m10_api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("m9_users.id"), nullable=False, unique=True
    )
    provider: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # anthropic/openai/qwen/deepseek/kimi/agnes/custom
    api_format: Mapped[str | None] = mapped_column(
        String(20)
    )  # anthropic/openai — required when provider=custom
    model: Mapped[str | None] = mapped_column(String(100))
    base_url: Mapped[str | None] = mapped_column(String(500))
    rpm: Mapped[int | None] = mapped_column(Integer)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    iv: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class M16WelcomeQuote(Base):
    __tablename__ = "m16_welcome_quotes"
    __table_args__ = (
        Index("idx_m16_quotes_status", "status"),
        Index("idx_m16_quotes_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("m9_users.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'pending'")
    )
    ai_verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class M2CharacterMemory(Base):
    __tablename__ = "m2_character_memories"
    __table_args__ = (
        Index("idx_m2_character_memories_character_id", "character_id"),
        Index("idx_m2_character_memories_world_id", "world_id"),
        Index(
            "idx_m2_character_memories_event_name",
            "character_id",
            "event_name",
            postgresql_where=text("event_name IS NOT NULL"),
        ),
        CheckConstraint(
            "dissemination IS NULL OR (dissemination >= 0 AND dissemination <= 1)",
            name="ck_m2_character_memories_dissemination_range",
        ),
        CheckConstraint(
            "info_amount IS NULL OR (info_amount >= 0 AND info_amount <= 1)",
            name="ck_m2_memories_info_amount_range",
        ),
        CheckConstraint(
            "hop_count >= 0 AND hop_count <= 2",
            name="ck_m2_memories_hop_count_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    character_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("m2_characters.id", ondelete="CASCADE"), nullable=False
    )
    world_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("m1_worlds.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("m4_chat_sessions.id", ondelete="SET NULL"), nullable=True
    )
    memory_type: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # 'short_term' | 'long_term'
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    # Memory propagation columns
    visible_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    origin_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("m3_events.id", ondelete="SET NULL"), nullable=True
    )
    is_hearsay: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    propagated_from: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("m2_characters.id", ondelete="SET NULL"), nullable=True
    )
    involved_characters: Mapped[list | None] = mapped_column(ARRAY(UUID), nullable=True)
    propagation_meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Multi-hop propagation fields
    hop_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    info_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_character_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID,
        ForeignKey("m2_characters.id", ondelete="SET NULL"),
        nullable=True,
    )
    memory_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Structured long-term memory fields (P0)
    event_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    perspective_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    reflection: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Awareness tags (P1): ["heard"] | ["integrated"] | None
    tags: Mapped[list | None] = mapped_column(ARRAY(String(20)), nullable=True)

    # Element event dissemination (P1): 0.0 ~ 1.0
    dissemination: Mapped[float | None] = mapped_column(nullable=True)

    # Short-term memory category (V2): "trivial" | "private" | "major"
    memory_category: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Short-term memory optional reflection (V2)
    short_term_reflection: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Note: 'embedding' column (vector(1024)) exists in DB for short-term memory
    # vector search, but is managed via raw SQL in CharacterMemoryRepository
    # (same pattern as m25_element_embeddings.embedding).


# ---------------------------------------------------------------------------
# M26: World Event Index (V2)
# ---------------------------------------------------------------------------


class M26EventIndex(Base):
    __tablename__ = "m26_event_index"
    __table_args__ = (
        Index("idx_m26_event_index_world_id", "world_id"),
        CheckConstraint(
            "dissemination >= 0 AND dissemination <= 1",
            name="ck_m26_event_index_dissemination_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("m1_worlds.id", ondelete="CASCADE"), nullable=False
    )
    event_name: Mapped[str] = mapped_column(String(255), nullable=False)
    brief: Mapped[str] = mapped_column(Text, nullable=False)
    dissemination: Mapped[float] = mapped_column(nullable=False, default=0.5)
    core_participants: Mapped[list | None] = mapped_column(ARRAY(UUID), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    # Multi-hop: effective world day (NULL = private event, not publicly visible)
    effective_day: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ---------------------------------------------------------------------------
# M25: Element Embeddings (pgvector)
# ---------------------------------------------------------------------------


class M25ElementEmbedding(Base):
    __tablename__ = "m25_element_embeddings"
    __table_args__ = (
        Index("idx_m25_world_id", "world_id"),
        Index("idx_m25_world_elem", "world_id", "element_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("m1_worlds.id", ondelete="CASCADE"), nullable=False
    )
    element_id: Mapped[str] = mapped_column(String(128), nullable=False)
    element_type: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str | None] = mapped_column(String(16))
    tier: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    search_text: Mapped[str] = mapped_column(Text, nullable=False)
    # tsv and embedding columns are managed via raw SQL (TSVECTOR and vector types)
    # They are present in the DB but not mapped in the ORM to avoid import issues
    # with pgvector types; the repository handles them directly.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class M23GuideContent(Base):
    __tablename__ = "m23_guide_content"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    all_content: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    recent_content: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    recent_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    context_help: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


# ---------------------------------------------------------------------------
# M21: Admin Config (key-value settings store)
# ---------------------------------------------------------------------------


class M21AdminConfig(Base):
    __tablename__ = "m21_admin_config"
    __table_args__ = (UniqueConstraint("group_name", "key", name="uq_m21_admin_config_group_key"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID, primary_key=True, server_default=text("gen_random_uuid()")
    )
    group_name: Mapped[str] = mapped_column(String(32), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    plain_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    iv: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
