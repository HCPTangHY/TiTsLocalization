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


def parse_pos(context):
    if not context:
        return -1
    m = re.search(r'<<POS:(\d+)>>', context)
    if m:
        return int(m.group(1)) - 1
    m2 = re.search(r'&lt;&lt;POS:(\d+)&gt;&gt;', context)
    if m2:
        return int(m2.group(1)) - 1
    return -1


def replace_file(source_path, trans_json_path, output_path):
    with open(source_path, 'r', encoding='utf-8') as f:
        content = f.read()

    with open(trans_json_path, 'r', encoding='utf-8') as f:
        entries = json.load(f)

    items = []
    for e in entries:
        translation = e.get('translation', '')
        if not translation:
            continue
        pos0 = parse_pos(e.get('context', ''))
        if pos0 < 0:
            continue
        original = e.get('original', '')
        if not original:
            continue
        items.append((pos0, original, translation, e.get('key', '')))

    if not items:
        logger.info("No translated entries, copying original")
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return 0

    items.sort(key=lambda x: x[0])

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

        orig_len = len(original)
        actual = content[pos0:pos0 + orig_len]
        if actual != original:
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

        parts.append(content[last_idx:pos0])
        parts.append(translation)
        last_idx = pos0 + orig_len
        applied += 1

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
