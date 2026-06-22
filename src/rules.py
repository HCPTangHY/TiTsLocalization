# -*- coding: utf-8 -*-
"""TiTS JS 扫描规则"""

import re
from util import semantic_key, format_pos, context_hash

RULES = []


# ================================================================
#   工具函数
# ================================================================

def _make_entry(ctx, category: str, key_suffix: str, original: str):
    return {
        "key": f"{category}|{key_suffix}",
        "original": original,
        "translation": "",
        "context": format_pos(ctx.pos + 1),  # 1-based
    }


def _pfx(prefix: str, regex: str):
    """在前缀末尾匹配正则"""
    return re.search(regex, prefix)


def _has_alpha(s: str) -> bool:
    return bool(re.search(r'[a-zA-Z]', s))


# ================================================================
#   Rule: output() 叙事文本
# ================================================================

def _is_output(ctx) -> bool:
    return bool(_pfx(ctx.prefix, r'output\(\s*$'))

def _proc_output(ctx):
    c = ctx.content
    if not c or len(c) < 2 or not _has_alpha(c):
        return []
    h = context_hash(ctx.prev_string, c, ctx.next_string)
    return [_make_entry(ctx, "output", f"{semantic_key(c)}|{h}", c)]

RULES.append({"name": "output", "condition": _is_output, "process": _proc_output})


# ================================================================
#   Rule: output() 拼接内部的字符串
#   匹配前缀: ...output("..."+xxx+"  或  ...output("...".concat(
# ================================================================

def _is_output_concat(ctx) -> bool:
    # 检查前缀里是否有 output( 且之后没有闭合的 )
    p = ctx.prefix
    # 往回找最近的 output(
    idx = p.rfind('output(')
    if idx < 0:
        return False
    # 从 output( 之后到当前位置，数括号
    after = p[idx + 7:]  # len('output(') = 7
    depth = 1
    for ch in after:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if depth <= 0:
            return False
    return True

def _proc_output_concat(ctx):
    c = ctx.content
    if not c or len(c) < 2 or not _has_alpha(c):
        return []
    h = context_hash(ctx.prev_string, c, ctx.next_string)
    return [_make_entry(ctx, "output", f"{semantic_key(c)}|{h}", c)]

RULES.append({"name": "output_concat", "condition": _is_output_concat, "process": _proc_output_concat})


# ================================================================
#   Rule: combatAppend() 战斗文本
# ================================================================

def _is_combat(ctx) -> bool:
    return bool(_pfx(ctx.prefix, r'combatAppend\(\s*$'))

def _proc_combat(ctx):
    c = ctx.content
    if not c or len(c) < 2 or not _has_alpha(c):
        return []
    h = context_hash(ctx.prev_string, c, ctx.next_string)
    return [_make_entry(ctx, "combat", f"{semantic_key(c)}|{h}", c)]

RULES.append({"name": "combatAppend", "condition": _is_combat, "process": _proc_combat})


# ================================================================
#   Rule: combatAppend() 拼接内部
# ================================================================

def _is_combat_concat(ctx) -> bool:
    p = ctx.prefix
    idx = p.rfind('combatAppend(')
    if idx < 0:
        return False
    after = p[idx + 13:]  # len('combatAppend(') = 13
    depth = 1
    for ch in after:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if depth <= 0:
            return False
    return True

def _proc_combat_concat(ctx):
    c = ctx.content
    if not c or len(c) < 2 or not _has_alpha(c):
        return []
    h = context_hash(ctx.prev_string, c, ctx.next_string)
    return [_make_entry(ctx, "combat", f"{semantic_key(c)}|{h}", c)]

RULES.append({"name": "combatAppend_concat", "condition": _is_combat_concat, "process": _proc_combat_concat})


# ================================================================
#   Rule: addButton() 按钮文本
# ================================================================

def _is_addbutton(ctx) -> bool:
    return bool(_pfx(ctx.prefix, r'addButton\(\s*\w+\s*,\s*$'))

def _proc_addbutton(ctx):
    c = ctx.content
    if not c:
        return []
    return [_make_entry(ctx, "button", semantic_key(c), c)]

