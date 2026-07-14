"""JSON 修复与提取工具函数。

从 LLM 回复中提取合法 JSON，支持 markdown 代码块包裹、截断括号补全、
未引用字符串值修复等容错处理。
"""

import json
import logging
import re

logger = logging.getLogger(__name__)


def _find_balanced_json(text: str, open_ch: str, close_ch: str) -> str | None:
    """从 text 中找到第一个以 open_ch 开头的、括号平衡的 JSON 片段。

    能处理含未闭合字符串的情况：当在字符串内遇到 } 或 ] 且栈上有匹配时，
    视为字符串已闭合，继续正常匹配括号。
    """
    start = text.find(open_ch)
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            # 字符串内遇到闭合括号，如果栈上有匹配 → 视为字符串已闭合
            if ch == close_ch and depth > 0:
                in_string = False
                # 不 continue，走下面的括号匹配逻辑
            else:
                continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _try_close_truncated(text: str) -> str:
    """尝试补全截断的 JSON —— 追加缺失的闭合括号/花括号。

    当字符串未闭合时（如 {"name": "小明}），遇到 }/] 且栈上有匹配的开括号，
    则在该位置之前插入闭合引号，使结构匹配能正常工作。
    """
    result: list[str] = []
    stack: list[str] = []
    in_string = False
    escape_next = False

    for ch in text:
        if escape_next:
            escape_next = False
            result.append(ch)
            continue
        if ch == "\\" and in_string:
            escape_next = True
            result.append(ch)
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            continue
        if in_string:
            # 字符串内遇到以下情况 → 先闭合字符串：
            # 1. } 或 ] 且栈上有匹配的开括号（结构符号在字符串内）
            # 2. \n（JSON 字符串不允许原始换行，说明字符串应该在换行前结束）
            if (ch in "}]" and stack and stack[-1] == ch) or ch == "\n":
                result.append('"')  # 插入闭合引号
                in_string = False
                if ch == "\n":
                    # 换行是格式，插入引号后让换行走下面的正常处理
                    pass
                # 不 continue，让 } 或 ] 走下面的正常结构匹配
            else:
                result.append(ch)
                continue
        if ch in "{[":
            stack.append("}" if ch == "{" else "]")
            result.append(ch)
        elif ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()
            result.append(ch)
        else:
            result.append(ch)

    text = "".join(result)

    if in_string:
        text += '"'

    while stack:
        text += stack.pop()

    return text


def _is_string_closed(text: str) -> bool:
    """检查以 " 开头的文本是否含有合法的闭合引号（跳过转义引号）。

    正确处理 \\\\": \\\\ 是转义反斜杠，其后的 " 是真正的闭合引号。
    """
    i = 1
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            i += 2  # 跳过转义序列（\\\" 或 \\\\）
        elif text[i] == '"':
            return True
        else:
            i += 1
    return False


def _close_unclosed_strings(text: str) -> str:
    """预处理：在结构边界处闭合未闭合的字符串。

    处理 {"name": "小明, "age": 18} 这种情况——值 "小明, 后面缺少闭合引号，
    逗号被当作字符串内容。在逗号之前闭合字符串，使后续解析能正确识别键值对。
    """
    result: list[str] = []
    in_str = False
    esc_next = False

    for ch in text:
        if esc_next:
            esc_next = False
            result.append(ch)
            continue
        if ch == "\\" and in_str:
            esc_next = True
            result.append(ch)
            continue
        if ch == '"':
            in_str = not in_str
            result.append(ch)
            continue
        if in_str and ch in ",}]\n":
            # 字符串内遇到结构边界 → 在当前位置之前插入闭合引号
            result.append('"')
            in_str = False
            # 不 continue，让这个结构字符被正常处理
        result.append(ch)

    if in_str:
        result.append('"')

    return "".join(result)


