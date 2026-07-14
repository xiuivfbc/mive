"""语言提示工具。

user_language ContextVar 由 API 入口 set，get_lang_hint() 返回对应语言的输出指令。
"""

from contextvars import ContextVar

# 当前用户语言偏好，由 API 入口 set，services 通过 get_lang_hint() 读取
user_language: ContextVar[str] = ContextVar("user_language", default="zh-CN")

_LANG_HINTS: dict[str, str] = {
    "zh-CN": "\n请使用简体中文回答。",
    "zh-TW": "\n請使用繁體中文回答。",
    "en": "\nRespond in English.",
    "ja": "\n必ず日本語で回答してください。",
    "ko": "\n반드시 한국어로 응답하세요.",
}


def get_lang_hint() -> str:
    """返回当前用户语言对应的输出指令。"""
    return _LANG_HINTS.get(user_language.get("zh-CN"), "")
