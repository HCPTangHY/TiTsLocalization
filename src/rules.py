# -*- coding: utf-8 -*-
"""TiTS JS 扫描规则

每条规则包含：
  - name:      规则名（调试用）
  - type:      文件类型（"js"）
  - condition:  ctx -> bool，判断是否匹配
  - process:    ctx -> list[dict]，返回词条列表

process 必须设置 ctx.end_pos 告诉 scanner 跳到哪里。
process 通过 ctx.scanner 访问工具方法（match_paren / split_args 等）。
"""

from util import parse_js_string, semantic_key, format_pos, context_hash

RULES = []


# ================================================================
#   辅助函数
# ================================================================

def make_entry(ctx, category, original, pos):
    """构建词条。pos 是相对于 content 的 0-based 偏移。"""
    s = ctx.scanner
    if not original or not s.has_alpha(original):
        return None
    h = context_hash(s._prev_original, original, "")
    key_text = semantic_key(original)
    return {
        "key": f"{category}|{key_text}|{h}",
        "original": original,
        "translation": "",
        "context": format_pos(pos + s.pos_offset + 1),
    }


# ================================================================
#   Rule: output / outputText / combatAppend — 完整括号内容提取
# ================================================================

_CALL_EXTRACT = {
    "output": "output",
    "outputText": "output",
    "combatAppend": "combat",
}


def _is_call_extract(ctx):
    return ctx.event == "call" and ctx.identifier in _CALL_EXTRACT


def _process_call_extract(ctx):
    s = ctx.scanner
    category = _CALL_EXTRACT[ctx.identifier]
    inner, after = s.extract_call_content(ctx.paren_pos)
    ctx.end_pos = after
    if not inner:
        return []
    # 去掉前后引号
    content_pos = ctx.paren_pos + 1
    stripped = inner
    if stripped and stripped[0] in ('"', "'"):
        stripped = stripped[1:]
        content_pos += 1
    if stripped and stripped[-1] in ('"', "'"):
        stripped = stripped[:-1]
    entry = make_entry(ctx, category, stripped, content_pos)
    return [entry] if entry else []


RULES.append({
    "name": "call_extract",
    "type": "js",
    "condition": _is_call_extract,
    "process": _process_call_extract,
})


# ================================================================
#   Rule: addButton / showName / createPerk 等 — 第N个参数提取
# ================================================================

# (arg_index, category) 或 [(arg_index, category), ...] 多参数提取
_ARG_EXTRACT = {
    "addButton":         [(1, "button"), (3, "button.hover"), (4, "button.tooltip")],
    "addDisabledButton": [(1, "button"), (3, "button.hover"), (4, "button.tooltip")],
    "showName":          [(0, "name.show")],
    "createPerk":        [(0, "perk")],
    "author":            [(0, "_skip")],
}


def _is_arg_extract(ctx):
    return ctx.event == "call" and ctx.identifier in _ARG_EXTRACT


def _process_arg_extract(ctx):
    s = ctx.scanner
    extractions = _ARG_EXTRACT[ctx.identifier]

    close = s.match_paren(ctx.paren_pos)
    if close < 0:
        ctx.end_pos = ctx.paren_pos + 1
        return []

    inner = s.content[ctx.paren_pos + 1:close]
    ctx.end_pos = close + 1

    args = s.split_args(inner)
    results = []

    for arg_idx, category in extractions:
        if category == "_skip":
            continue
        if arg_idx >= len(args):
            continue

        arg_text, arg_offset = args[arg_idx]
        # 找到 arg_text 内字符串字面量的起始位置（跳过前导空白）
        leading = len(arg_text) - len(arg_text.lstrip())
        stripped = arg_text.strip()
        if not stripped or stripped[0] not in ('"', "'"):
            continue

        content, _ = parse_js_string(stripped, 0)
        if content is None:
            continue

        # 参数在 inner 中的精确起始偏移 = arg_offset + 前导空白 + 1（跳引号）
        real_pos = ctx.paren_pos + 1 + arg_offset + leading + 1

        entry = make_entry(ctx, category, content, real_pos)
        if entry:
            results.append(entry)

    return results


