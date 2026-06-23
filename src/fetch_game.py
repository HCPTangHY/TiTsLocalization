#!/usr/bin/env python3
"""Download TiTS game files from fenoxo.com.

Modes:
  --check-only  : HEAD request to detect version, compare with cache
  --output DIR  : Download Electron Linux package, extract JS to DIR

Outputs (GITHUB_OUTPUT):
  version     : Game version string (e.g. 0.9.159)
  main_hash   : Hash suffix from main.{hash}.js filename
  has_update  : 'true' or 'false' (check-only mode)
  file_count  : Number of JS files extracted

Usage:
  python fetch_game.py --check-only
  python fetch_game.py --output game_source/
  python fetch_game.py --output game_source/ --force
"""

import os
import re
import sys
import json
import argparse
import tarfile
import tempfile

try:
    import requests
except ImportError:
    print("ERROR: pip install requests")
    sys.exit(1)

BASE = "https://www.fenoxo.com/play"
ELECTRON_WIN_URL = f"{BASE}/latest_tits_electron.php"
ELECTRON_LINUX_URL = f"{BASE}/latest_tits_electron_linux.php"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def gh_output(key, value):
    """Write key=value to GITHUB_OUTPUT if available."""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")
    print(f"  [{key}={value}]")


def check_version():
    """HEAD request to get version from content-disposition header."""
    r = requests.head(
        ELECTRON_WIN_URL,
        headers={"User-Agent": UA},
        allow_redirects=True,
        timeout=30,
    )
    r.raise_for_status()
    cd = r.headers.get("content-disposition", "")
    m = re.search(r"filename=TiTS-public-([\d.]+)-win\.zip", cd)
    return m.group(1) if m else None


def download_electron_linux(output_dir):
    """Download Electron Linux tar.gz, extract JS files from resources/app/."""
    os.makedirs(output_dir, exist_ok=True)

    print("Downloading Electron Linux package...")
    r = requests.get(
        ELECTRON_LINUX_URL,
        headers={"User-Agent": UA},
        stream=True,
        timeout=600,
    )
    r.raise_for_status()

    total = int(r.headers.get("content-length", 0))
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        downloaded = 0
        for chunk in r.iter_content(65536):
            tmp.write(chunk)
            downloaded += len(chunk)
            if total:
                print(
                    f"\r  {downloaded / 1048576:.0f}MB / {total / 1048576:.0f}MB"
                    f" ({downloaded * 100 // total}%)",
                    end="",
                    flush=True,
                )
        tmp_path = tmp.name
    print()

    print("Extracting JS files from resources/app/ ...")
    extracted = {}
    with tarfile.open(tmp_path, "r:gz") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            # Only keep JS and index.html from resources/app/
            if "/resources/app/" not in member.name:
                continue
            basename = os.path.basename(member.name)
            if not (basename.endswith(".js") or basename == "index.html"):
                continue
            fobj = tf.extractfile(member)
            if not fobj:
                continue
            content = fobj.read()
            out_path = os.path.join(output_dir, basename)
            with open(out_path, "wb") as f:
                f.write(content)
            extracted[basename] = len(content)
            size_str = f"{len(content) / 1048576:.1f}MB" if len(content) > 102400 else f"{len(content) / 1024:.0f}KB"
            print(f"  \u2713 {basename} ({size_str})")

    os.unlink(tmp_path)
    return extracted


def detect_version(source_dir):
    """Extract game version (e.g. 0.9.159) from main.js module."""
    for fn in os.listdir(source_dir):
        if fn.startswith("main.") and fn.endswith(".js"):
            with open(os.path.join(source_dir, fn), encoding="utf-8") as f:
                text = f.read()
            # Short module: e.exports={i8:"0.9.159"}
            m = re.search(r'e\.exports=\{[a-zA-Z0-9]+:"(0\.\d+\.\d+)"\}', text)
            if m:
                return m.group(1)
            # Fallback
            m = re.search(r'"(0\.\d+\.\d+)"', text)
            if m:
                return m.group(1)
    return "unknown"


def get_main_hash(source_dir):
    """Get hash suffix from main.{hash}.js filename."""
    for fn in os.listdir(source_dir):
        m = re.match(r"main\.([a-f0-9]+)\.js", fn)
        if m:
            return m.group(1)
    return "unknown"


def main():
    p = argparse.ArgumentParser(description="Download TiTS game files")
    p.add_argument("--check-only", action="store_true", help="Only check version")
    p.add_argument("--output", help="Output directory for JS files")
    p.add_argument("--force", action="store_true", help="Ignore version cache")
    p.add_argument(
        "--cache-file",
        default=".version_cache/tits_version.json",
        help="Version cache file path",
    )
    args = p.parse_args()

    # -- Check-only mode --
    if args.check_only:
        version = check_version()
        print(f"Remote version: {version}")
        gh_output("version", version or "unknown")

        has_update = "true"
        if not args.force and os.path.exists(args.cache_file):
            try:
                with open(args.cache_file) as f:
                    cache = json.load(f)
                if cache.get("version") == version:
                    has_update = "false"
                    print("No update (version unchanged)")
            except Exception:
                pass

        if has_update == "true":
            print("Update available")

        gh_output("has_update", has_update)
        return 0

    # -- Download mode --
    if not args.output:
        p.error("--output is required when not using --check-only")

    downloaded = download_electron_linux(args.output)
    if not downloaded:
        print("ERROR: no files extracted")
        return 1

    version = detect_version(args.output)
    main_hash = get_main_hash(args.output)

    # Write metadata
    with open(os.path.join(args.output, ".version"), "w") as f:
        f.write(version)
    with open(os.path.join(args.output, ".main_hash"), "w") as f:
        f.write(main_hash)

    # Update cache
    os.makedirs(os.path.dirname(args.cache_file) or ".", exist_ok=True)
    with open(args.cache_file, "w") as f:
        json.dump({"version": version, "main_hash": main_hash}, f)

    # Outputs
    gh_output("version", version)
    gh_output("main_hash", main_hash)
    gh_output("file_count", str(len(downloaded)))

    total_mb = sum(downloaded.values()) / 1048576
    print(f"\nVersion:   {version}")
    print(f"Main hash: {main_hash}")
    print(f"Files:     {len(downloaded)}")
    print(f"Total:     {total_mb:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
