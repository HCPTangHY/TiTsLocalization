#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TiTS 本地化 Pipeline

完整流程：
  1. split   — 将 source/<version>/*.js 拆分到 split/<version>/
  2. extract — 从拆分文件提取词条到 pz_origin/<version>/
  3. replace — 将翻译回写到源文件，输出到 dist/<version>/

目录结构：
  project/
  ├── src/                    # 工具代码
  ├── source/<version>/       # 原始 JS 文件（content_*.js, main.js）
  ├── split/<version>/        # 拆分后的子模块（中间产物）
  ├── pz_origin/<version>/    # 提取的词条 JSON（上传 ParaTranz）
  ├── trans_origin/<version>/ # 翻译后的词条 JSON（从 ParaTranz 下载）
  └── dist/<version>/         # 替换后的 JS 文件（最终产物）
"""

import os
import sys
import json
import glob
import re
import time
import argparse
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from splitter import split_chunk
from scanner import extract_file
from replacer import replace_file, parse_pos


def get_project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_dir(base, version, subdir):
    path = os.path.join(base, subdir, version)
    os.makedirs(path, exist_ok=True)
    return path


def step_split(root, version):
    source_dir = os.path.join(root, 'source', version)
    split_dir = resolve_dir(root, version, 'split')

    if not os.path.isdir(source_dir):
        print(f"ERROR: source directory not found: {source_dir}")
        return False

    js_files = sorted(glob.glob(os.path.join(source_dir, '*.js')))
    if not js_files:
        print(f"ERROR: no JS files in {source_dir}")
        return False

    print(f"\n{'='*60}")
    print(f"  SPLIT: {len(js_files)} files -> {split_dir}")
    print(f"{'='*60}")

    for f in js_files:
        print(f"\nSplitting {os.path.basename(f)}...")
        split_chunk(f, split_dir)

    return True


def step_extract(root, version):
    split_dir = os.path.join(root, 'split', version)
    pz_dir = resolve_dir(root, version, 'pz_origin')

    if not os.path.isdir(split_dir):
        print(f"ERROR: split directory not found: {split_dir}")
        return False

    print(f"\n{'='*60}")
    print(f"  EXTRACT: {split_dir} -> {pz_dir}")
    print(f"{'='*60}")

    total_entries = 0
    total_files = 0

    for chunk_dir in sorted(glob.glob(os.path.join(split_dir, '*/'))):
        chunk_name_raw = os.path.basename(chunk_dir.rstrip('/'))
        chunk_name = re.sub(r'\.[a-f0-9]+$', '', chunk_name_raw)
        out_dir = os.path.join(pz_dir, chunk_name)
        os.makedirs(out_dir, exist_ok=True)

        manifest_path = os.path.join(chunk_dir, '_manifest.json')
        manifest = None
        if os.path.isfile(manifest_path):
            with open(manifest_path) as mf:
                manifest = json.load(mf)

        for js_file in sorted(glob.glob(os.path.join(chunk_dir, '*.js'))):
            js_name = os.path.basename(js_file)
            module_name = os.path.splitext(js_name)[0]

            offset = 0
            if manifest:
                for mod in manifest.get('modules', []):
                    if mod.get('file') == js_name:
                        offset = mod.get('offset_in_source', 0)
                        break

            with open(js_file, 'r', encoding='utf-8') as f:
                content = f.read()

            entries = extract_file(js_file, content, pos_offset=offset)

            if not entries:
                continue

            out_path = os.path.join(out_dir, f"{module_name}.json")
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(entries, f, ensure_ascii=False, indent=2)

            total_entries += len(entries)
            total_files += 1

        chunk_entries = sum(
            len(json.load(open(f)))
            for f in glob.glob(os.path.join(out_dir, '*.json'))
        ) if os.path.isdir(out_dir) else 0
        print(f"  {chunk_name}: {chunk_entries} entries")

    print(f"\n  Total: {total_entries} entries / {total_files} files")
    return True


def step_replace(root, version):
    source_dir = os.path.join(root, 'source', version)
    trans_dir = os.path.join(root, 'trans_origin', version)
    dist_dir = resolve_dir(root, version, 'dist')

    if not os.path.isdir(source_dir):
        print(f"ERROR: source directory not found: {source_dir}")
        return False

    if not os.path.isdir(trans_dir):
        print(f"ERROR: trans_origin directory not found: {trans_dir}")
        return False

    print(f"\n{'='*60}")
    print(f"  REPLACE: {trans_dir} -> {dist_dir}")
    print(f"{'='*60}")

    total_applied = 0

    for src_file in sorted(glob.glob(os.path.join(source_dir, '*.js'))):
        src_name = os.path.basename(src_file)
        chunk_name = re.sub(r'\.[a-f0-9]+\.js$', '', src_name)
        if chunk_name == src_name.replace('.js', ''):
            chunk_name = src_name.replace('.js', '')

        trans_chunk_dir = os.path.join(trans_dir, chunk_name)
        if not os.path.isdir(trans_chunk_dir):
            out_path = os.path.join(dist_dir, src_name)
            shutil.copy2(src_file, out_path)
            continue

        all_entries = []
        for tj in sorted(glob.glob(os.path.join(trans_chunk_dir, '*.json'))):
            with open(tj) as f:
                entries = json.load(f)
            all_entries.extend([e for e in entries if e.get('translation')])

        if not all_entries:
            out_path = os.path.join(dist_dir, src_name)
            shutil.copy2(src_file, out_path)
            continue

        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as tf:
            json.dump(all_entries, tf, ensure_ascii=False)
            tmp_path = tf.name

        out_path = os.path.join(dist_dir, src_name)
        try:
            applied = replace_file(src_file, tmp_path, out_path)
            total_applied += applied
            print(f"  {src_name}: {applied} replacements")
        finally:
            os.unlink(tmp_path)

    for other in glob.glob(os.path.join(source_dir, '*')):
        if not other.endswith('.js'):
            name = os.path.basename(other)
            out = os.path.join(dist_dir, name)
            if os.path.isfile(other):
                shutil.copy2(other, out)

    print(f"\n  Total applied: {total_applied} replacements")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="TiTS Localization Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pipeline.py -v 0.9.159 split
  python pipeline.py -v 0.9.159 extract
  python pipeline.py -v 0.9.159 all          # split + extract
  python pipeline.py -v 0.9.159 replace
"""
    )
    parser.add_argument('-v', '--version', required=True)
    parser.add_argument('steps', nargs='+', choices=['split', 'extract', 'replace', 'all'])
    parser.add_argument('--root', default=None)
    args = parser.parse_args()

    root = args.root or get_project_root()
    steps = args.steps
    if 'all' in steps:
        steps = ['split', 'extract']

    t0 = time.time()

    for step in steps:
        if step == 'split':
            if not step_split(root, args.version):
                return 1
        elif step == 'extract':
            if not step_extract(root, args.version):
                return 1
        elif step == 'replace':
            if not step_replace(root, args.version):
                return 1

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s")
    return 0


if __name__ == '__main__':
    sys.exit(main())
