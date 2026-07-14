"""时钟领域规则：时长解析。"""

from datetime import timedelta


def parse_duration(duration: str) -> timedelta:
    """解析时长字符串，如 '1h', '30m', '2d'。"""
    duration = duration.strip()
    if duration.endswith("m"):
        return timedelta(minutes=int(duration[:-1]))
    if duration.endswith("h"):
        return timedelta(hours=int(duration[:-1]))
    if duration.endswith("d"):
        return timedelta(days=int(duration[:-1]))
    raise ValueError(f"Invalid duration format: {duration}")
