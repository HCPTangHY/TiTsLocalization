#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TiTS JS 翻译替换器

基于 POS（1-based 字符偏移）的顺序拼接替换。
按位置升序处理，确保 last_idx 单调递增。
"""

import json
import os
import re
import sys
import logging

logger = logging.getLogger("replacer")
logging.basicConfig(format="[%(levelname)s] %(message)s", level=logging.INFO)


def parse_pos(context: str) -> int:
    """从 context 字段解析 POS（1-based），返回 0-based。"""
    if not context:
        return -1
    m = re.search(r'<<POS:(\d+)>>', context)
    if m:
        return int(m.group(1)) - 1  # 转 0-based
    # 兼容 HTML 转义
    m2 = re.search(r'&lt;&lt;POS:(\d+)&gt;&gt;', context)
    if m2:
        return int(m2.group(1)) - 1
    return -1


def parse_vars(context: str) -> dict:
    """从 context 解析 <<VARS:var0=a,var1=Ot.m>> 映射表。"""
    if not context:
        return {}
    m = re.search(r'<<VARS:([^>]+)>>', context)
    if not m:
        return {}
    result = {}
    for pair in m.group(1).split(','):
        eq = pair.find('=')
        if eq > 0:
            result[pair[:eq]] = pair[eq + 1:]
    return result


def resolve_vars(text: str, var_map: dict) -> str:
    """将 {var0} {var1} 占位符替换为真实变量名。"""
    for k, v in var_map.items():
        text = text.replace('{' + k + '}', v)
    return text


def check_quote_safety(original: str, translation: str) -> bool:
    """检查译文的引号结构是否安全。

    规则：译文中每种引号的净变化量必须为偶数（成对出现）。
    允许译文比原文多或少成对引号，但不允许落单的引号破坏JS语法。
    同时检查反斜杠转义的引号（\\" 和 \\'）不被计入。
    """
    def count_unescaped(s, ch):
        """计算未转义的引号数量"""
        count = 0
        i = 0
        while i < len(s):
            if s[i] == '\\':  # 跳过转义字符
                i += 2
                continue
            if s[i] == ch:
                count += 1
            i += 1
        return count

    for ch in ('"', "'"):
        orig_count = count_unescaped(original, ch)
        trans_count = count_unescaped(translation, ch)
        # 净变化必须是偶数（成对增减）
        delta = trans_count - orig_count
        if delta % 2 != 0:
            return False
    return True


def replace_file(source_path: str, trans_json_path: str, output_path: str):
    """对一个源文件执行翻译替换"""
    with open(source_path, 'r', encoding='utf-8') as f:
        content = f.read()

    with open(trans_json_path, 'r', encoding='utf-8') as f:
        entries = json.load(f)

    # 零宽空格字符集
    _ZWSP = '\u200b\u200c\u200d\ufeff'

    # 过滤出有翻译且有POS的词条
    items = []
    for e in entries:
        translation = e.get('translation', '')
        if not translation:
            continue
        # 剥离零宽空格：译者用零宽空格表示"不需要翻译"（如英语复数s），
        # 但零宽空格插入JS代码区会导致语法错误，替换为空字符串
        translation = translation.translate(str.maketrans('', '', _ZWSP))
        if not translation:
            continue
        pos0 = parse_pos(e.get('context', ''))
        if pos0 < 0:
            continue
        original = e.get('original', '')
        if not original:
            continue
        context = e.get('context', '')
        key = e.get('key', '')
        # 解析 expr 占位符映射
        var_map = parse_vars(context)
        if var_map:
            # expr 类型：还原 original 和 translation 中的 {var} 占位符
            original = resolve_vars(original, var_map)
            translation = resolve_vars(translation, var_map)
        # 引号安全检查
        if not check_quote_safety(original, translation):
            logger.warning(f"Quote mismatch, skip: key={key[:60]}")
            logger.warning(f"  orig: {repr(original[:80])}")
            logger.warning(f"  trans: {repr(translation[:80])}")
            continue
        items.append((pos0, original, translation, key))

    if not items:
        logger.info(f"No translated entries, copying original")
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return 0

    # 按位置升序
    items.sort(key=lambda x: x[0])

    # 顺序拼接替换
    parts = []
    last_idx = 0
    applied = 0
    skipped = 0

    for pos0, original, translation, key in items:
        if pos0 < last_idx:
            logger.warning(f"Overlap: key={key} pos={pos0} < last_idx={last_idx}, skip")
            skipped += 1
            continue

        if pos0 > len(content):
            logger.warning(f"Out of bounds: key={key} pos={pos0} > len={len(content)}, skip")
            skipped += 1
            continue

        # 验证原文匹配
        orig_len = len(original)
        actual = content[pos0:pos0 + orig_len]
        if actual != original:
            # 尝试小范围搜索（±5字符）
            found = False
            for offset in range(-5, 6):
                check_pos = pos0 + offset
                if check_pos < last_idx or check_pos < 0:
                    continue
                if content[check_pos:check_pos + orig_len] == original:
                    pos0 = check_pos
                    found = True
                    break
            if not found:
                logger.warning(f"Mismatch: key={key[:50]} pos={pos0}")
                logger.warning(f"  expect: {repr(original[:50])}")
                logger.warning(f"  actual: {repr(actual[:50])}")
                skipped += 1
                continue

        # 拼接: [last_idx, pos0) + translation
        parts.append(content[last_idx:pos0])
        parts.append(translation)
        last_idx = pos0 + orig_len
        applied += 1

    # 收尾
    parts.append(content[last_idx:])

    result = ''.join(parts)

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(result)

    logger.info(f"Applied {applied}/{applied + skipped} entries, output: {output_path}")
    return applied


def main():
    import argparse
    parser = argparse.ArgumentParser(description="TiTS JS translation replacer")
    parser.add_argument("source", help="Original JS source file")
    parser.add_argument("trans", help="Translation JSON file")
    parser.add_argument("-o", "--output", help="Output JS file", required=True)
    args = parser.parse_args()
    replace_file(args.source, args.trans, args.output)


if __name__ == '__main__':
    main()
