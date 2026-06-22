# -*- coding: utf-8 -*-
"""TiTS JS 扫描器工具函数"""

import re
import hashlib


def format_pos(pos: int) -> str:
    return f"<<POS:{pos:08d}>>"


def semantic_key(text: str, max_length: int = 64) -> str:
    return re.sub(r'[^a-zA-Z0-9]+', '_', text[:max_length]).strip('_')


def context_hash(prev_text: str, current_text: str, next_text: str) -> str:
    """基于相对上下文生成 hash，用于消歧短字符串"""
    combined = f"{prev_text[-50:]}|{current_text}|{next_text[:50]}"
    return hashlib.sha1(combined.encode()).hexdigest()[:12]


# ================================================================
#   JS 字符串解析（游标式）
# ================================================================

def parse_js_string(content: str, pos: int):
    """
    从 content[pos] 开始解析一个 JS 字符串字面量。
    content[pos] 必须是 ' 或 \" 或 `。

    返回 (string_content, end_pos):
        string_content: 引号之间的原始内容（保留转义序列）
        end_pos: 闭合引号之后的下一个字符位置
    失败返回 (None, pos + 1) 跳过一个字符。
    """
    if pos >= len(content):
        return None, pos + 1

    quote = content[pos]
    if quote not in ('"', "'", '`'):
        return None, pos + 1

    if quote == '`':
        return _parse_template_literal(content, pos)

    i = pos + 1
    while i < len(content):
        ch = content[i]
        if ch == '\\':
            i += 2  # 跳过转义
            continue
        if ch == quote:
            return content[pos + 1:i], i + 1
        # JS 普通字符串不能跨行（\n 是转义不是真换行）
        if ch in ('\n', '\r'):
            return None, pos + 1
        i += 1

    return None, pos + 1


def _parse_template_literal(content: str, pos: int):
    """解析模板字面量 `...`，跳过 ${...} 表达式"""
    i = pos + 1
    while i < len(content):
        ch = content[i]
        if ch == '\\':
            i += 2
            continue
        if ch == '`':
            return content[pos + 1:i], i + 1
        if ch == '$' and i + 1 < len(content) and content[i + 1] == '{':
            # ${...} 表达式 — 数括号跳过
            i += 2
            depth = 1
            while i < len(content) and depth > 0:
                c = content[i]
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                elif c in ('"', "'", '`'):
                    # 表达式内嵌套字符串，递归跳过
                    _, i = parse_js_string(content, i)
                    continue
                elif c == '\\' and i + 1 < len(content):
                    i += 2
                    continue
                i += 1
            continue
        i += 1

    return None, pos + 1


def lookback(content: str, pos: int, max_chars: int = 200) -> str:
    """获取 pos 之前的内容片段"""
    start = max(0, pos - max_chars)
    return content[start:pos]
