"""世界创建流程专用调试日志。

所有关键步骤写入同一个文件 logs/world_creation_debug.log，
中文标注业务阶段，便于端到端排查。
"""

import logging
import logging.handlers
import os

_wcd = logging.getLogger("world_creation_debug")
_wcd.setLevel(logging.DEBUG)
if not _wcd.handlers:
    _log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(_log_dir, exist_ok=True)
    _handler = logging.handlers.RotatingFileHandler(
        os.path.join(_log_dir, "world_creation_debug.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    _handler.setFormatter(
        logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    _wcd.addHandler(_handler)
    _wcd.propagate = False


def wcd(msg: str) -> None:
    """写一条世界创建调试日志。"""
    _wcd.debug(msg)
