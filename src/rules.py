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

import re

from util import parse_js_string, semantic_key, format_pos, context_hash

RULES = []


# ================================================================
#   辅助函数
# ================================================================

def _strip_escape_newlines(text):
    """剥离首尾 \\n 和 \\t 序列。返回 (stripped, leading字符数, trailing字符数)。"""
    lead = 0
    while True:
        if text[lead:lead + 2] == '\\n':
            lead += 2
        elif text[lead:lead + 2] == '\\t':
            lead += 2
        else:
            break
    trail = 0
    end = len(text)
    while end - 2 >= lead:
        if text[end - 2:end] == '\\n':
            trail += 2
            end -= 2
        elif text[end - 2:end] == '\\t':
            trail += 2
            end -= 2
        else:
            break
    return text[lead:end], lead, trail


def _placeholderize_expr(expr):
    """将表达式中的变量引用替换为 {var0} {var1} 占位符。
    返回 (placeholder_text, {"var0": "a", "var1": "t", ...})。
    字符串字面量和数字保持不变。
    按顶层 + 分割，括号内的 + 不切分。
    """
    # 按顶层 + 分割，尊重括号和引号嵌套
    tokens = []
    depth = 0
    cur = []
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch in ('"', "'"):
            # 跳过字符串字面量
            j = i + 1
            while j < len(expr) and expr[j] != ch:
                if expr[j] == '\\':
                    j += 1
                j += 1
            cur.append(expr[i:j + 1])
            i = j + 1
            continue
        if ch in ('(', '[', '{'):
            depth += 1
        elif ch in (')', ']', '}'):
            depth -= 1
        elif ch == '+' and depth == 0:
            tokens.append(''.join(cur))
            tokens.append('+')
            cur = []
            i += 1
            continue
        elif ch in ('?', ':') and depth == 0:
            # 三目运算符分隔符
            tokens.append(''.join(cur))
            tokens.append(ch)
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    tokens.append(''.join(cur))

    var_map = {}
    var_idx = [0]  # 用列表包装以便递归共享计数器
    result = []
    for token in tokens:
        t = token.strip()
        if t in ('+', '?', ':'):
            result.append(t)
        elif not t:
            result.append(token)
        elif t[0] in ('"', "'"):
            result.append(token)
        elif t[0].isdigit():
            result.append(token)
        elif t.startswith('('):
            # 括号表达式：递归处理内部
            inner = t[1:-1] if t.endswith(')') else t[1:]
            closing = ')' if t.endswith(')') else ''
            inner_result, inner_vars = _placeholderize_expr(inner)
            for k, v in inner_vars.items():
                new_key = f"var{var_idx[0]}"
                var_map[new_key] = v
                inner_result = inner_result.replace('{' + k + '}', '{' + new_key + '}')
                var_idx[0] += 1
            result.append('(' + inner_result + closing)
        else:
            # 变量或函数调用
            paren_idx = t.find('(')
            if paren_idx >= 0 and t.endswith(')'):
                func_name = t[:paren_idx]
                inner_args = t[paren_idx + 1:-1]
                # 递归处理括号内参数
                inner_result, inner_vars = _placeholderize_expr(inner_args)
                for k, v in inner_vars.items():
                    new_key = f"var{var_idx[0]}"
                    var_map[new_key] = v
                    inner_result = inner_result.replace('{' + k + '}', '{' + new_key + '}')
                    var_idx[0] += 1
                # 拆分函数名：对象前缀(不稳定) + 方法名(稳定)
                # 如 Ot.m.toTitleCase -> prefix=Ot.m, method=toTitleCase
                last_dot = func_name.rfind('.')
                if last_dot >= 0:
                    obj_prefix = func_name[:last_dot]
                    method_name = func_name[last_dot + 1:]
                    pk = f"var{var_idx[0]}"
                    var_map[pk] = obj_prefix
                    var_idx[0] += 1
                    result.append(f"{{{pk}}}.{method_name}({inner_result})")
                else:
                    # 无点号的函数名（如 isSillyModeEnabled）也占位
                    pk = f"var{var_idx[0]}"
                    var_map[pk] = func_name
                    var_idx[0] += 1
                    result.append(f"{{{pk}}}({inner_result})")
            else:
                key = f"var{var_idx[0]}"
                var_map[key] = t
                leading_ws = token[:len(token) - len(token.lstrip())]
                trailing_ws = token[len(token.rstrip()):]
                result.append(f"{leading_ws}{{{key}}}{trailing_ws}")
                var_idx[0] += 1
    return ''.join(result), var_map


