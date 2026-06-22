#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TiTS JS 词条提取入口"""

import os
import sys
import json
import time
import argparse
from scanner import extract_file


def run(input_path: str, output_path: str, pos_offset: int = 0):
    print(f"Reading {input_path}...")
    with open(input_path, 'r', encoding='utf-8') as f:
        content = f.read()
    print(f"  File size: {len(content)} bytes ({len(content)/1048576:.1f}MB)")
    if pos_offset:
        print(f"  POS offset: +{pos_offset}")

    t0 = time.time()
    entries = extract_file(input_path, content, pos_offset=pos_offset)
    elapsed = time.time() - t0
    print(f"  Extracted {len(entries)} entries in {elapsed:.2f}s")

    # 统计分类
    cats = {}
    for e in entries:
        cat = e['key'].split('|')[0]
        cats[cat] = cats.get(cat, 0) + 1
    print(f"  Categories:")
    for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"    {cat}: {count}")

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    print(f"  Output: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="TiTS JS string extractor")
    parser.add_argument("input", help="Input JS file")
    parser.add_argument("-o", "--output", help="Output JSON file", default=None)
    parser.add_argument("--pos-offset", type=int, default=0, help="POS offset in source file")
    parser.add_argument("--manifest", help="Manifest JSON to auto-resolve offset")
    parser.add_argument("--module-file", help="Module filename (for manifest lookup)")
    args = parser.parse_args()

    offset = args.pos_offset

    # 从manifest自动解析offset
    if args.manifest and args.module_file:
        import json as _json
        with open(args.manifest) as mf:
            manifest = _json.load(mf)
        for mod in manifest.get('modules', []):
            if mod.get('file') == args.module_file:
                offset = mod.get('offset_in_source', 0)
                break

    output = args.output or args.input + ".extracted.json"
    run(args.input, output, pos_offset=offset)


if __name__ == "__main__":
    main()