RULES.append({"name": "addButton", "condition": _is_addbutton, "process": _proc_addbutton})


# ================================================================
#   Rule: addDisabledButton() 禁用按钮
# ================================================================

def _is_disabled_button(ctx) -> bool:
    return bool(_pfx(ctx.prefix, r'addDisabledButton\(\s*\w+\s*,\s*$'))

def _proc_disabled_button(ctx):
    c = ctx.content
    if not c:
        return []
    return [_make_entry(ctx, "button", semantic_key(c), c)]

RULES.append({"name": "addDisabledButton", "condition": _is_disabled_button, "process": _proc_disabled_button})


# ================================================================
#   Rule: addGatedButtonObj 字段 (text, ttB, dttB)
# ================================================================

def _is_gated_field(ctx) -> bool:
    return bool(_pfx(ctx.prefix, r'(?:text|ttB|dttB)\s*:\s*$'))

def _proc_gated_field(ctx):
    c = ctx.content
    if not c:
        return []
    m = _pfx(ctx.prefix, r'(text|ttB|dttB)\s*:\s*$')
    field = m.group(1) if m else "text"
    return [_make_entry(ctx, f"button.{field}", semantic_key(c), c)]

RULES.append({"name": "gatedButton", "condition": _is_gated_field, "process": _proc_gated_field})


# ================================================================
#   Rule: showName() 角色/场景名
# ================================================================

def _is_showname(ctx) -> bool:
    return bool(_pfx(ctx.prefix, r'showName\(\s*$'))

def _proc_showname(ctx):
    c = ctx.content
    if not c:
        return []
    return [_make_entry(ctx, "name.show", semantic_key(c), c)]

RULES.append({"name": "showName", "condition": _is_showname, "process": _proc_showname})


# ================================================================
#   Rule: this.short = "..." 角色短名
# ================================================================

def _is_this_short(ctx) -> bool:
    return bool(_pfx(ctx.prefix, r'this\.short\s*=\s*$'))

def _proc_this_short(ctx):
    c = ctx.content
    if not c:
        return []
    return [_make_entry(ctx, "name.short", semantic_key(c), c)]

RULES.append({"name": "this.short", "condition": _is_this_short, "process": _proc_this_short})


# ================================================================
#   Rule: this.long = "..." 角色长描述
# ================================================================

def _is_this_long(ctx) -> bool:
    return bool(_pfx(ctx.prefix, r'this\.long\s*=\s*$'))

def _proc_this_long(ctx):
    c = ctx.content
    if not c:
        return []
    h = context_hash(ctx.prev_string, c, ctx.next_string)
    return [_make_entry(ctx, "desc.long", f"{semantic_key(c)}|{h}", c)]

RULES.append({"name": "this.long", "condition": _is_this_long, "process": _proc_this_long})


# ================================================================
#   Rule: this.description = "..."
# ================================================================

def _is_this_desc(ctx) -> bool:
    return bool(_pfx(ctx.prefix, r'this\.description\s*=\s*$'))

def _proc_this_desc(ctx):
    c = ctx.content
    if not c:
        return []
    h = context_hash(ctx.prev_string, c, ctx.next_string)
    return [_make_entry(ctx, "desc", f"{semantic_key(c)}|{h}", c)]

RULES.append({"name": "this.description", "condition": _is_this_desc, "process": _proc_this_desc})


# ================================================================
#   Rule: createPerk() Perk名
# ================================================================

def _is_perk(ctx) -> bool:
    return bool(_pfx(ctx.prefix, r'createPerk\(\s*$'))

def _proc_perk(ctx):
    c = ctx.content
    if not c:
        return []
    return [_make_entry(ctx, "perk", semantic_key(c), c)]

RULES.append({"name": "createPerk", "condition": _is_perk, "process": _proc_perk})


# ================================================================
#   Rule: author() — 仅记录元数据，不生成词条
# ================================================================

def _is_author(ctx) -> bool:
    return bool(_pfx(ctx.prefix, r'author\(\s*$'))

def _proc_author(ctx):
    return []  # 不翻译

RULES.append({"name": "author", "condition": _is_author, "process": _proc_author})
