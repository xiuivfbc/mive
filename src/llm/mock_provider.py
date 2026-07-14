"""开发用 Mock LLM Provider。按 llm_operation + system 关键词分派，sleep 1.5s 模拟延迟。"""

import asyncio
import re

from .base import LLMProvider, LLMResponse, llm_operation


def _extract_bracket_name(prompt: str) -> str | None:
    """从 prompt 中提取 「名字」 格式的角色名。"""
    m = re.search(r"「([^」]{1,30})」", prompt)
    return m.group(1) if m else None


class MockLLMProvider(LLMProvider):
    def __init__(self, gate=None, **_ignored) -> None:
        self._gate = None  # gate 参数接受但忽略

    async def complete(
        self,
        system: str,
        prompt: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        cacheable_system_prefix: str | None = None,
        thinking: dict | None = None,
        priority: int = 2,
    ) -> LLMResponse:
        await asyncio.sleep(1.5)
        return LLMResponse(
            content="这是一段模拟文本回复，用于快速验证流程。",
            model="mock",
            input_tokens=100,
            output_tokens=30,
        )

    async def complete_json(
        self,
        system: str,
        prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        prefill: str = "{",
        cacheable_system_prefix: str | None = None,
        thinking: dict | None = None,
        priority: int = 2,
        operation: str | None = None,
        expect: type[dict] | type[list] = dict,
    ) -> dict | list:
        await asyncio.sleep(1.5)
        if operation is not None:
            llm_operation.set(operation)
        op = llm_operation.get()
        return self._dispatch(op, system, prompt)

    # ──────────────────────────────────────────────────────────────────────────
    # Dispatch

    def _dispatch(self, op: str, system: str, prompt: str) -> dict | list:
        match op:
            case "元素提取" | "元素补充提取":
                return [
                    {
                        "category": "人物",
                        "name": "主角",
                        "brief": "故事核心人物",
                        "detail": "有独特使命与背景的主人公，在世界中扮演关键角色。",
                        "importance": "core",
                    },
                    {
                        "category": "地点",
                        "name": "主城",
                        "brief": "故事主要场景",
                        "detail": "繁华的核心城市，各方势力交汇处，是大多数事件的起点。",
                        "importance": "supporting",
                    },
                    {
                        "category": "势力",
                        "name": "主要组织",
                        "brief": "核心势力",
                        "detail": "掌控地区秩序的重要机构，旗下成员众多，影响深远。",
                        "importance": "supporting",
                    },
                ]
            case "世界识别":
                return {"type": "single", "work_type": "小说", "search_query": "mock"}
            case "Wiki 链接筛选":
                return {"chosen": None, "reason": "mock 模式，跳过链接筛选"}
            case "角色生成":
                return self._dispatch_generation(system, prompt)
            case "事件推演":
                return self._dispatch_event(system, prompt)
            case "角色聊天":
                return self._dispatch_chat(system, prompt)
            case "角色去重":
                return {"duplicates": []}
            case "图谱解析":
                return {"operations": []}
            case _:
                return self._dispatch_by_system(system)

    def _dispatch_generation(self, system: str, prompt: str) -> dict | list:
        # 关系质量审核（reflection）
        if "关系质量审核员" in system:
            return {
                "valid": True,
                "relation": {
                    "type": "相关",
                    "description": "两人在故事中存在关联。",
                    "direction": "bidirectional",
                },
            }
        # 关系判断（core pairs / non-core pairs）
        if "has_relation" in system:
            return {"has_relation": False, "relation": None}
        # 角色档案生成
        name = _extract_bracket_name(prompt) or "模拟角色"
        return {
            "name": name,
            "profile": {
                "brief": f"{name}是故事中的重要角色。",
                "detail": (
                    f"{name}拥有独特的过去与使命，在世界中占据关键位置，其行动影响着故事走向。"
                ),
            },
        }

    def _dispatch_event(self, system: str, prompt: str) -> dict | list:
        # Planner
        if "event_title" in system and "scenes" in system:
            return {
                "event_title": "模拟事件",
                "scenes": [
                    {
                        "scene_id": 1,
                        "location": "主城广场",
                        "atmosphere": "气氛紧张",
                        "factions": ["相关人员"],
                        "purpose": "讨论应对方案",
                    }
                ],
            }
        # Orchestrator（场景导演）
        if "场景导演" in system or ("participants" in system and "first_speaker" in system):
            return {"participants": [], "first_speaker": None, "can_inject": False}
        # Speaker（角色发言）
        if "你正在扮演虚拟世界中的角色" in system:
            return {"content": "*沉默片刻* 我明白了。", "next_speaker": None}
        # Summarizer
        if "对话记录员" in system:
            return {"summary": "场景对话已完成，各方达成基本共识。"}
        # Reviser
        if "叙事连贯性审核员" in system:
            return {"changes": "none", "reasoning": "mock 模式，不修改场景", "updated_scenes": []}
        # Short-term memory
        if "角色状态记录器" in system:
            return {"content": "我参与了这次事件，经历了一番交流。"}
        # Long-term memory promote
        if "长期记忆提炼器" in system:
            return {"promote": []}
        return {}

    def _dispatch_chat(self, system: str, prompt: str) -> dict | list:
        # select_participants
        if "选出本轮参与对话的角色" in system:
            return {"participants": [], "narration": ""}
        # generate_response
        if "对话引擎" in system:
            return {"messages": []}
        return {}

    def _dispatch_by_system(self, system: str) -> dict | list:
        if "has_relation" in system:
            return {"has_relation": False, "relation": None}
        return {}
