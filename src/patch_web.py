#!/usr/bin/env python3
"""Patch Electron index.html for web compatibility.

Usage:
  python patch_web.py <index.html path> [version]
"""
import sys


def patch_html(html_path, version="unknown"):
    with open(html_path) as f:
        html = f.read()

    # 1. Replace Electron custom protocol with relative path
    html = html.replace('<base href="tits://titsapp">', '<base href="./">')

    # 2. Inject electronAPI shim before first <script> tag
    shim = (
        "<script>window.electronAPI={"
        "getStoreValue:()=>Promise.resolve(null),"
        "setStoreValue:()=>Promise.resolve(),"
        "getAppVersion:()=>Promise.resolve('" + version + "-web'),"
        "onNavigate:()=>{},"
        "platform:'browser',"
        "checkManifest:()=>Promise.resolve(null),"
        "deleteFile:()=>Promise.resolve(),"
        "downloadImages:()=>Promise.resolve(),"
        "downloadImagesCancel:()=>{},"
        "forceReload:()=>location.reload(),"
        # Web builds do not have Electron file APIs, so save/load now use
        # localStorage with the same tits_ prefix for both write and read.
        # The rest of the shim is intentionally unchanged to avoid changing
        # unrelated browser compatibility behavior in this patch.
        "loadFile: (n) => Promise.resolve(localStorage.getItem('tits_'+n)),"
        "notifyDownloadComplete:()=>{},"
        "notifyDownloadProgress:()=>{},"
        "notifyHasImagesAvailable:()=>{},"
        "onTriggerRedraw:()=>{},"
        "saveFile: (n,d) => { try{localStorage.setItem('tits_'+n,d)}catch(e){} return Promise.resolve() }"
        "};</script>"
    )
    html = html.replace("<script defer=", shim + "<script defer=", 1)

    with open(html_path, "w") as f:
        f.write(html)

    # Verify
    ok = True
    if 'base href="./"' in html:
        print("base href patched")
    else:
        print("WARN: base href patch failed")
        ok = False
    if "window.electronAPI" in html:
        print("electronAPI shim injected")
    else:
        print("WARN: shim injection failed")
        ok = False
    return ok


if __name__ == "__main__":
    html_path = sys.argv[1]
    version = sys.argv[2] if len(sys.argv) > 2 else "unknown"
    if not patch_html(html_path, version):
        sys.exit(1)
