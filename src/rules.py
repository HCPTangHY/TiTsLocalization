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

_ARG_EXTRACT = {
    "addButton":         (1, "button"),
    "addDisabledButton": (1, "button"),
    "showName":          (0, "name.show"),
    "showBust":          (0, "bust"),
    "createPerk":        (0, "perk"),
    "author":            (0, "_skip"),
}


def _is_arg_extract(ctx):
    return ctx.event == "call" and ctx.identifier in _ARG_EXTRACT


def _process_arg_extract(ctx):
    s = ctx.scanner
    arg_idx, category = _ARG_EXTRACT[ctx.identifier]

    close = s.match_paren(ctx.paren_pos)
    if close < 0:
        ctx.end_pos = ctx.paren_pos + 1
        return []

    inner = s.content[ctx.paren_pos + 1:close]
    ctx.end_pos = close + 1

    if category == "_skip":
        return []

    args = s.split_args(inner)
    if arg_idx >= len(args):
        return []

    arg = args[arg_idx].strip()
    if not arg or arg[0] not in ('"', "'"):
        return []

    content, _ = parse_js_string(arg, 0)
    if content is None:
        return []

    str_offset = inner.find(arg)
    if str_offset < 0:
        str_offset = 0
    real_pos = ctx.paren_pos + 1 + str_offset + 1

    entry = make_entry(ctx, category, content, real_pos)
    return [entry] if entry else []


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
