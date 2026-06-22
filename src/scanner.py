# -*- coding: utf-8 -*-
"""TiTS JS 游标扫描器

核心逻辑：
1. 游标扫描，遇到已知函数调用（output/combatAppend/addButton等）时
   用括号匹配提取完整调用内容，作为一条词条
2. 遇到 this.short = "xxx" 等赋值模式时，提取字符串字面量
"""

import re
from dataclasses import dataclass
from typing import Optional
from util import parse_js_string, lookback, semantic_key, format_pos, context_hash


# 需要整体提取调用内容的函数名
CALL_EXTRACTORS = {
    'output':         'output',
    'combatAppend':   'combat',
    'outputText':     'output',
}

# 需要提取第N个参数的函数
ARG_EXTRACTORS = {
    'addButton':         (1, 'button'),       # addButton(idx, "text", ...)
    'addDisabledButton': (1, 'button'),
    'showName':          (0, 'name.show'),
    'showBust':          (0, 'bust'),          # 不翻译，但记录
    'createPerk':        (0, 'perk'),
    'author':            (0, '_skip'),         # 不生成词条
}

# 对象字段提取: {text:"...", ttB:"...", dttB:"..."}
OBJ_FIELDS = {'text': 'button.text', 'ttB': 'button.ttB', 'dttB': 'button.dttB'}

# 赋值模式: this.xxx = "..."
ASSIGN_PATTERNS = {
    'this.short':       'name.short',
    'this.long':        'desc.long',
    'this.description': 'desc',
    'this.ButtonName':  'ui.button',
    'this.TooltipTitle':'ui.tooltip',
}


