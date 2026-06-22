# -*- coding: utf-8 -*-
"""TiTS JS 游标扫描器

scanner 只负责：
  1. 游标移动、跳过注释/字符串
  2. 识别标识符，查 rules 注册表分发
  3. 括号匹配、参数分割等底层操作

所有提取规则在 rules.py 中注册。
"""

import re
from util import parse_js_string, lookback, semantic_key, format_pos, context_hash


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

        # 从 rules.py 加载规则
        from rules import CALL_RULES, ARG_RULES, ASSIGN_RULES, FIELD_RULES, CUSTOM_RULES
        self._call_rules = CALL_RULES
        self._arg_rules = ARG_RULES
        self._assign_rules = ASSIGN_RULES
        self._field_rules = FIELD_RULES
        self._custom_rules = CUSTOM_RULES

    # ==========================================================
    #  公共工具方法（供 rules 的 custom handler 调用）
    # ==========================================================

    def unique_key(self, key):
        if key in self.used_keys:
            i = 1
            while f"{key}#{i}" in self.used_keys:
                i += 1
            key = f"{key}#{i}"
        self.used_keys.add(key)
        return key

    def has_alpha(self, s):
        return bool(re.search(r'[a-zA-Z]', s))

    def add_entry(self, category, original, pos, next_hint=""):
        """添加一条词条。pos 是相对于 self.content 的 0-based 偏移。"""
        if not original or not self.has_alpha(original):
            return
        h = context_hash(self._prev_original, original, next_hint)
        key_text = semantic_key(original)
        key = f"{category}|{key_text}|{h}"
        key = self.unique_key(key)
        self.entries.append({
            "key": key,
            "original": original,
            "translation": "",
            "context": format_pos(pos + self.pos_offset + 1),
        })
        self._prev_original = original

    def match_paren(self, start):
        """从 content[start]='(' 开始，返回匹配 ')' 的位置。失败返回 -1"""
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

    def extract_call_content(self, paren_start):
        """提取 (...) 内的完整内容，返回 (inner, end_pos_after_paren)"""
        close = self.match_paren(paren_start)
        if close < 0:
            return "", paren_start + 1
        inner = self.content[paren_start + 1:close]
        return inner, close + 1

    def split_args(self, inner):
        """分割函数参数，正确处理嵌套括号和字符串"""
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

    # ==========================================================
    #  内部方法
    # ==========================================================

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

    def _handle_call_rule(self, category, name_end):
        inner, after = self.extract_call_content(name_end)
        if inner:
            content_pos = name_end + 1
            stripped = inner
            if stripped and stripped[0] in ('"', "'"):
                stripped = stripped[1:]
                content_pos += 1
            if stripped and stripped[-1] in ('"', "'"):
                stripped = stripped[:-1]
            self.add_entry(category, stripped, content_pos)
        self.pos = after

    def _handle_arg_rule(self, arg_idx, category, name_end):
        paren_pos = name_end
        close = self.match_paren(paren_pos)
        if close < 0:
            self.pos = paren_pos + 1
            return

        inner = self.content[paren_pos + 1:close]
        self.pos = close + 1

        if category == '_skip':
            return

        args = self.split_args(inner)
        if arg_idx < len(args):
            arg = args[arg_idx].strip()
            if arg and arg[0] in ('"', "'"):
                content, _ = parse_js_string(arg, 0)
                if content is not None:
                    str_offset = inner.find(arg.strip())
                    if str_offset < 0:
                        str_offset = 0
                    real_pos = paren_pos + 1 + str_offset + 1
                    self.add_entry(category, content, real_pos)

    def _try_assign_pattern(self):
        prefix = lookback(self.content, self.pos, 50).rstrip()
        for pattern, category in self._assign_rules.items():
            if prefix.endswith(pattern + ' =') or prefix.endswith(pattern + '='):
                str_content, end = parse_js_string(self.content, self.pos)
                if str_content is not None:
                    self.add_entry(category, str_content, self.pos + 1)
                    self.pos = end
                    return True
        return False

    def _try_obj_field(self):
        prefix = lookback(self.content, self.pos, 30).rstrip()
        for field, category in self._field_rules.items():
            if prefix.endswith(field + ':') or prefix.endswith(field + ': '):
                str_content, end = parse_js_string(self.content, self.pos)
                if str_content is not None:
                    self.add_entry(category, str_content, self.pos + 1)
                    self.pos = end
                    return True
        return False

    # ==========================================================
    #  主扫描循环
    # ==========================================================

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

                if name and name_end < self.length and self.content[name_end] == '(':
                    if name in self._custom_rules:
                        self._custom_rules[name](self, name_end)
                        continue
                    if name in self._call_rules:
                        self._handle_call_rule(self._call_rules[name], name_end)
                        continue
                    if name in self._arg_rules:
                        arg_idx, category = self._arg_rules[name]
                        self._handle_arg_rule(arg_idx, category, name_end)
                        continue

                self.pos = name_end
                continue

            self.pos += 1

        return self.entries


def extract_file(file_path, content, pos_offset=0):
    scanner = TiTSScanner(content, file_path, pos_offset=pos_offset)
    return scanner.scan()