RULES.append({
    "name": "arg_extract",
    "type": "js",
    "condition": _is_arg_extract,
    "process": _process_arg_extract,
})


# ================================================================
#   Rule: this.short = "..." 等 — 赋值模式
# ================================================================

_ASSIGN = {
    'this.short':        'name.short',
    'this.long':         'desc.long',
    'this.description':  'desc',
    'this.ButtonName':   'ui.button',
    'this.TooltipTitle': 'ui.tooltip',
}


def _is_assign(ctx):
    if ctx.event != "string":
        return False
    prefix = ctx.prefix.rstrip()
    for pattern in _ASSIGN:
        if prefix.endswith(pattern + ' =') or prefix.endswith(pattern + '='):
            return True
    return False


def _process_assign(ctx):
    s = ctx.scanner
    prefix = ctx.prefix.rstrip()
    for pattern, category in _ASSIGN.items():
        if prefix.endswith(pattern + ' =') or prefix.endswith(pattern + '='):
            str_content, end = parse_js_string(s.content, ctx.pos)
            if str_content is not None:
                ctx.end_pos = end
                entry = make_entry(ctx, category, str_content, ctx.pos + 1)
                return [entry] if entry else []
    return []


RULES.append({
    "name": "assign",
    "type": "js",
    "condition": _is_assign,
    "process": _process_assign,
})


# ================================================================
#   Rule: text:"..." / ttB:"..." / dttB:"..." — 对象字段
# ================================================================

_FIELD = {
    'text': 'button.text',
    'ttB':  'button.ttB',
    'dttB': 'button.dttB',
}


def _is_field(ctx):
    if ctx.event != "string":
        return False
    prefix = ctx.prefix.rstrip()
    for f in _FIELD:
        if prefix.endswith(f + ':') or prefix.endswith(f + ': '):
            return True
    return False


def _process_field(ctx):
    s = ctx.scanner
    prefix = ctx.prefix.rstrip()
    for f, category in _FIELD.items():
        if prefix.endswith(f + ':') or prefix.endswith(f + ': '):
            str_content, end = parse_js_string(s.content, ctx.pos)
            if str_content is not None:
                ctx.end_pos = end
                entry = make_entry(ctx, category, str_content, ctx.pos + 1)
                return [entry] if entry else []
    return []


RULES.append({
    "name": "field",
    "type": "js",
    "condition": _is_field,
    "process": _process_field,
})


# ================================================================
#   Rule: textify() — babel tagged template literal
#   textify(VAR||(VAR=(0,Ce.Z)(["str1","str2",...])), interp1, interp2, ...)
#   提取字符串数组中的所有文本
# ================================================================

import re as _re


def _is_textify(ctx):
    return ctx.event == "call" and ctx.identifier == "textify"


def _process_textify(ctx):
    s = ctx.scanner
    inner, after = s.extract_call_content(ctx.paren_pos)
    ctx.end_pos = after
    if not inner:
        return []

    # inner 形如: VAR||(VAR=(0,Ce.Z)(["str1","str2"])), interp1, ...
    # 找到字符串数组 ["...","..."]
    results = []

    # 用正则找所有引号字符串
    # 从 ([" 开始到 "]) 结束的数组部分
    arr_start = inner.find('(["')
    if arr_start < 0:
        arr_start = inner.find("(['")
    if arr_start < 0:
        return []

    arr_start += 1  # 跳过 (
    # 从 arr_start 找匹配的 ]
    bracket_pos = arr_start
    if inner[bracket_pos] != '[':
        return []

    # 解析数组内的字符串
    i = bracket_pos + 1
    while i < len(inner):
        ch = inner[i]
        if ch == ']':
            break
        if ch in ('"', "'"):
            str_content, end = parse_js_string(inner, i)
            if str_content is not None and str_content.strip():
                # 计算在原始文件中的位置
                real_pos = ctx.paren_pos + 1 + i + 1  # +1 for (, +1 for quote
                entry = make_entry(ctx, "textify", str_content, real_pos)
                if entry:
                    results.append(entry)
                i = end
                continue
        i += 1

    return results


RULES.append({
    "name": "textify",
    "type": "js",
    "condition": _is_textify,
    "process": _process_textify,
})
