#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上传 pz_origin 到 ParaTranz 脚本

用法:
  python src/upload_pz.py -v 0.9.160 --dry-run    # 预览上传计划
  python src/upload_pz.py -v 0.9.160               # 执行上传

行为:
  1. 获取 PZ 上已有文件列表
  2. 对比本地 pz_origin 文件
  3. 已有文件 → PUT 更新
  4. 新文件 → POST 创建（带正确路径前缀）
  5. 绝不删除任何 PZ 上的文件
"""

import os
import sys
import glob
import json
import time
import argparse
import requests

TOKEN = '9d1a82e831df26c4c956398408086de0'
PROJECT_ID = 19507
BASE = 'https://paratranz.cn/api'
HEADERS = {'Authorization': f'Bearer {TOKEN}'}


def get_pz_files():
    """获取 PZ 上所有文件的 name -> id 映射"""
    r = requests.get(f'{BASE}/projects/{PROJECT_ID}/files', headers=HEADERS)
    r.raise_for_status()
    files = r.json()
    remaining = r.headers.get('X-RateLimit-Remaining', '?')
    print(f"  PZ files: {len(files)} (rate limit remaining: {remaining})")
    return {f['name']: f['id'] for f in files}


def rate_limit_wait(response):
    """如果接近 rate limit，等待重置"""
    remaining = int(response.headers.get('X-RateLimit-Remaining', 100))
    if remaining < 5:
        reset = int(response.headers.get('X-RateLimit-Reset', 0))
        wait = max(1, reset - int(time.time()))
        print(f"  ⏳ Rate limit ({remaining} remaining), waiting {wait}s...")
        time.sleep(wait)


def upload_files(root, version, dry_run=False):
    """上传 pz_origin 文件到 PZ"""
    pz_dir = os.path.join(root, 'pz_origin', version)
    if not os.path.isdir(pz_dir):
        print(f"ERROR: pz_origin directory not found: {pz_dir}")
        return 1

    # 获取 PZ 文件映射
    print("Step 1: Fetching PZ file list...")
    pz_map = get_pz_files()

    # 收集本地文件
    print("\nStep 2: Scanning local files...")
    local_files = sorted(glob.glob(os.path.join(pz_dir, '**', '*.json'), recursive=True))
    print(f"  Local files: {len(local_files)}")

    # 分类
    to_update = []  # (local_path, pz_name, pz_id)
    to_create = []  # (local_path, pz_name)

    for lf in local_files:
        rel = os.path.relpath(lf, os.path.dirname(pz_dir))  # version/xxx/yyy.json
        if rel in pz_map:
            to_update.append((lf, rel, pz_map[rel]))
        else:
            to_create.append((lf, rel))

    # 统计
    print(f"\nStep 3: Upload plan")
    print(f"  PUT update (existing): {len(to_update)}")
    print(f"  POST create (new):     {len(to_create)}")

    # PZ 上有但本地没有的
    local_rels = set(os.path.relpath(lf, os.path.dirname(pz_dir)) for lf in local_files)
    pz_only = set(pz_map.keys()) - local_rels
    pz_only_with_path = [p for p in pz_only if '/' in p]
    pz_only_no_path = [p for p in pz_only if '/' not in p]
    if pz_only_with_path:
        print(f"  ⚠ PZ-only (with path, orphaned): {len(pz_only_with_path)}")
    if pz_only_no_path:
        print(f"  ⚠ PZ-only (no path, garbage):    {len(pz_only_no_path)}")

    if dry_run:
        print("\n  DRY RUN — no changes made")
        if to_create:
            print(f"  New files to create:")
            for _, name in to_create[:10]:
                print(f"    {name}")
            if len(to_create) > 10:
                print(f"    ... and {len(to_create) - 10} more")
        return 0

    # 执行上传
    print(f"\nStep 4: Uploading...")
    put_ok = 0
    put_fail = 0
    post_ok = 0
    post_fail = 0

    # PUT 更新
    for i, (lf, name, fid) in enumerate(to_update):
        with open(lf, 'rb') as f:
            r = requests.post(
                f'{BASE}/projects/{PROJECT_ID}/files/{fid}',
                headers=HEADERS,
                files={'file': (name, f, 'application/json')}
            )
        if r.status_code == 200:
            put_ok += 1
        else:
            put_fail += 1
            if put_fail <= 5:
                print(f"  PUT FAIL [{r.status_code}] {name}: {r.text[:80]}")
        rate_limit_wait(r)
        if (i + 1) % 300 == 0:
            print(f"  PUT progress: {i+1}/{len(to_update)} (ok={put_ok})")

    if to_update:
        print(f"  PUT done: {put_ok} ok, {put_fail} fail")

    # POST 创建
    for i, (lf, name) in enumerate(to_create):
        with open(lf, 'rb') as f:
            r = requests.post(
                f'{BASE}/projects/{PROJECT_ID}/files',
                headers=HEADERS,
                files={'file': (name, f, 'application/json')}
            )
        if r.status_code in (200, 201):
            post_ok += 1
        else:
            post_fail += 1
            if post_fail <= 5:
                print(f"  POST FAIL [{r.status_code}] {name}: {r.text[:80]}")
        rate_limit_wait(r)
        if (i + 1) % 100 == 0:
            print(f"  POST progress: {i+1}/{len(to_create)} (ok={post_ok})")

    if to_create:
        print(f"  POST done: {post_ok} ok, {post_fail} fail")

    print(f"\n  Total: PUT {put_ok}/{len(to_update)}, POST {post_ok}/{len(to_create)}")
    return 0


def main():
    parser = argparse.ArgumentParser(description='上传 pz_origin 到 ParaTranz')
    parser.add_argument('-v', '--version', required=True, help='Game version')
    parser.add_argument('--root', default=None, help='Project root')
    parser.add_argument('--dry-run', action='store_true', help='预览上传计划，不执行')
    args = parser.parse_args()

    root = args.root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return upload_files(root, args.version, dry_run=args.dry_run)


if __name__ == '__main__':
    sys.exit(main())
