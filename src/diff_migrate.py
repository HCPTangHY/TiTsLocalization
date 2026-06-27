#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重提取 + Diff + 翻译迁移脚本

用法:
  python src/diff_migrate.py -v 0.9.160                    # 只 diff，不迁移
  python src/diff_migrate.py -v 0.9.160 --migrate           # diff + 迁移翻译
  python src/diff_migrate.py -v 0.9.160 --migrate --apply   # diff + 迁移 + 写入 pz_origin

流程:
  1. 记录当前 pz_origin 的 key set
  2. 运行 pipeline split + extract (覆盖 pz_origin)
  3. 对比新旧 key set，输出 diff 报告
  4. 如指定 --migrate，从 PZ 最新导出或指定目录迁移翻译
  5. 如指定 --apply，将迁移结果写入 pz_origin
"""

import os
import sys
import json
import glob
import argparse
import shutil
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def key_base(k):
    """去掉 key 末尾的 hash"""
    parts = k.rsplit('|', 1)
    return parts[0] if len(parts) > 1 else k


def load_keys(pz_dir):
    """加载 pz_origin 目录下所有词条的 key -> original 映射"""
    keys = {}
    for f in glob.glob(os.path.join(pz_dir, '**', '*.json'), recursive=True):
        with open(f) as fh:
            for e in json.load(fh):
                keys[e['key']] = e.get('original', '')[:60]
    return keys


def load_translations(trans_dir):
    """加载翻译目录下所有有翻译的词条"""
    trans = {}
    for f in glob.glob(os.path.join(trans_dir, '**', '*.json'), recursive=True):
        with open(f) as fh:
            for e in json.load(fh):
                t = e.get('translation', '').strip()
                if t:
                    trans[e['key']] = t
    return trans


def diff_report(old_keys, new_keys):
    """输出 diff 报告"""
    added = set(new_keys) - set(old_keys)
    removed = set(old_keys) - set(new_keys)
    unchanged = set(old_keys) & set(new_keys)

    print(f"\n{'='*50}")
    print(f"  DIFF REPORT")
    print(f"{'='*50}")
    print(f"  Old: {len(old_keys)} keys")
    print(f"  New: {len(new_keys)} keys")
    print(f"  Added:     {len(added)}")
    print(f"  Removed:   {len(removed)}")
    print(f"  Unchanged: {len(unchanged)}")
    print(f"  Net:       {len(new_keys) - len(old_keys):+d}")

    if added:
        print(f"\n  Added by category:")
        cats = Counter(k.split('|')[0] for k in added)
        for c, n in cats.most_common(20):
            print(f"    {c}: +{n}")

    if removed:
        print(f"\n  Removed by category:")
        cats = Counter(k.split('|')[0] for k in removed)
        for c, n in cats.most_common(20):
            print(f"    {c}: -{n}")

    return added, removed, unchanged


def migrate_translations(pz_dir, trans, new_keys):
    """迁移翻译到新 pz_origin"""
    # 构建 new base -> key 索引
    new_base_idx = {}
    for key in new_keys:
        b = key_base(key)
        if b not in new_base_idx:
            new_base_idx[b] = key

    # 加载所有新 entries
    all_data = {}  # filepath -> [entries]
    entry_idx = {}  # key -> (filepath, index)
    for f in glob.glob(os.path.join(pz_dir, '**', '*.json'), recursive=True):
        with open(f) as fh:
            entries = json.load(fh)
        all_data[f] = entries
        for i, e in enumerate(entries):
            entry_idx[e['key']] = (f, i)

    # 精确匹配
    exact = 0
    for key, t in trans.items():
        if key in entry_idx:
            fpath, idx = entry_idx[key]
            all_data[fpath][idx]['translation'] = t
            all_data[fpath][idx]['stage'] = 1
            exact += 1

    # fuzzy 匹配
    fuzzy = 0
    for old_key, t in trans.items():
        if old_key in entry_idx:
            continue
        b = key_base(old_key)
        if b in new_base_idx:
            nk = new_base_idx[b]
            if nk in entry_idx:
                fpath, idx = entry_idx[nk]
                if not all_data[fpath][idx].get('translation'):
                    all_data[fpath][idx]['translation'] = t
                    all_data[fpath][idx]['stage'] = 1
                    fuzzy += 1

    print(f"\n  Migration: exact={exact}, fuzzy={fuzzy}, total={exact+fuzzy}")

    # 检查 removed 里有翻译的
    removed_keys = set(trans.keys()) - set(entry_idx.keys())
    removed_translated = len(removed_keys)
    removed_recoverable = sum(1 for k in removed_keys if key_base(k) in new_base_idx)
    print(f"  Lost translations: {removed_translated - removed_recoverable} (recoverable: {removed_recoverable})")

    return all_data


def main():
    parser = argparse.ArgumentParser(description='重提取 + Diff + 翻译迁移')
    parser.add_argument('-v', '--version', required=True, help='Game version')
    parser.add_argument('--root', default=None, help='Project root')
    parser.add_argument('--migrate', action='store_true', help='迁移翻译')
    parser.add_argument('--apply', action='store_true', help='写入迁移结果到 pz_origin')
    parser.add_argument('--trans-dir', default=None, help='翻译目录（默认从 PZ 导出）')
    args = parser.parse_args()

    # 找项目根目录
    root = args.root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pz_dir = os.path.join(root, 'pz_origin', args.version)

    # Step 1: 记录旧 keys
    print("Step 1: Loading current pz_origin keys...")
    if os.path.isdir(pz_dir):
        old_keys = load_keys(pz_dir)
        print(f"  Current: {len(old_keys)} keys")
    else:
        old_keys = {}
        print(f"  No existing pz_origin for {args.version}")

    # Step 2: 运行 pipeline
    print("\nStep 2: Running pipeline split + extract...")
    from pipeline import step_split, step_extract
    # 清空旧数据
    split_dir = os.path.join(root, 'split', args.version)
    if os.path.isdir(split_dir):
        shutil.rmtree(split_dir)
    if os.path.isdir(pz_dir):
        shutil.rmtree(pz_dir)

    if not step_split(root, args.version):
        print("ERROR: split failed")
        return 1
    if not step_extract(root, args.version):
        print("ERROR: extract failed")
        return 1

    # Step 3: Diff
    print("\nStep 3: Diff...")
    new_keys = load_keys(pz_dir)
    added, removed, unchanged = diff_report(old_keys, new_keys)

    # Step 4: 迁移翻译
    if args.migrate or args.apply:
        print("\nStep 4: Migrating translations...")
        if args.trans_dir:
            trans_source = args.trans_dir
        else:
            # 从 PZ 导出
            trans_source = os.path.join(root, 'data', 'tmp', 'pz_latest')
            if not os.path.isdir(trans_source):
                print(f"  ERROR: Translation source not found: {trans_source}")
                print(f"  Run PZ export first or use --trans-dir")
                return 1

        trans = load_translations(trans_source)
        print(f"  Loaded {len(trans)} translations from {trans_source}")

        # 检查 removed 中有翻译的
        removed_with_trans = sum(1 for k in removed if k in trans)
        print(f"  Removed keys with translations: {removed_with_trans}")

        all_data = migrate_translations(pz_dir, trans, new_keys)

        if args.apply:
            print("\n  Writing migrated translations to pz_origin...")
            for fpath, entries in all_data.items():
                with open(fpath, 'w', encoding='utf-8') as f:
                    json.dump(entries, f, ensure_ascii=False)
            translated = sum(
                1 for entries in all_data.values()
                for e in entries if e.get('translation', '').strip()
            )
            print(f"  Done: {translated} translated entries written")
        else:
            print("\n  Dry run — use --apply to write changes")

    print("\nDone.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
