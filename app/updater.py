"""Check for updates: looks for a newer setup file on the public downloads page on GitHub, downloads it,
checks it, and runs it. Only the installer is public; the program's code stays private.
Works without internet too - it just says it couldn't check."""
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from .config import APP_VERSION

DOWNLOADS_REPO = "mrobin1629-create/store-apps-downloads"
ASSET_PREFIX = "BevMargin-Setup-"
APP_KEY = "BevMargin"
MANIFEST = f"https://raw.githubusercontent.com/{DOWNLOADS_REPO}/main/latest.json"
API = f"https://api.github.com/repos/{DOWNLOADS_REPO}/releases?per_page=30"
PAGE = f"https://github.com/{DOWNLOADS_REPO}"


def _ver(text):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


MAX_SETUP_BYTES = 500 * 1024 * 1024


def allowed_url(url):
    """Updates are only ever fetched over HTTPS from GitHub (no other website, no local network addresses)."""
    try:
        u = urllib.parse.urlsplit(url or "")
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    return (u.scheme == "https" and not u.username and not u.password and u.port in (None, 443)
            and (host in ("github.com", "api.github.com") or host.endswith(".githubusercontent.com")))


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl):
            raise urllib.error.URLError(f"Blocked redirect to {urllib.parse.urlsplit(newurl).hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context()), _SafeRedirect)


def _open(url, timeout):
    if not allowed_url(url):
        raise IOError("Update address refused (not a GitHub HTTPS address).")
    req = urllib.request.Request(url, headers={"User-Agent": f"BevMargin/{APP_VERSION}",
                                               "Accept": "application/vnd.github+json"})
    return _opener.open(req, timeout=timeout)


def _from_manifest(timeout):
    """latest.json on the downloads page: {"BevMargin": {"version", "file", "url", "size", "sha256", "notes"}}."""
    with _open(MANIFEST, timeout) as r:
        e = json.load(r).get(APP_KEY)
    if not e or not e.get("url"):
        return None
    return {"version": _ver(e.get("version")), "name": e.get("file") or os.path.basename(e["url"]), "url": e["url"],
            "size": e.get("size"), "sha256": e.get("sha256"), "notes": (e.get("notes") or "").strip()}


def find_latest(timeout=6):
    """Returns {'version', 'name', 'url', 'size', 'sha256', 'notes'} for the newest setup file, or None.
    Looks at latest.json on the downloads page and at its Releases; the higher version wins."""
    found, errors = [], []
    for source in (_from_manifest, _from_releases):
        try:
            r = source(timeout)
            if r:
                found.append(r)
        except Exception as ex:
            errors.append(ex)
    if not found and errors and len(errors) == 2:
        raise errors[0]
    return max(found, key=lambda x: x["version"]) if found else None


def _from_releases(timeout):
    with _open(API, timeout) as r:
        releases = json.load(r)
    best = None
    for rel in releases:
        if rel.get("draft"):
            continue
        for a in rel.get("assets", []):
            name = a.get("name", "")
            if name.startswith(ASSET_PREFIX) and name.lower().endswith(".exe"):
                v = _ver(name)
                if not best or v > best["version"]:
                    digest = (a.get("digest") or "")
                    best = {"version": v, "name": name, "url": a["browser_download_url"], "size": a.get("size"),
                            "sha256": digest.split(":", 1)[1] if digest.startswith("sha256:") else None,
                            "notes": (rel.get("body") or "").strip()}
    return best


def newer_available(timeout=6):
    latest = find_latest(timeout)
    if latest and latest["version"] > _ver(APP_VERSION):
        latest["text"] = ".".join(map(str, latest["version"]))
        return latest
    return None


def download(info, progress=None):
    """Downloads the setup file to a new private temp folder and checks its size / SHA-256. Returns the file path."""
    want = (info.get("sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", want):
        raise IOError("This update has no safety fingerprint, so it wasn't downloaded. "
                      "Please download the setup file from the downloads page instead.")
    name = os.path.basename(info.get("name") or "")
    if not re.fullmatch(re.escape(ASSET_PREFIX) + r"[0-9.]+\.exe", name):
        raise IOError("Unexpected update file name.")
    if (info.get("size") or 0) > MAX_SETUP_BYTES:
        raise IOError("The update file is unexpectedly large.")
    path = os.path.join(tempfile.mkdtemp(prefix="update-"), name)
    h = hashlib.sha256()
    done = 0
    with _open(info["url"], 60) as r, open(path, "wb") as f:
        total = info.get("size") or int(r.headers.get("Content-Length") or 0)
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            if done + len(chunk) > MAX_SETUP_BYTES:
                f.close()
                os.remove(path)
                raise IOError("The update file is unexpectedly large.")
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if info.get("size") and done != info["size"]:
        os.remove(path)
        raise IOError("The download was incomplete. Please try again.")
    if h.hexdigest() != want:
        os.remove(path)
        raise IOError("The downloaded file didn't pass the safety check. Please try again.")
    return path


def run_installer(path):
    if sys.platform.startswith("win"):
        subprocess.Popen([path], close_fds=True)
    else:
        raise OSError("Updates install on Windows only.")