class TiTSScanner:
    def __init__(self, content, file_name, pos_offset=0):
        self.content = content
        self.file_name = file_name
        self.length = len(content)
        self.entries = []
        self.used_keys = set()
        self.pos = 0
        self.pos_offset = pos_offset
        self._prev_original = ""

    def _unique_key(self, key):
        if key in self.used_keys:
            i = 1
            while f"{key}#{i}" in self.used_keys:
                i += 1
            key = f"{key}#{i}"
        self.used_keys.add(key)
        return key

    def _has_alpha(self, s):
        return bool(re.search(r'[a-zA-Z]', s))

    def _add_entry(self, category, original, pos, next_hint=""):
        if not original or not self._has_alpha(original):
            return
        h = context_hash(self._prev_original, original, next_hint)
        key_text = semantic_key(original)
        key = f"{category}|{key_text}|{h}"
        key = self._unique_key(key)
        self.entries.append({
            "key": key,
            "original": original,
            "translation": "",
            "context": format_pos(pos + self.pos_offset + 1),
        })
        self._prev_original = original

    def _match_paren(self, start):
        if start >= self.length or self.content[start] != '(':
            return -1
        depth = 1
        i = start + 1
        while i < self.length and depth > 0:
            ch = self.content[i]
            if ch in ('"', "'", '`'):
                _, end = parse_js_string(self.content, i)
                if end > i:
                    i = end
                    continue
                i += 1
                continue
            if ch == '/' and i + 1 < self.length:
                nch = self.content[i + 1]
                if nch == '/':
                    nl = self.content.find('\n', i)
                    i = nl + 1 if nl >= 0 else self.length
                    continue
                elif nch == '*':
                    end = self.content.find('*/', i + 2)
                    i = end + 2 if end >= 0 else self.length
                    continue
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        return -1

    def _extract_call_content(self, paren_start):
        close = self._match_paren(paren_start)
        if close < 0:
            return "", paren_start + 1
        inner = self.content[paren_start + 1:close]
        return inner, close + 1

    def _try_identifier(self, pos):
        if pos >= self.length:
            return "", pos
        ch = self.content[pos]
        if not (ch.isalpha() or ch == '_' or ch == '$'):
            return "", pos
        end = pos + 1
        while end < self.length and (self.content[end].isalnum() or self.content[end] in ('_', '$')):
            end += 1
        return self.content[pos:end], end

    def _try_string_at(self, pos):
        if pos >= self.length or self.content[pos] not in ('"', "'", '`'):
            return "", pos, pos
        content, end = parse_js_string(self.content, pos)
        if content is None:
            return "", pos, pos
        return content, pos, end

    def scan(self):
        while self.pos < self.length:
            ch = self.content[self.pos]

            if ch == '/' and self.pos + 1 < self.length:
                nch = self.content[self.pos + 1]
                if nch == '/':
                    end = self.content.find('\n', self.pos)
                    self.pos = end + 1 if end >= 0 else self.length
                    continue
                elif nch == '*':
                    end = self.content.find('*/', self.pos + 2)
                    self.pos = end + 2 if end >= 0 else self.length
                    continue

            if ch in ('"', "'", '`'):
                if self._try_assign_pattern():
                    continue
                if self._try_obj_field():
                    continue
                _, end = parse_js_string(self.content, self.pos)
                if end > self.pos:
                    self.pos = end
                else:
                    self.pos += 1
                continue

            if ch.isalpha() or ch == '_' or ch == '$':
                name, name_end = self._try_identifier(self.pos)

                if name in CALL_EXTRACTORS and name_end < self.length and self.content[name_end] == '(':
                    category = CALL_EXTRACTORS[name]
                    inner, after = self._extract_call_content(name_end)
                    if inner:
                        content_pos = name_end + 1
                        stripped = inner
                        if stripped and stripped[0] in ('"', "'"):
                            stripped = stripped[1:]
                            content_pos += 1
                        if stripped and stripped[-1] in ('"', "'"):
                            stripped = stripped[:-1]
                        self._add_entry(category, stripped, content_pos)
                    self.pos = after
                    continue

                if name in ARG_EXTRACTORS and name_end < self.length and self.content[name_end] == '(':
                    arg_idx, category = ARG_EXTRACTORS[name]
                    self._extract_arg(name, name_end, arg_idx, category)
                    continue

                self.pos = name_end
                continue

            self.pos += 1

        return self.entries

    def _try_assign_pattern(self):
        prefix = lookback(self.content, self.pos, 50).rstrip()
        for pattern, category in ASSIGN_PATTERNS.items():
            if prefix.endswith(pattern + ' =') or prefix.endswith(pattern + '='):
                str_content, end = parse_js_string(self.content, self.pos)
                if str_content is not None:
                    self._add_entry(category, str_content, self.pos + 1)
                    self.pos = end
                    return True
        return False

    def _try_obj_field(self):
        prefix = lookback(self.content, self.pos, 30).rstrip()
        for field, category in OBJ_FIELDS.items():
            if prefix.endswith(field + ':') or prefix.endswith(field + ': '):
                str_content, end = parse_js_string(self.content, self.pos)
                if str_content is not None:
                    self._add_entry(category, str_content, self.pos + 1)
                    self.pos = end
                    return True
        return False

    def _extract_arg(self, name, paren_pos, arg_idx, category):
        close = self._match_paren(paren_pos)
        if close < 0:
            self.pos = paren_pos + 1
            return

        inner = self.content[paren_pos + 1:close]
        self.pos = close + 1

        if category == '_skip':
            return

        args = self._split_args(inner)

        if arg_idx < len(args):
            arg = args[arg_idx].strip()
            if arg and arg[0] in ('"', "'"):
                content, _ = parse_js_string(arg, 0)
                if content is not None:
                    str_offset = inner.find(arg.strip())
                    if str_offset < 0:
                        str_offset = 0
                    real_pos = paren_pos + 1 + str_offset + 1
                    self._add_entry(category, content, real_pos)

    def _split_args(self, inner):
        args = []
        depth = 0
        current = []
        i = 0
        while i < len(inner):
            ch = inner[i]
            if ch in ('"', "'", '`'):
                content, end = parse_js_string(inner, i)
                if content is not None:
                    current.append(inner[i:end])
                    i = end
                    continue
            if ch in ('(', '[', '{'):
                depth += 1
            elif ch in (')', ']', '}'):
                depth -= 1
            elif ch == ',' and depth == 0:
                args.append(''.join(current))
                current = []
                i += 1
                continue
            current.append(ch)
            i += 1
        args.append(''.join(current))
        return args


def extract_file(file_path, content, pos_offset=0):
    scanner = TiTSScanner(content, file_path, pos_offset=pos_offset)
    return scanner.scan()
