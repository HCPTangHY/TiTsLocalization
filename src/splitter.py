#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TiTS webpack chunk splitter

将 webpack chunk 按 module 边界拆分成独立文件。
对于巨型 module，再按 class/_inherits 和 clearOutput 边界做二/三级拆分。
所有 sub-part 记录相对于源文件的绝对偏移（offset_in_source）。
"""

import os
import re
import json
import hashlib
import argparse


def find_modules(content: str):
    """找所有 webpack module 边界，返回 [(module_id, start, end), ...]"""
    pattern = re.compile(r'(\d+):\([a-z,]+\)=>\{')
    matches = list(pattern.finditer(content))
    if not matches:
        return []
    modules = []
    for i, m in enumerate(matches):
        mid = m.group(1)
        start = m.start()
        if i + 1 < len(matches):
            end_region = matches[i + 1].start()
        else:
            end_region = len(content)
        modules.append((mid, start, end_region))
    return modules


def _find_scene_boundaries(content):
    boundaries = []
    for m in re.finditer(r'clearOutput\(\)', content):
        pos = m.start()
        semi = content.rfind(';', max(0, pos - 500), pos)
        if semi >= 0:
            boundaries.append(semi + 1)
        else:
            boundaries.append(pos)
    return boundaries


def split_large_module(content, module_id, max_chunk_kb=500):
    """
    拆分巨型 module。
    返回 [(sub_id, sub_content, internal_offset), ...]
    internal_offset 是 sub_content 在 content 中的起始偏移。
    """
    if len(content) < max_chunk_kb * 1024:
        return [(module_id, content, 0)]

    inherits = [m.start() for m in re.finditer(r'\(0,[a-zA-Z_$]+\.Z\)\(o,e\)', content)]

    if len(inherits) < 2:
        return _split_by_scenes(content, module_id, max_chunk_kb)

    boundaries = [0]
    for pos in inherits:
        search_start = max(0, pos - 2000)
        region = content[search_start:pos]
        last_var = region.rfind(';var ')
        if last_var >= 0:
            boundary = search_start + last_var + 1
        else:
            last_var = region.rfind('var ')
            if last_var >= 0:
                boundary = search_start + last_var
            else:
                boundary = pos
        if boundary > boundaries[-1]:
            boundaries.append(boundary)
    boundaries.append(len(content))

    merged = [boundaries[0]]
    for b in boundaries[1:]:
        if b - merged[-1] < 50 * 1024 and b != boundaries[-1]:
            continue
        merged.append(b)

    parts = []
    for i in range(len(merged) - 1):
        sub_start = merged[i]
        sub_end = merged[i + 1]
        sub_content = content[sub_start:sub_end]
        sub_id = f"{module_id}_part{i}"

        if len(sub_content) > max_chunk_kb * 1024:
            sub_parts = _split_by_scenes(sub_content, sub_id, max_chunk_kb)
            for sp_id, sp_content, sp_offset in sub_parts:
                parts.append((sp_id, sp_content, sub_start + sp_offset))
        else:
            parts.append((sub_id, sub_content, sub_start))

    return parts


def _split_by_scenes(content, base_id, max_chunk_kb):
    """用 clearOutput() 做场景切分。返回 [(id, content, internal_offset), ...]"""
    scene_bounds = _find_scene_boundaries(content)
    if not scene_bounds:
        return _split_by_size(content, base_id, max_chunk_kb)

    scene_bounds = sorted(set(scene_bounds))
    all_bounds = [0] + scene_bounds + [len(content)]

    max_bytes = max_chunk_kb * 1024
    merged = [0]
    for b in all_bounds[1:]:
        if b - merged[-1] >= max_bytes:
            merged.append(b)
    if merged[-1] != len(content):
        merged.append(len(content))

    if len(merged) <= 2:
        return _split_by_size(content, base_id, max_chunk_kb)

    parts = []
    for i in range(len(merged) - 1):
        start = merged[i]
        sub = content[start:merged[i + 1]]
        parts.append((f"{base_id}_s{i}", sub, start))
    return parts


def _split_by_size(content, module_id, max_chunk_kb):
    """按固定大小切分。返回 [(id, content, internal_offset), ...]"""
    max_bytes = max_chunk_kb * 1024
    parts = []
    pos = 0
    part_idx = 0
    while pos < len(content):
        end = min(pos + max_bytes, len(content))
        if end < len(content):
            semicolon = content.rfind(';', pos, end)
            if semicolon > pos:
                end = semicolon + 1
        parts.append((f"{module_id}_part{part_idx}", content[pos:end], pos))
        pos = end
        part_idx += 1
    return parts


# ================================================================
#   语义命名
# ================================================================

_SKIP_NAMES = {
    'PlayerCharacter', 'Boolean', 'Reflect', 'Error', 'Object', 'Array',
    'String', 'Number', 'Function', 'Promise', 'Arguments', 'Proxy',
    'TypeError', 'RangeError', 'SyntaxError', 'Math', 'Date', 'RegExp',
    'JSON', 'Map', 'Set', 'WeakMap', 'WeakSet', 'Symbol', 'Infinity',
    'NaN', 'undefined', 'null', 'console', 'window', 'document',
    'ARMOR', 'SHIELDS', 'Next',
}


def _extract_semantic_name(content):
    classes = re.findall(r'"([A-Z][a-zA-Z]{3,40})"', content[:3000])
    classes = [c for c in classes if c not in _SKIP_NAMES]
    if len(classes) >= 2:
        return f"{classes[0]}_{classes[1]}"
    elif len(classes) == 1:
        return classes[0]
    return ""


def _extract_subpart_name(content):
    shows = re.findall(r'showName\("([^"]+)"\)', content)
    if shows:
        from collections import Counter
        c = Counter(shows)
        name = c.most_common(1)[0][0]
        return re.sub(r'[^a-zA-Z0-9]+', '_', name).strip('_')
    return ""


def _content_hash(content, length=6):
    return hashlib.sha1(content.encode('utf-8', errors='replace')).hexdigest()[:length]


def _make_unique_filename(base_name, content, used_names):
    if not base_name:
        base_name = _content_hash(content)
    candidate = base_name
    if candidate in used_names:
        h = _content_hash(content, 4)
        candidate = f"{base_name}_{h}"
    while candidate in used_names:
        h = _content_hash(content + str(len(used_names)), 6)
        candidate = f"{base_name}_{h}"
    used_names.add(candidate)
    return candidate


def split_chunk(file_path, output_dir, max_module_kb=500):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    basename = os.path.splitext(os.path.basename(file_path))[0]
    modules = find_modules(content)

    if not modules:
        out_path = os.path.join(output_dir, basename, '_raw.js')
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return [out_path]

    print(f"  Found {len(modules)} webpack modules")

    output_files = []
    chunk_dir = os.path.join(output_dir, basename)
    os.makedirs(chunk_dir, exist_ok=True)

    manifest = {
        "source": os.path.basename(file_path),
        "source_size": len(content),
        "modules": [],
    }

    used_names = set()

    for mid, mod_start, mod_end in modules:
        module_content = content[mod_start:mod_end]
        module_size = len(module_content)

        parts = split_large_module(module_content, mid, max_module_kb)

        for sub_id, sub_content, internal_offset in parts:
            # 绝对偏移 = module在源文件的起始 + sub-part在module内的偏移
            absolute_offset = mod_start + internal_offset

            # 语义命名
            if len(parts) == 1:
                sem = _extract_semantic_name(sub_content)
            else:
                sem = _extract_subpart_name(sub_content)
                if not sem:
                    sem = _extract_semantic_name(sub_content)

            filename = _make_unique_filename(sem, sub_content, used_names)
            out_path = os.path.join(chunk_dir, f"{filename}.js")

            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(sub_content)
            output_files.append(out_path)

            manifest["modules"].append({
                "id": sub_id,
                "semantic_name": filename,
                "original_module": mid,
                "file": f"{filename}.js",
                "size": len(sub_content),
                "offset_in_source": absolute_offset,
            })

        if len(parts) > 1:
            print(f"    Module {mid}: {module_size // 1024}KB -> {len(parts)} sub-parts")

    manifest_path = os.path.join(chunk_dir, "_manifest.json")
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"  Output: {chunk_dir}/ ({len(output_files)} files)")
    return output_files


def main():
    parser = argparse.ArgumentParser(description="Split TiTS webpack chunks into modules")
    parser.add_argument("input", nargs='+', help="Input JS file(s)")
    parser.add_argument("-o", "--output-dir", default="split_output", help="Output directory")
    parser.add_argument("--max-module-kb", type=int, default=500, help="Max module size before sub-splitting (KB)")
    args = parser.parse_args()
    for path in args.input:
        print(f"Splitting {path}...")
        split_chunk(path, args.output_dir, args.max_module_kb)


if __name__ == "__main__":
    main()
