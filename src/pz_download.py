#!/usr/bin/env python3
"""Download translated entries from ParaTranz.

Environment variables:
  PARATRANZ_TOKEN   - API token (required)
  PARATRANZ_PROJECT - Project ID (required)

Usage:
  python pz_download.py --output trans_origin/0.9.159/
"""

import os, sys, json, re, time, zipfile, io, argparse, shutil

try:
    import requests
except ImportError:
    print("pip install requests"); sys.exit(1)

PZ_API = "https://paratranz.cn/api"


def pz_get(path, token, **kw):
    headers = {"Authorization": token}
    r = requests.get(f"{PZ_API}{path}", headers=headers, **kw)
    r.raise_for_status()
    return r


def pz_post(path, token, **kw):
    headers = {"Authorization": token}
    r = requests.post(f"{PZ_API}{path}", headers=headers, **kw)
    r.raise_for_status()
    return r


def trigger_export(project_id, token):
    """Trigger artifact build and wait for completion."""
    print("Triggering ParaTranz export...")
    pz_post(f"/projects/{project_id}/artifacts", token)
    for i in range(60):
        time.sleep(5)
        r = pz_get(f"/projects/{project_id}/artifacts", token)
        data = r.json()
        if data.get("status") == 1:
            return data
        print(f"  Waiting... ({i*5}s)")
    raise TimeoutError("Export timed out after 5 minutes")


def download_artifact(project_id, token, output_dir):
    """Download and extract the artifact zip."""
    print("Downloading artifact...")
    r = pz_get(f"/projects/{project_id}/artifacts/download", token, stream=True)

    buf = io.BytesIO()
    for chunk in r.iter_content(8192):
        buf.write(chunk)
    buf.seek(0)

    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    with zipfile.ZipFile(buf) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            # Normalize path
            name = info.filename
            parts = name.split("/")
            # Strip PZ export prefix (utf8/ or raw/)
            if parts[0] in ("utf8", "raw"):
                parts = parts[1:]
            # Strip version prefix (e.g. 0.9.159/) if PZ uses it for organization
            if parts and re.match(r'^\d+\.\d+\.\d+$', parts[0]):
                parts = parts[1:]
            rel = "/".join(parts)
            if not rel or not rel.endswith(".json"):
                continue

            out_path = os.path.join(output_dir, rel)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with zf.open(info) as src, open(out_path, "wb") as dst:
                dst.write(src.read())

    file_count = sum(1 for _ in _walk_json(output_dir))
    print(f"Extracted {file_count} JSON files to {output_dir}")
    return file_count


def _walk_json(d):
    for root, dirs, files in os.walk(d):
        for f in files:
            if f.endswith(".json"):
                yield os.path.join(root, f)


def count_translated(output_dir):
    """Count entries with non-empty translation field."""
    total = 0
    translated = 0
    for fp in _walk_json(output_dir):
        with open(fp, encoding="utf-8") as f:
            entries = json.load(f)
        total += len(entries)
        translated += sum(1 for e in entries if e.get("translation"))
    return total, translated


def main():
    p = argparse.ArgumentParser(description="Download translations from ParaTranz")
    p.add_argument("--output", required=True, help="Output directory")
    p.add_argument("--project", default=os.environ.get("PARATRANZ_PROJECT"))
    p.add_argument("--token", default=os.environ.get("PARATRANZ_TOKEN"))
    p.add_argument("--trigger-export", action="store_true", help="Trigger a fresh export before downloading (default: use latest existing)")
    args = p.parse_args()

    if not args.project or not args.token:
        print("ERROR: set PARATRANZ_PROJECT and PARATRANZ_TOKEN env vars")
        sys.exit(1)

    if args.trigger_export:
        trigger_export(args.project, args.token)
    else:
        print("Using latest existing artifact (PZ auto-builds hourly)")

    download_artifact(args.project, args.token, args.output)
    total, translated = count_translated(args.output)

    print(f"\nTotal: {total} entries")
    print(f"Translated: {translated} ({100*translated/max(total,1):.1f}%)")

    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a") as f:
            f.write(f"total_entries={total}\ntranslated_entries={translated}\n")


if __name__ == "__main__":
    main()
