#!/usr/bin/env python3
"""Patch Electron index.html for Cordova APK compatibility.

Usage:
  python patch_apk.py <index.html path> [version]
"""
import re
import sys

CORDOVA_SCRIPT = '<script src="cordova.js"></script>'


def ensure_cordova_script(html):
    """Ensure cordova.js is the first script in <head>."""
    # APK builds run inside Cordova, so cordova.js must be present before the
    # shim and before the game bundle. Existing cordova.js tags are removed and
    # reinserted once to keep the patch idempotent without duplicating scripts.
    cordova_re = re.compile(
        r"\s*<script\b(?=[^>]*\bsrc=[\"']cordova\.js[\"'])[^>]*>\s*</script>",
        re.IGNORECASE,
    )
    html = cordova_re.sub("", html)

    head_match = re.search(r"<head\b[^>]*>", html, re.IGNORECASE)
    if head_match:
        return html[:head_match.end()] + CORDOVA_SCRIPT + html[head_match.end():]

    script_match = re.search(r"<script\b", html, re.IGNORECASE)
    if script_match:
        return html[:script_match.start()] + CORDOVA_SCRIPT + html[script_match.start():]

    return CORDOVA_SCRIPT + html


def build_shim(version):
    # APK save/load keeps the Electron-facing API name but changes the storage
    # backend to the Cordova file plugin, which is the persistent file interface
    # available to the Android package.
    return (
        "<script>window.electronAPI={"
        "getStoreValue:()=>Promise.resolve(null),"
        "setStoreValue:()=>Promise.resolve(),"
        "getAppVersion:()=>Promise.resolve('" + version + "-apk'),"
        "onNavigate:()=>{},"
        "platform:'android',"
        "checkManifest:()=>Promise.resolve(null),"
        "deleteFile:()=>Promise.resolve(),"
        "downloadImages:()=>Promise.resolve(),"
        "downloadImagesCancel:()=>{},"
        "forceReload:()=>location.reload(),"
        "loadFile: (n) => {return new Promise((resolve) => {"
        "resolveLocalFileSystemURL(cordova.file.dataDirectory, (dir) => {"
        "dir.getFile(n, {create:false}, (fileEntry) => {"
        "fileEntry.file((file) => {"
        "const reader = new FileReader();"
        "reader.onloadend = () => resolve(reader.result);"
        "reader.readAsText(file);"
        "});"
        "}, () => resolve(null));"
        "}, () => resolve(null));"
        "});},"
        "notifyDownloadComplete:()=>{},"
        "notifyDownloadProgress:()=>{},"
        "notifyHasImagesAvailable:()=>{},"
        "onTriggerRedraw:()=>{},"
        "saveFile: (n,d) => {return new Promise((resolve,reject) => {"
        "resolveLocalFileSystemURL(cordova.file.dataDirectory, (dir) => {"
        "dir.getFile(n, {create:true}, (fileEntry) => {"
        "fileEntry.createWriter((writer) => {"
        "writer.onwriteend = () => resolve();"
        "writer.onerror = (e) => reject(e);"
        "writer.write(new Blob([d]));"
        "});"
        "}, reject);"
        "}, reject);"
        "});}"
        "};</script>"
    )


def inject_shim(html, shim):
    # The game bundle is loaded with a defer script in the Electron index.html.
    # The shim is inserted before that bundle so game code can call
    # window.electronAPI during startup. If the defer marker is absent, the shim
    # is placed after cordova.js so Cordova remains the first script in <head>.
    if "<script defer=" in html:
        return html.replace("<script defer=", shim + "<script defer=", 1)
    if CORDOVA_SCRIPT in html:
        return html.replace(CORDOVA_SCRIPT, CORDOVA_SCRIPT + shim, 1)

    script_match = re.search(r"<script\b", html, re.IGNORECASE)
    if script_match:
        return html[:script_match.start()] + shim + html[script_match.start():]

    return html + shim


def patch_html(html_path, version="unknown"):
    with open(html_path) as f:
        html = f.read()

    # APK assets are loaded from the local package, so the Electron custom
    # protocol must be replaced with a relative base path.
    html = html.replace('<base href="tits://titsapp">', '<base href="./">')
    html = ensure_cordova_script(html)
    html = inject_shim(html, build_shim(version))

    with open(html_path, "w") as f:
        f.write(html)

    ok = True
    if 'base href="./"' in html:
        print("base href patched")
    elif 'base href' not in html:
        print("base href not present (OK for native APK)")
    else:
        print("WARN: base href patch failed")
        ok = False
    if 'src="cordova.js"' in html:
        print("cordova.js script ensured")
    else:
        print("WARN: cordova.js injection failed")
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
