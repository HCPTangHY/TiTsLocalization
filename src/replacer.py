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
    """从 context 解析 <<VARS:var0=a|var1=Ot.m>> 映射表。
    兼容旧格式逗号分隔（当值里不含逗号时）。"""
    if not context:
        return {}
    m = re.search(r'<<VARS:([^>]+)>>', context)
    if not m:
        return {}
    raw = m.group(1)
    # 新格式用 | 分隔（值里可能含逗号）
    if '|' in raw:
        pairs = raw.split('|')
    else:
        # 旧格式兼容：找 ,varN= 边界手动切分
        pairs = []
        start = 0
        for i in range(len(raw)):
            if raw[i] == ',' and raw[i+1:i+4].startswith('var') and '=' in raw[i+1:i+8]:
                pairs.append(raw[start:i])
                start = i + 1
        pairs.append(raw[start:])
    result = {}
    for pair in pairs:
        eq = pair.find('=')
        if eq > 0:
            result[pair[:eq]] = pair[eq + 1:]
    return result


def resolve_vars(text: str, var_map: dict) -> str:
    """将 {var0} {var1} 占位符替换为真实变量名。"""
    for k, v in var_map.items():
        text = text.replace('{' + k + '}', v)
    return text


def check_quote_safety(original: str, translation: str, wrapper: str = None) -> bool:
    """检查译文的引号结构是否安全。

    如果提供了 wrapper（JS 字符串的包裹引号类型），只检查 wrapper 引号的变化。
    非 wrapper 引号属于文本内容，变化不影响 JS 语法结构。
    如果没有 wrapper 信息，退回检查两种引号（保守策略）。
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

    # 状态机检查：模拟 JS 引擎解析引号状态
    # 初始状态 inside=True（POS-1 处的 wrapper 引号已打开字符串）
    # 分别扫描 original 和 translation，记录各自的结束状态
    # 两者结束状态必须一致 → 替换后源码尾部的引号状态不被破坏
    check_chars = [wrapper] if wrapper in ('"', "'") else ['"', "'"]
    for ch in check_chars:
        def scan_end_state(text):
            inside = True  # 从引号内部开始
            i = 0
            while i < len(text):
                if text[i] == '\\':
                    i += 2
                    continue
                if text[i] == ch:
                    inside = not inside
                i += 1
            return inside
        if scan_end_state(original) != scan_end_state(translation):
            return False

    # 检查半角引号夹在汉字之间 — 译者误用半角引号当中文标点
    # 汉字"汉字 或 汉字" 汉字 或 汉字 "汉字（两侧都是汉字才拦）
    # 汉字"+var 这种一侧是 JS 符号的不拦
    import re
    CJK = '\u4e00-\u9fff\u3000-\u303f\uff00-\uffef'
    if re.search(rf'[{CJK}]\s*["\']\s*[{CJK}]', translation):
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
        # 找 wrapper 引号：从 pos0 往前扫到最近的引号字符
        wrapper = None
        for i in range(pos0 - 1, max(0, pos0 - 20), -1):
            if content[i] in ('"', "'"):
                wrapper = content[i]
                break
        # 引号安全检查（只检查 wrapper 引号）
        if not check_quote_safety(original, translation, wrapper):
            logger.warning(f"Quote mismatch (wrapper={wrapper}), skip: key={key[:60]}")
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