def make_entry(ctx, category, original, pos, context_text=None):
    """构建词条。pos 是相对于 content 的 0-based 偏移。
    context_text: 可选，附近代码上下文（如完整的 addButton 调用），会追加到 context 字段。
    自动剥离首尾 \\n 并偏移 POS。
    """
    s = ctx.scanner
    # 剥离 leading/trailing \n，调整 POS
    original, lead_stripped, _ = _strip_escape_newlines(original)
    pos += lead_stripped
    if not original or not s.has_alpha(original):
        return None
    h = context_hash(s._prev_original, original, "")
    key_text = semantic_key(original)
    pos_str = format_pos(pos + s.pos_offset + 1)
    ctx_value = f"{pos_str} {context_text}" if context_text else pos_str
    return {
        "key": f"{category}|{key_text}|{h}",
        "original": original,
        "translation": "",
        "context": ctx_value,
    }


# ================================================================
#   Rule: output / outputText / combatAppend — 完整括号内容提取
# ================================================================

_CALL_EXTRACT = {
    "output": "output",
    "outputText": "output",
    "outputB": "output",
    "combatOutput": "combat",
    "combatAppend": "combat",
    "blockHeader": "header",
    "header": "header",
    "ParseText": "output",
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
    # 只取第一个参数（combatOutput("text",null,pc) → 只要 "text"）
    args = s.split_args(inner)
    if not args:
        return []
    first_arg, first_offset = args[0]
    stripped = first_arg.strip()
    if not stripped:
        return []
    # 判断是纯字符串还是拼接表达式
    # 纯字符串：引号开头且内部没有 "+ 拼接
    is_pure_string = (stripped[0] in ('"', "'") and
                      '"+' not in stripped and "'+" not in stripped)
    # 调用上下文（截断避免过长）
    call_ctx = f"{ctx.identifier}({inner})"
    if len(call_ctx) > 300:
        call_ctx = call_ctx[:300] + "..."
    if is_pure_string:
        # 纯字符串字面量
        leading = len(first_arg) - len(first_arg.lstrip())
        content_pos = ctx.paren_pos + 1 + first_offset + leading + 1  # +1 跳过开头引号
        text = stripped[1:]
        if text and text[-1] in ('"', "'"):
            text = text[:-1]
        entry = make_entry(ctx, category, text, content_pos, context_text=call_ctx)
        return [entry] if entry else []
    else:
        # 穿透白名单：这些函数已有专用规则，不要被 output 吐掉2
        # 让 scanner 深入内部，交给各自的规则处理
        _PASSTHROUGH = ('blockHeader', 'header', 'textify', 'ParseText')
        first_token = stripped.split('(')[0].strip()
        if first_token in _PASSTHROUGH:
            ctx.end_pos = ctx.paren_pos + 1
            return []
        # 检测 webpack 混淆的 textify 调用：(0,X.zI)(VAR||(VAR=(0,Y.Z)(["..."
        # .zI 是 textify 的统一混淆后缀，前缀字母是 webpack module 局部变量
        # 直接在这里解析内部的字符串数组，因为 scanner 主循环无法识别 (0,X.zI)( 作为函数调用
        if re.match(r'\(0,[a-zA-Z_$]+\.zI\)', stripped):
            # 手动提取内部的 textify 字符串数组
            arr_start = inner.find('(["')
            if arr_start < 0:
                arr_start = inner.find("(['")
            if arr_start >= 0:
                arr_start += 1  # 跳过 (
                results = []
                i = arr_start + 1  # 跳过 [
                while i < len(inner):
                    ch = inner[i]
                    if ch == ']':
                        break
                    if ch in ('"', "'"):
                        str_content, end = parse_js_string(inner, i)
                        if str_content is not None and str_content.strip():
                            real_pos = ctx.paren_pos + 1 + i + 1
                            textify_ctx = f"textify([{repr(str_content[:50])}...])"
                            entry = make_entry(ctx, "textify", str_content, real_pos, context_text=textify_ctx)
                            if entry:
                                results.append(entry)
                            i = end
                            continue
                    i += 1
                return results
            ctx.end_pos = ctx.paren_pos + 1
            return []
        # 拼接/三目表达式：占位符化变量，保留字符串给译者
        leading = len(first_arg) - len(first_arg.lstrip())
        real_pos = ctx.paren_pos + 1 + first_offset + leading
        placeholder, var_map = _placeholderize_expr(stripped)
        # 剥离 expr 最外层的引号和 \n：
        # "\n\nThe "+... → The "+...  (去掉开头 "\n\n)
        # ...repair." → ...repair.  (去掉结尾 ")
        expr_text = placeholder
        pos_adjust = 0
        if expr_text.startswith('"'):
            expr_text = expr_text[1:]
            pos_adjust += 1
        # 剥离 leading \n \t
        while expr_text.startswith('\\n') or expr_text.startswith('\\t'):
            expr_text = expr_text[2:]
            pos_adjust += 2
        if expr_text.endswith('"'):
            expr_text = expr_text[:-1]
        # 剥离 trailing \n \t
        while expr_text.endswith('\\n') or expr_text.endswith('\\t'):
            expr_text = expr_text[:-2]
        real_pos += pos_adjust
        vars_tag = '<<VARS:' + ','.join(f'{k}={v}' for k, v in var_map.items()) + '>>' if var_map else ''
        expr_ctx = f"{vars_tag} {ctx.identifier}({inner})"
        entry = make_entry(ctx, category + ".expr", expr_text, real_pos, context_text=expr_ctx)
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
    "renderAchievementType": [(0, "header")],
    # showDialog(type, header, body, buttons) — arg0 是类型常量不翻，arg1 header 和 arg2 body 需要翻
    "showDialog":        [(1, "dialog.header"), (2, "dialog.body")],

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

    # addButton/addDisabledButton 的第三个参数是 callback 函数体，
    # 里面可能包含 output()/blockHeader() 等需要提取的调用。
    # 不跳过整个 addButton(...)，只跳到第三个参数之前，让 scanner 深入 callback。
    args = s.split_args(inner)
    if ctx.identifier in ('addButton', 'addDisabledButton') and len(args) > 2:
        # end_pos 设到第三个参数开始位置，scanner 会从这里继续扫描 callback
        _, third_arg_offset = args[2]
        ctx.end_pos = ctx.paren_pos + 1 + third_arg_offset
    elif ctx.identifier == 'showDialog' and len(args) > 2:
        # end_pos 设到第三个参数（body）开始位置，让 scanner 深入扫描：
        # - body 如果是 ParseText/textify 调用，scanner 会进入提取
        # - body 后面的 buttons 数组里的 txt: 字段也会被 field 规则捕获
        _, third_arg_offset = args[2]
        ctx.end_pos = ctx.paren_pos + 1 + third_arg_offset
    else:
        ctx.end_pos = close + 1

    # 完整调用作为上下文（截断避免过长）
    full_call = f"{ctx.identifier}({inner})"
    if len(full_call) > 300:
        full_call = full_call[:300] + "..."

    # 穿透白名单：这些函数有专用规则，arg_extract 不提取，让 scanner 深入
    _ARG_PASSTHROUGH = {'ParseText', 'textify', 'blockHeader', 'header'}

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
        if not stripped:
            continue

        # 穿透：如果参数是已有规则的函数调用，跳过让 scanner 深入
        first_token = stripped.split('(')[0].strip()
        if first_token in _ARG_PASSTHROUGH:
            continue

        if stripped[0] in ('"', "'"):
            # 检查是否为纯字符串（无拼接）还是表达式
            content, end = parse_js_string(stripped, 0)
            if content is not None and not stripped[end:].strip():
                # 纯字符串字面量：提取内容
                real_pos = ctx.paren_pos + 1 + arg_offset + leading + 1
                entry = make_entry(ctx, category, content, real_pos, context_text=full_call)
            else:
                # 以引号开头但后面有拼接（如 "text"+var），走 expr
                real_pos = ctx.paren_pos + 1 + arg_offset + leading
                placeholder, var_map = _placeholderize_expr(stripped)
                # 剥离首尾 wrapper 引号（同 call_extract 逻辑）
                expr_text = placeholder
                pos_adjust = 0
                if expr_text.startswith('"'):
                    expr_text = expr_text[1:]
                    pos_adjust += 1
                while expr_text.startswith('\\n') or expr_text.startswith('\\t'):
                    expr_text = expr_text[2:]
                    pos_adjust += 2
                if expr_text.endswith('"'):
                    expr_text = expr_text[:-1]
                while expr_text.endswith('\\n') or expr_text.endswith('\\t'):
                    expr_text = expr_text[:-2]
                real_pos += pos_adjust
                vars_tag = '<<VARS:' + ','.join(f'{k}={v}' for k, v in var_map.items()) + '>>'
                expr_context = f"{vars_tag} {full_call}"
                entry = make_entry(ctx, category + ".expr", expr_text, real_pos, context_text=expr_context)
        else:
            # 非字符串参数（纯变量、表达式、拼接等）：
            # 全部走 placeholderize，让译者决定是否翻译/包装
            real_pos = ctx.paren_pos + 1 + arg_offset + leading
            # 变量占位符化：非字符串非数字的 token 替换为 {var0} {var1}...
            placeholder, var_map = _placeholderize_expr(stripped)
            # <<VARS:...>> 是 replacer 需要解析的占位符映射。
            vars_tag = '<<VARS:' + ','.join(f'{k}={v}' for k, v in var_map.items()) + '>>'
            expr_context = f"{vars_tag} {full_call}"
            entry = make_entry(ctx, category + ".expr", placeholder, real_pos, context_text=expr_context)

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
    'e.shortName':       'item.short',
    'e.longName':        'item.long',
    'e.description':     'item.desc',
    'e.tooltip':         'item.tooltip',
    'e.attackVerb':      'item.attackVerb',
    'e.attackNoun':      'item.attackNoun',
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
                # 上下文：赋值语句 + 值前80字符
                assign_ctx = f"{pattern}=" + repr(str_content[:60])
                entry = make_entry(ctx, category, str_content, ctx.pos + 1, context_text=assign_ctx)
                return [entry] if entry else []
    return []


RULES.append({
    "name": "assign",
    "type": "js",
    "condition": _is_assign,
    "process": _process_assign,
})


# ================================================================
#   Rule: 通用变量赋值 — e="..." / e+="..."
# ================================================================


def _is_generic_assign(ctx):
    if ctx.event != "string":
        return False
    prefix = ctx.prefix.rstrip()
    # 匹配: 变量名= 或 变量名+= 后紧跟引号
    # 不匹配: this.xxx= (已有 assign 规则), text: (已有 field 规则)
    # 不匹配: === / !== (比较运算符)
    if prefix.endswith('===') or prefix.endswith('!==') or prefix.endswith('=='):
        return False
    if re.search(r'[a-zA-Z_$][a-zA-Z0-9_$]*\s*\+?=$', prefix):
        # 确保不是已有 assign 规则覆盖的 this.xxx
        for pattern in _ASSIGN:
            if prefix.endswith(pattern + ' =') or prefix.endswith(pattern + '='):
                return False
        return True
    return False


def _process_generic_assign(ctx):
    s = ctx.scanner
    str_content, end = parse_js_string(s.content, ctx.pos)
    if str_content is None:
        return []
    # 过滤已关闭：短字符串（HP、Unisex 等）也需要提取
    ctx.end_pos = end
    # 上下文：赋值左侧
    prefix = ctx.prefix.rstrip()
    # 取 = 前的变量名
    eq_idx = prefix.rfind('=')
    assign_lhs = prefix[max(0, eq_idx-30):eq_idx+1] if eq_idx >= 0 else prefix[-30:]
    assign_ctx = assign_lhs.strip() + repr(str_content[:60])
    entry = make_entry(ctx, 'assign', str_content, ctx.pos + 1, context_text=assign_ctx)
    return [entry] if entry else []


RULES.append({
    "name": "generic_assign",
    "type": "js",
    "condition": _is_generic_assign,
    "process": _process_generic_assign,
})


# ================================================================
#   Rule: text:"..." / ttB:"..." / dttB:"..." — 对象字段
# ================================================================

_FIELD = {
    'text': 'button.text',
    'ttB':  'button.ttB',
    'dttB': 'button.dttB',
    'title': 'ui.title',
    'statName': 'ui.stat',
    'statTitle': 'ui.stat.title',
    'placeholder': 'ui.placeholder',
    'label': 'ui.label',
    'txt':   'dialog.button',
}


# statName/statTitle 等字段在三目表达式中出现时（如 statName:t?"PHY":"PHYSIQUE"），
# scanner 触发 string event 时 prefix 末尾是 t?" 或 e:" 而不是 statName:"。
# 需要在 prefix 中搜索字段名而不是只检查末尾。
_FIELD_ANY_VALUE = {'statName', 'statTitle'}  # 这些字段提取任意值表达式中的字符串

def _is_field(ctx):
    if ctx.event != "string":
        return False
    prefix = ctx.prefix.rstrip()
    for f in _FIELD:
        if prefix.endswith(f + ':') or prefix.endswith(f + ': '):
            return True
    # 三目/nullish fallback：prefix 中有字段名后跟 : 再跟非引号内容再跟 ? 或引号
    # 如 statName:t?"  statName:null!==...?e:"
    for f in _FIELD_ANY_VALUE:
        # 搜 prefix 中 f: 的位置
        tag = f + ':'
        idx = prefix.rfind(tag)
        if idx >= 0:
            after = prefix[idx + len(tag):]
            # 确认中间没有逗号或 }（说明还在同一个属性值内）
            if ',' not in after and '}' not in after:
                return True
    return False


def _process_field(ctx):
    s = ctx.scanner
    prefix = ctx.prefix.rstrip()
    # 直接匹配：statName:"LEVEL"
    for f, category in _FIELD.items():
        if prefix.endswith(f + ':') or prefix.endswith(f + ': '):
            str_content, end = parse_js_string(s.content, ctx.pos)
            if str_content is not None:
                ctx.end_pos = end
                field_ctx = f"{f}:" + repr(str_content[:60])
                entry = make_entry(ctx, category, str_content, ctx.pos + 1, context_text=field_ctx)
                return [entry] if entry else []
    # 三目/nullish fallback：statName:t?"PHY" 或 statName:...?e:"SHIELDS"
    # prefix 里有字段名但不在末尾（中间隔了三目表达式片段）
    for f in _FIELD_ANY_VALUE:
        tag = f + ':'
        idx = prefix.rfind(tag)
        if idx >= 0:
            after = prefix[idx + len(tag):]
            if ',' not in after and '}' not in after:
                str_content, end = parse_js_string(s.content, ctx.pos)
                if str_content is not None:
                    ctx.end_pos = end
                    field_ctx = f"{f}:(ternary)" + repr(str_content[:60])
                    category = _FIELD[f]
                    entry = make_entry(ctx, category, str_content, ctx.pos + 1, context_text=field_ctx)
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
                textify_ctx = f"textify([{repr(str_content[:50])}...])"
                entry = make_entry(ctx, "textify", str_content, real_pos, context_text=textify_ctx)
                if entry:
                    results.append(entry)
                i = end
                continue
        i += 1

    return results


# ================================================================
#   Rule: createElement("tag", props, "text") — React UI 文本提取
#   匹配 l.createElement("span", null, "text content")
#   提取第3个参数（子内容）中的字符串字面量
# ================================================================

_CE_TAGS = {"span", "p", "div", "b", "i", "em", "strong", "label",
            "h1", "h2", "h3", "h4", "h5", "h6"}


def _is_create_element(ctx):
    return ctx.event == "call" and ctx.identifier == "createElement"


def _process_create_element(ctx):
    s = ctx.scanner
    close = s.match_paren(ctx.paren_pos)
    if close < 0:
        ctx.end_pos = ctx.paren_pos + 1
        return []

    inner = s.content[ctx.paren_pos + 1:close]

    args = s.split_args(inner)
    # 至少3个参数: (tag, props, child)
    if len(args) < 3:
        ctx.end_pos = ctx.paren_pos + 1  # 不跳过，让scanner继续深入
        return []

    # 检查第1个参数是否为 HTML 标签
    tag_text = args[0][0].strip().strip('"\'')
    if tag_text not in _CE_TAGS:
        ctx.end_pos = ctx.paren_pos + 1  # tag不匹配时不跳过，让scanner深入扫描内层
        return []

    # 不跳过整个括号，让 scanner 深入扫描嵌套的 createElement
    ctx.end_pos = ctx.paren_pos + 1

    # 提取当前层第3个及之后的纯字符串参数
    results = []
    for idx in range(2, len(args)):
        arg_text, arg_offset = args[idx]
        leading = len(arg_text) - len(arg_text.lstrip())
        stripped = arg_text.strip()
        if not stripped or stripped[0] not in ('"', "'"):
            continue
        content, _ = parse_js_string(stripped, 0)
        if content is None:
            continue
        real_pos = ctx.paren_pos + 1 + arg_offset + leading + 1
        ce_ctx = f"createElement({args[0][0].strip()}, ..., {repr(content[:50])})"
        entry = make_entry(ctx, "ui.element", content, real_pos, context_text=ce_ctx)
        if entry:
            results.append(entry)

    return results


RULES.append({
    "name": "create_element",
    "type": "js",
    "condition": _is_create_element,
    "process": _process_create_element,
})


RULES.append({
    "name": "textify",
    "type": "js",
    "condition": _is_textify,
    "process": _process_textify,
})


# ================================================================
#   预扫描：动态发现混淆函数名并注入提取规则
#   scanner.scan() 开始前调用 prescan(content)
# ================================================================

# 键特征结构 → 参数提取配置
_PRESCAN_ANCHORS = [
    {
        # 菜单按钮函数：对象里有 buttonHeader + buttonText 字段
        "pattern": re.compile(r'buttonHeader:\w+.*?buttonText:\w+'),
        "args": [(2, 'menu.button'), (3, 'menu.tooltip')],
        "backtrack": 1000,
    },
]


def prescan(content):
    """预扫描文件内容，通过结构特征定位混淆函数名并动态注入到 _ARG_EXTRACT。

    原理：对象字段名（如 buttonHeader、buttonText）是源码写的，
    不会被 webpack 混淆。通过它们定位到包含它们的函数定义，
    反向推出函数的混淆名。
    """
    func_def_re = re.compile(r'([a-zA-Z_$][a-zA-Z0-9_$]*)\s*=\s*function\s*\(')

    for anchor in _PRESCAN_ANCHORS:
        for m in anchor['pattern'].finditer(content):
            region = content[max(0, m.start() - anchor['backtrack']):m.start()]
            func_match = None
            for fm in func_def_re.finditer(region):
                func_match = fm
            if not func_match:
                continue
            func_name = func_match.group(1)
            if func_name not in _ARG_EXTRACT:
                _ARG_EXTRACT[func_name] = anchor['args']


# ================================================================
#   Rule: VAR = ["str","str",...] — 纯字符串数组赋值
#   提取包含可翻译字符串的数组作为单条词条
# ================================================================

def _is_string_array(ctx):
    if ctx.event != "string":
        return False
    # 检查前缀是否是 = [ 模式
    prefix = ctx.prefix.rstrip()
    if not prefix.endswith('=[') and not prefix.endswith('= ['):
        return False
    # 确保不是对象属性 {内的数组
    # 且不是已被其他规则处理过的模式
    return True


def _process_string_array(ctx):
    s = ctx.scanner
    content = s.content
    # 往前找 [ 的位置
    bracket_pos = content.rfind('[', max(0, ctx.pos - 5), ctx.pos)
    if bracket_pos < 0:
        return []
    # 找配对的 ] — 手动匹配，因为 match_paren 只处理 ()
    depth = 1
    i = bracket_pos + 1
    close = -1
    while i < len(content) and depth > 0:
        ch = content[i]
        if ch in ('"', "'"):
            _, end = parse_js_string(content, i)
            if end > i:
                i = end
                continue
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                close = i
        i += 1
    if close < 0:
        return []
    arr_content = content[bracket_pos:close + 1]
    ctx.end_pos = close + 1
    # 解析数组内的所有字符串
    strings = []
    i = 1  # 跳过 [
    while i < len(arr_content) - 1:
        ch = arr_content[i]
        if ch in ('"', "'"):
            str_content, end = parse_js_string(arr_content, i)
            if str_content is not None:
                strings.append(str_content)
                i = end
                continue
        elif ch.isalpha() or ch == '_':
            # 非纯字符串数组，跳过
            return []
        i += 1
    if not strings or not any(s.has_alpha(st) for st in strings):
        return []
    # 整个数组作为一条词条，original = [内容]
    # POS 指向 [ 的位置
    arr_ctx = repr(arr_content[:80]) + ("..." if len(arr_content) > 80 else "")
    entry = make_entry(ctx, "string.array", arr_content, bracket_pos, context_text=arr_ctx)
    return [entry] if entry else []


RULES.append({
    "name": "string_array",
    "type": "js",
    "condition": _is_string_array,
    "process": _process_string_array,
})


# ================================================================
#   Rule: case "xxx": VAR = "..." — switch/case 内赋值字符串
#   检测 case 块内 = 后紧跟字符串字面量，不依赖变量名
# ================================================================

def _is_case_assign(ctx):
    if ctx.event != "string":
        return False
    prefix = ctx.prefix.rstrip()
    # 匹配 ...=" 或 ...= " 模式，且前面有 case 关键字
    if not (prefix.endswith('=') or prefix.endswith('= ')):
        return False
    # 检查 prefix 中有 case ... : ... = 结构
    # 不要求特定变量名
    case_idx = prefix.rfind('case')
    if case_idx < 0:
        return False
    between = prefix[case_idx:]
    # case 后应有 : 分隔，: 后应有 = 
    colon_idx = between.find(':')
    if colon_idx < 0:
        return False
    after_colon = between[colon_idx + 1:].strip()
    # : 之后到 = 之间不应有 ; 或 } （确保在同一个 case 块内）
    if ';' in after_colon or '}' in after_colon:
        return False
    return True


def _process_case_assign(ctx):
    s = ctx.scanner
    str_content, end = parse_js_string(s.content, ctx.pos)
    if str_content is None:
        return []
    ctx.end_pos = end
    # 从 prefix 提取 case 值作为上下文
    prefix = ctx.prefix.rstrip()
    case_idx = prefix.rfind('case')
    case_ctx = prefix[case_idx:] if case_idx >= 0 else ""
    if len(case_ctx) > 100:
        case_ctx = case_ctx[:100] + "..."
    entry = make_entry(ctx, "case.assign", str_content, ctx.pos + 1, context_text=case_ctx)
    return [entry] if entry else []


RULES.append({
    "name": "case_assign",
    "type": "js",
    "condition": _is_case_assign,
    "process": _process_case_assign,
})
