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
import time
import argparse
import shutil

# 确保 src/ 在 path 上
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from splitter import split_chunk
from scanner import extract_file
from replacer import replace_file, parse_pos


def get_project_root():
    """获取项目根目录（src/ 的上一级）"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_dir(base, version, subdir):
    path = os.path.join(base, subdir, version)
    os.makedirs(path, exist_ok=True)
    return path


# ================================================================
#   Step 1: Split
# ================================================================

def step_split(root, version):
    """拆分 source/<version>/*.js → split/<version>/"""
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


# ================================================================
#   Step 2: Extract
# ================================================================

def step_extract(root, version):
    """提取 split/<version>/*/*.js → pz_origin/<version>/"""
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
        # 去掉 hash 后缀作为文件夹名
        import re
        chunk_name = re.sub(r'\.[a-f0-9]+$', '', chunk_name_raw)
        out_dir = os.path.join(pz_dir, chunk_name)

        manifest_path = os.path.join(chunk_dir, '_manifest.json')
        manifest = None
        if os.path.isfile(manifest_path):
            with open(manifest_path) as mf:
                manifest = json.load(mf)

        for js_file in sorted(glob.glob(os.path.join(chunk_dir, '*.js'))):
            js_name = os.path.basename(js_file)
            module_name = os.path.splitext(js_name)[0]

            # 从 manifest 获取 offset
            offset = 0
            if manifest:
                for mod in manifest.get('modules', []):
                    if mod.get('file') == js_name:
                        offset = mod.get('offset_in_source', 0)
                        break

            with open(js_file, 'r', encoding='utf-8') as f:
                content = f.read()

            entries = extract_file(js_file, content, pos_offset=offset)

            # 跳过空结果
            if not entries:
                continue

            # 按需创建输出目录
            os.makedirs(out_dir, exist_ok=True)

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


# ================================================================
#   Step 3: Replace
# ================================================================

def step_replace(root, version):
    """替换 source/<version>/*.js + trans_origin/<version>/ → dist/<version>/"""
    source_dir = os.path.join(root, 'source', version)
    trans_dir = os.path.join(root, 'trans_origin', version)
    dist_dir = resolve_dir(root, version, 'dist')
    pz_dir = os.path.join(root, 'pz_origin', version)

    if not os.path.isdir(source_dir):
        print(f"ERROR: source directory not found: {source_dir}")
        return False

    if not os.path.isdir(trans_dir):
        print(f"ERROR: trans_origin directory not found: {trans_dir}")
        return False

    # 以 pz_origin 为权威：遍历 pz_origin 词条，从 trans_origin 查翻译填入
    # 构建翻译查找表：key -> translation/context
    trans_lookup = {}
    if os.path.isdir(trans_dir):
        for tj in glob.glob(os.path.join(trans_dir, '**', '*.json'), recursive=True):
            with open(tj) as f:
                for e in json.load(f):
                    if e.get('translation'):
                        trans_lookup[e['key']] = e
        print(f"  Loaded {len(trans_lookup)} translated entries from trans_origin/{version}")
    else:
        print(f"  ERROR: trans_origin/{version} not found")
        return False

    if not os.path.isdir(pz_dir):
        print(f"  WARNING: pz_origin/{version} not found, using trans_origin keys directly")

    print(f"\n{'='*60}")
    print(f"  REPLACE: pz_origin as authority, trans_origin as translations")
    print(f"{'='*60}")

    total_applied = 0
    total_matched = 0

    # 遍历每个源文件
    for src_file in sorted(glob.glob(os.path.join(source_dir, '*.js'))):
        src_name = os.path.basename(src_file)
        # 找到对应的 chunk name（去掉hash）
        import re
        chunk_name = re.sub(r'\.[a-f0-9]+\.js$', '', src_name)
        if chunk_name == src_name.replace('.js', ''):
            chunk_name = src_name.replace('.js', '')

        # 优先用 pz_origin 作为权威词条来源
        pz_chunk_dir = os.path.join(pz_dir, chunk_name)
        if os.path.isdir(pz_dir) and os.path.isdir(pz_chunk_dir):
            authority_dir = pz_chunk_dir
        else:
            # fallback: 用 trans_origin
            authority_dir = os.path.join(trans_dir, chunk_name)

        if not os.path.isdir(authority_dir):
            out_path = os.path.join(dist_dir, src_name)
            shutil.copy2(src_file, out_path)
            continue

        # 遍历权威词条，从翻译查找表里填入翻译
        all_entries = []
        for pf in sorted(glob.glob(os.path.join(authority_dir, '*.json'))):
            with open(pf) as f:
                entries = json.load(f)
            for e in entries:
                tr = trans_lookup.get(e['key'])
                if tr and tr.get('translation'):
                    # 用 pz_origin 的 POS/context，填入 trans 的翻译
                    entry = dict(e)
                    entry['translation'] = tr['translation']
                    all_entries.append(entry)
                    total_matched += 1

        if not all_entries:
            out_path = os.path.join(dist_dir, src_name)
            shutil.copy2(src_file, out_path)
            continue

        # 写临时合并JSON
        import tempfile
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

    # 复制非JS文件（如果有）
    for other in glob.glob(os.path.join(source_dir, '*')):
        if not other.endswith('.js'):
            name = os.path.basename(other)
            out = os.path.join(dist_dir, name)
            if os.path.isfile(other):
                shutil.copy2(other, out)

    print(f"\n  Total: {total_matched} matched, {total_applied} applied")
    return True


# ================================================================
#   Main
# ================================================================

def main():
    parser = argparse.ArgumentParser(
        description="TiTS Localization Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pipeline.py -v 0.9.159 split        # 拆分 JS 文件
  python pipeline.py -v 0.9.159 extract      # 提取词条
  python pipeline.py -v 0.9.159 all          # split + extract
  python pipeline.py -v 0.9.159 replace      # 回写翻译
"""
    )
    parser.add_argument('-v', '--version', required=True, help='Game version (e.g. 0.9.159)')
    parser.add_argument('steps', nargs='+', choices=['split', 'extract', 'replace', 'all'],
                        help='Pipeline steps to run')
    parser.add_argument('--root', default=None, help='Project root (default: auto-detect)')
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
