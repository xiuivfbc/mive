"""事件领域规则：severity 枚举。"""

from enum import StrEnum


class ImpactSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