def _repair_json(text: str) -> str:
    """尝试修复常见的 JSON 格式问题（未引用字符串值、截断括号等）。

    非保证修复——如果文本损坏过于严重，返回的字符串仍然无法 json.loads，
    调用方应继续 fallback。
    """
    # 1. 预处理：闭合未闭合的字符串（在逗号等结构边界处）
    text = _close_unclosed_strings(text)
    # 2. 补全截断括号
    text = _try_close_truncated(text)

    # 3. 修复未引用的字符串值：`"key": some text` → `"key": "some text"`
    #    用逐行字符串解析代替正则（正则因 backtracking 导致已引用值被二次包裹）。
    #    先尝试将单行 JSON 分成多行，方便逐行处理。
    if "\n" not in text:
        # 单行 JSON，尝试在 }, 和 ,{ 后换行
        text = text.replace("},", "}\n").replace(",{", ",\n{")
        # 如果仍然是单行，尝试在逗号后换行（排除字符串内的逗号）
        if "\n" not in text and len(text) > 20:
            new_text = []
            in_str = False
            esc_next = False
            for ch in text:
                if esc_next:
                    esc_next = False
                    new_text.append(ch)
                    continue
                if ch == "\\" and in_str:
                    esc_next = True
                    new_text.append(ch)
                    continue
                if ch == '"':
                    in_str = not in_str
                    new_text.append(ch)
                    continue
                if ch == "," and not in_str:
                    new_text.append(ch)
                    new_text.append("\n")
                else:
                    new_text.append(ch)
            text = "".join(new_text)
    lines = text.split("\n")
    repaired: list[str] = []
    _json_value_starts = set('{["0123456789-tfn')
    for line in lines:
        # 找到 "key": 模式
        stripped = line.lstrip()
        # 跳过 { 开头但不是 "key": 模式的行（如 {"key": value} 整行）
        if stripped.startswith("{"):
            stripped = stripped[1:].lstrip()
            if not stripped.startswith('"'):
                repaired.append(line)
                continue
        elif not stripped.startswith('"'):
            repaired.append(line)
            continue
        # 处理行中可能有多个键值对的情况（如 {"key1": "value1", "key2": value2}）
        # 先尝试解析整行，如果成功则跳过
        try:
            json.loads(line)
            repaired.append(line)
            continue
        except json.JSONDecodeError:
            # 解析失败，继续处理这行中的键值对
            pass
        # 解析 key：找匹配的闭合引号
        end_quote = -1
        i = 1
        while i < len(stripped):
            if stripped[i] == "\\":
                i += 2
                continue
            if stripped[i] == '"':
                end_quote = i
                break
            i += 1
        if end_quote < 0:
            repaired.append(line)
            continue
        # key 后面应该是 : （允许空格）
        after_key = stripped[end_quote + 1 :].lstrip()
        if not after_key.startswith(":"):
            repaired.append(line)
            continue
        colon_idx = stripped.index(":", end_quote + 1)
        prefix = line[: len(line) - len(stripped)] + stripped[: colon_idx + 1]
        value_part = stripped[colon_idx + 1 :]
        # 找 value 的起始位置（跳过空格）
        value_stripped = value_part.lstrip()
        if not value_stripped:
            # 空值 → ""
            repaired.append(f'{prefix} ""')
            continue
        first_ch = value_stripped[0]
        if first_ch in _json_value_starts:
            # 值已经是合法 JSON 起始（{, [, ", 数字, -, true, false, null）
            # 但首字符是 " 时需确认有闭合引号，否则仍需修复
            if first_ch == '"' and not _is_string_closed(value_stripped):
                # 缺结尾引号：值内部转义后补上闭合引号
                inner = value_stripped[1:]  # 去掉开头引号
                escaped = inner.replace("\\", "\\\\").replace('"', '\\"')
                repaired.append(f'{prefix} "{escaped}"')
                continue
            repaired.append(line)
            continue
        # ── 未引用的字符串值，尝试修复 ──
        raw_value = value_stripped.rstrip()
        trailing = ""
        suffix = ""
        while raw_value and raw_value[-1] in "}]}":
            suffix = raw_value[-1] + suffix
            raw_value = raw_value[:-1].rstrip()
        if raw_value.endswith(","):
            raw_value = raw_value[:-1].rstrip()
            trailing = ","
        has_close = raw_value.endswith('"')
        if has_close:
            # 只缺开头引号
            inner = raw_value[:-1]
            escaped = inner.replace("\\", "\\\\").replace('"', '\\"')
            repaired.append(f'{prefix} "{escaped}"{trailing}{suffix}')
        else:
            # 两边都缺
            escaped = raw_value.replace("\\", "\\\\").replace('"', '\\"')
            repaired.append(f'{prefix} "{escaped}"{trailing}{suffix}')
    return "\n".join(repaired)


