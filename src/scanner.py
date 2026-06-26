# -*- coding: utf-8 -*-
"""TiTS JS 游标扫描器

scanner 只负责：
  1. 游标移动、跳过注释/字符串
  2. 识别事件（call / string），构建 Context
  3. 遍历 RULES 分发，condition 匹配则 process
  4. 括号匹配、参数分割等工具方法供 rules 调用

所有提取规则在 rules.py 中以 condition/process 模式注册。
"""

from dataclasses import dataclass, field
from util import parse_js_string, lookback


@dataclass
class Context:
    """传递给规则的上下文"""
    event: str           # "call" = 标识符+括号, "string" = 字符串字面量
    content: str         # 完整文件内容
    pos: int             # 当前位置（标识符起始 或 引号位置）
    prefix: str          # 前面 200 字符
    file_name: str = ""
    scanner: object = None  # TiTSScanner 实例，提供工具方法
    # call 事件专属
    identifier: str = ""    # 函数名（如 "output"、"addButton"）
    paren_pos: int = -1     # '(' 位置
    # process 设置，告诉 scanner 跳到哪
    end_pos: int = -1


class TiTSScanner:
    def __init__(self, content, file_name, pos_offset=0):
        self.content = content
        self.file_name = file_name
        self.file_type = "js"
        self.length = len(content)
        self.entries = []
        self.used_keys = set()
        self.pos = 0
        self.pos_offset = pos_offset
        self._prev_original = ""

        from rules import RULES
        self._rules = [r for r in RULES if r["type"] == self.file_type]

    # ==========================================================
    #  公共工具方法（供 rules 的 process 调用）
    # ==========================================================

    def has_alpha(self, s):
        """字符串是否包含英文字母"""
        import re
        return bool(re.search(r'[a-zA-Z]', s))

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
        """分割函数参数，正确处理嵌套括号和字符串。

        返回 list of (arg_text, offset_in_inner)，offset 是该参数在 inner 中的起始字节偏移。
        """
        args = []
        depth = 0
        current = []
        cur_start = 0
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
                args.append((''.join(current), cur_start))
                current = []
                i += 1
                cur_start = i
                continue
            current.append(ch)
            i += 1
        args.append((''.join(current), cur_start))
        return args

    # ==========================================================
    #  内部方法
    # ==========================================================

    def _unique_key(self, key):
        if key in self.used_keys:
            i = 1
            while f"{key}#{i}" in self.used_keys:
                i += 1
            key = f"{key}#{i}"
        self.used_keys.add(key)
        return key

    def _try_identifier(self, pos):
        """从 pos 开始尝试读取一个 JS 标识符"""
        if pos >= self.length:
            return "", pos
        ch = self.content[pos]
        if not (ch.isalpha() or ch == '_' or ch == '$'):
            return "", pos
        end = pos + 1
        while end < self.length and (self.content[end].isalnum() or self.content[end] in ('_', '$')):
            end += 1
        return self.content[pos:end], end

    def _run_rules(self, ctx):
        """对 ctx 运行所有规则，首条匹配即停。返回是否有匹配。"""
        for rule in self._rules:
            if rule["condition"](ctx):
                result = rule["process"](ctx)
                for r in result:
                    if r is not None:
                        r["key"] = self._unique_key(r["key"])
                        self.entries.append(r)
                        self._prev_original = r["original"]
                return True
        return False

    # ==========================================================
    #  主扫描循环
    # ==========================================================

    def scan(self):
        from rules import prescan
        prescan(self.content)
        while self.pos < self.length:
            ch = self.content[self.pos]

            # 跳过注释
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

            # 字符串事件
            if ch in ('"', "'", '`'):
                ctx = Context(
                    event="string",
                    content=self.content,
                    pos=self.pos,
                    prefix=lookback(self.content, self.pos, 200),
                    file_name=self.file_name,
                    scanner=self,
                )
                if self._run_rules(ctx) and ctx.end_pos > self.pos:
                    self.pos = ctx.end_pos
                else:
                    _, end = parse_js_string(self.content, self.pos)
                    self.pos = end if end > self.pos else self.pos + 1
                continue

            # 标识符 → 检查是否为函数调用
            if ch.isalpha() or ch == '_' or ch == '$':
                name, name_end = self._try_identifier(self.pos)
                if name and name_end < self.length and self.content[name_end] == '(':
                    ctx = Context(
                        event="call",
                        content=self.content,
                        pos=self.pos,
                        prefix=lookback(self.content, self.pos, 200),
                        file_name=self.file_name,
                        scanner=self,
                        identifier=name,
                        paren_pos=name_end,
                    )
                    if self._run_rules(ctx) and ctx.end_pos > self.pos:
                        self.pos = ctx.end_pos
                    else:
                        self.pos = name_end
                else:
                    self.pos = name_end if name_end > self.pos else self.pos + 1
                continue

            self.pos += 1

        return self.entries


def extract_file(file_path, content, pos_offset=0):
    scanner = TiTSScanner(content, file_path, pos_offset=pos_offset)
    return scanner.scan()
