"""Shared LLM utility functions."""

from __future__ import annotations


def unwrap_list(result: dict | list | None) -> list:
    """Unwrap LLM structured output into a list.

    complete_json returns dict | list. When the LLM wraps the array in a dict
    (e.g. {"items": [...]} or {"results": [...]}), extract the inner list.
    """
    if isinstance(result, list):
        return result
    if not isinstance(result, dict):
        return []
    # Try known wrapper keys
    for key in ("items", "results", "data", "memories", "elements", "promote"):
        val = result.get(key)
        if isinstance(val, list):
            return val
    # Search all values for the first list
    for val in result.values():
        if isinstance(val, list):
            return val
    return []