def _repair_json_aggressive(text: str) -> str:
    """更激进的 JSON 修复：用正则给未引用的字符串值加引号。

    匹配 "key": <未引用的值> 模式，给值加上双引号。
    策略：对匹配到的未引用值整体加双引号（含转义处理）。
    """
    # 匹配 "key": 后面跟着非引号开头的值（到行尾或下一个 key 或 } ] 之前）
    pattern = r'("[\w一-鿿]+")\s*:\s*([^"\d\[{tfn\-,\s\}]\S*?)(?=\s*[,}\]]|$)'

    def _add_both_quotes(m):
        key = m.group(1)
        val = m.group(2).rstrip()
        escaped = val.replace("\\", "\\\\").replace('"', '\\"')
        return f'{key}: "{escaped}"'

    # 策略 1：两边加引号
    result = re.sub(pattern, _add_both_quotes, text)
    try:
        json.loads(result)
        return result
    except (json.JSONDecodeError, ValueError):
        pass

    # 策略 2：前面加引号（值可能已经有结尾引号）
    pattern_open = r'("[\w一-鿿]+")\s*:\s*([^"\d\[{tfn\-,\s])'
    result2 = re.sub(pattern_open, lambda m: f'{m.group(1)}: "{m.group(2)}', text)
    try:
        json.loads(result2)
        return result2
    except (json.JSONDecodeError, ValueError):
        pass

    return text


def extract_json(text: str) -> dict | list:
    """从 LLM 回复中提取 JSON，兼容 markdown 代码块包裹和前后废话。"""
    text = text.strip()
    # 1. 尝试剥离 ```json ... ``` 或 ``` ... ```
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    # 2. 直接解析
    try:
        result = json.loads(text)
        if isinstance(result, (dict, list)):
            return result
    except json.JSONDecodeError:
        pass
    # 2.5. 闭合未闭合的字符串 + 补全截断的括号（在查找平衡 JSON 之前）
    text = _close_unclosed_strings(text)
    text = _try_close_truncated(text)
    # 3. 找第一个平衡的 { ... } 对象
    fragment = _find_balanced_json(text, "{", "}")
    if fragment:
        try:
            return json.loads(fragment)
        except json.JSONDecodeError:
            # 3.5. 尝试修复常见 JSON 格式问题后重试
            repaired = _repair_json(fragment)
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                # 3.6. 更激进的修复：用正则给未引用的字符串值加引号
                repaired2 = _repair_json_aggressive(repaired)
                try:
                    return json.loads(repaired2)
                except json.JSONDecodeError:
                    logger.warning("JSON object extraction failed. Raw response:\n%s", text[:500])
    # 4. 找第一个平衡的 [ ... ] 数组
    fragment = _find_balanced_json(text, "[", "]")
    if fragment:
        try:
            return json.loads(fragment)
        except json.JSONDecodeError:
            # 4.5. 尝试修复后重试
            repaired = _repair_json(fragment)
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                repaired2 = _repair_json_aggressive(repaired)
                try:
                    return json.loads(repaired2)
                except json.JSONDecodeError:
                    pass
    logger.warning("All JSON extraction methods failed. Raw response:\n%s", text[:500])
    raise ValueError(f"无法从 LLM 回复中提取 JSON: {text[:200]}")
