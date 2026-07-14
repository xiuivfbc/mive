from dataclasses import dataclass


@dataclass
class ScaleConfig:
    label: str
    element_range: tuple[int, int]
    char_range: tuple[int, int]
    max_tokens: int
    # 元素详情生成阶段传入 wiki 的最大字符数（超过截断）
    wiki_detail_threshold: int

    @property
    def char_target(self) -> int:
        """角色目标数量（等于 char_range 下限）。"""
        return self.char_range[0]


SCALES: dict[str, ScaleConfig] = {
    "standard": ScaleConfig("标准", (8, 15), (5, 10), 8192, 8000),
    "detailed": ScaleConfig("详尽", (15, 25), (10, 30), 8192, 15000),
    "deep": ScaleConfig("深度", (25, 40), (30, 50), 16384, 30000),
    "all": ScaleConfig("全量", (50, 80), (0, 0), 16384, 50000),
}

DEFAULT_SCALE = "standard"
