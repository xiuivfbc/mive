"""领域枚举。消除散布在代码中的魔法字符串。"""

from enum import StrEnum


class EventStatus(StrEnum):
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class EventType(StrEnum):
    USER_INJECTED = "user_injected"
    AI_DETECTED = "ai_detected"
    DAILY_ROUTINE = "daily_routine"


class RelationStatus(StrEnum):
    ACTIVE = "active"
    TERMINATED = "terminated"
