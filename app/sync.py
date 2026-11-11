"""Sync between computers through a cloud folder (OneDrive, Dropbox or any folder both computers share).

* Closing the app saves an encrypted copy of the data to  <cloud>/RM Store Apps/<app>/data.rmsync
  plus a small latest.json saying which computer saved it and when.
* Opening the app on the other computer sees the newer copy and offers to load it.
* If both computers changed something since they last synced, the person chooses - nothing is overwritten silently,
  and a safety backup is always made first.
* The cloud only ever holds encrypted data. The first load on a computer asks for the backup password once;
  after that both computers share the data key and no password is needed.
Each computer keeps its own settings for this in sync.json next to its data (not inside the synced data).
"""
import datetime
import hashlib
import json
import os
import platform
import secrets
import shutil

from .config import APP_SHORT, APP_VERSION, data_dir

DATA_FILE = "data.rmsync"
MANIFEST = "latest.json"
IN_USE = "in-use.json"
DATA_KINDS_EXCLUDED = ("login", "security", "backup", "system", "export", "sync")
_state_path = None            # tests point this somewhere else


def state_path():
    return _state_path or os.path.join(data_dir(), "sync.json")


def load_state():
    try:
        with open(state_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(d):
    tmp = state_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, state_path())


def computer_name():
    return os.environ.get("COMPUTERNAME") or platform.node() or "this computer"


# ---------------------------------------------------------------- cloud folders on this computer
def cloud_folders():
    """[(label, path)] for OneDrive / Dropbox folders found on this computer."""
    out, seen = [], set()

    def add(label, p):
        if p and os.path.isdir(p) and os.path.normcase(os.path.abspath(p)) not in seen:
            seen.add(os.path.normcase(os.path.abspath(p)))
            out.append((label, p))
    for var, label in (("OneDriveConsumer", "OneDrive"), ("OneDrive", "OneDrive"),
                       ("OneDriveCommercial", "OneDrive (work)")):
        add(label, os.environ.get(var))
    add("OneDrive", os.path.join(os.path.expanduser("~"), "OneDrive"))
    for base in (os.environ.get("APPDATA"), os.environ.get("LOCALAPPDATA")):
        if not base:
            continue
        try:
            with open(os.path.join(base, "Dropbox", "info.json"), encoding="utf-8") as f:
                info = json.load(f)
            for kind, label in (("personal", "Dropbox"), ("business", "Dropbox (business)")):
                add(label, (info.get(kind) or {}).get("path"))
        except (OSError, ValueError, AttributeError):
            pass
    add("Dropbox", os.path.join(os.path.expanduser("~"), "Dropbox"))
    return out


def folder_label(folder):
    f = (folder or "").lower()
    return "OneDrive" if "onedrive" in f else "Dropbox" if "dropbox" in f else "the sync folder"


def sync_dir(state=None):
    folder = (state or load_state()).get("folder")
    return os.path.join(folder, "RM Store Apps", APP_SHORT) if folder else None


# ---------------------------------------------------------------- what changed where
def fingerprint(db):
    """Changes to the store's data since the last sync show up as a different number here
    (sign-ins, exports and backups don't count)."""
    q = "SELECT COALESCE(MAX(id),0) FROM activity WHERE kind NOT IN (%s)" % ",".join("?" * len(DATA_KINDS_EXCLUDED))
    return int(db.conn.execute(q, DATA_KINDS_EXCLUDED).fetchone()[0])


def manifest(state=None):
    d = sync_dir(state)
    if not d:
        return None
    try:
        with open(os.path.join(d, MANIFEST), encoding="utf-8") as f:
            m = json.load(f)
        return m if isinstance(m, dict) and m.get("version") else None
    except (OSError, ValueError):
        return None


def status(db):
    """One of: off, no_folder, first (nothing synced yet), same, remote_newer, local_newer, both_changed."""
    st = load_state()
    if not st.get("folder"):
        return {"kind": "off", "state": st}
    if not os.path.isdir(st["folder"]):
        return {"kind": "no_folder", "state": st}
    m = manifest(st)
    local_changed = fingerprint(db) != st.get("fp")
    if not m:
        return {"kind": "first", "state": st, "local_changed": True}
    remote_changed = m["version"] != st.get("have")
    if m.get("computer_key") == st.get("me") and not remote_changed:
        remote_changed = False
    kind = ("both_changed" if remote_changed and local_changed and st.get("have") else
            "remote_newer" if remote_changed else "local_newer" if local_changed else "same")
    return {"kind": kind, "state": st, "manifest": m, "local_changed": local_changed}


def other_open(state=None):
    """{'computer', 'since'} when the app looks open on another computer right now (within 12 hours)."""
    d = sync_dir(state)
    if not d:
        return None
    try:
        with open(os.path.join(d, IN_USE), encoding="utf-8") as f:
            u = json.load(f)
        me = (state or load_state()).get("me")
        since = datetime.datetime.fromisoformat(u["since"])
        if u.get("computer_key") != me and datetime.datetime.now() - since < datetime.timedelta(hours=12):
            return u
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def mark_open(on=True):
    st = load_state()
    d = sync_dir(st)
    if not d or not os.path.isdir(st.get("folder", "")):
        return
    p = os.path.join(d, IN_USE)
    try:
        if on:
            os.makedirs(d, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"computer": computer_name(), "computer_key": st.get("me"),
                           "since": datetime.datetime.now().isoformat(timespec="seconds")}, f)
        else:
            with open(p, encoding="utf-8") as f:
                if json.load(f).get("computer_key") == st.get("me"):
                    os.remove(p)
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------- set up / push / pull
def set_folder(folder):
    st = load_state()
    st["folder"] = folder or ""
    st.setdefault("me", secrets.token_hex(8))
    if not folder:
        st.pop("have", None)
    save_state(st)
    return st


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def push(db):
    """Saves this computer's data to the sync folder."""
    st = load_state()
    d = sync_dir(st)
    if not d:
        raise ValueError("Sync isn't set up.")
    if not os.path.isdir(st["folder"]):
        raise ValueError(f"The sync folder isn't available:\n{st['folder']}")
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, f".{DATA_FILE}.{secrets.token_hex(4)}.tmp")
    db.backup(tmp)
    final = os.path.join(d, DATA_FILE)
    os.replace(tmp, final)
    m = {"version": secrets.token_hex(8), "based_on": st.get("have"), "computer": computer_name(),
         "computer_key": st.setdefault("me", secrets.token_hex(8)),
         "saved_at": datetime.datetime.now().isoformat(timespec="seconds"), "app_version": APP_VERSION,
         "schema": db.schema_version(), "size": os.path.getsize(final), "sha256": _sha(final)}
    mt = os.path.join(d, f".{MANIFEST}.tmp")
    with open(mt, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=1)
    os.replace(mt, os.path.join(d, MANIFEST))
    st.update(have=m["version"], fp=fingerprint(db), last=m["saved_at"], last_from=m["computer"], last_dir="saved")
    save_state(st)
    db.log(f"Synced: saved this computer's data to {folder_label(st['folder'])}", "system", "sync")
    return m


def pull(db, ask_password=None):
    """Loads the other computer's data from the sync folder (a safety backup of this computer's data comes first)."""
    st = load_state()
    m = manifest(st)
    if not m:
        raise ValueError("There's no synced data in the sync folder yet.")
    if (m.get("schema") or 0) > db.schema_version():
        raise ValueError(f"{m.get('computer', 'The other computer')} has a newer version of the app "
                         f"({m.get('app_version', '?')}). Update this computer first (About > Check for updates).")
    path = os.path.join(sync_dir(st), DATA_FILE)
    if not os.path.exists(path) or os.path.getsize(path) != m.get("size") or _sha(path) != m.get("sha256"):
        raise ValueError(f"{folder_label(st['folder'])} is still downloading the newest data. "
                         "Wait a minute and try again (Backup > Sync now).")
    safety = db.load_from_other_computer(path, ask_password)
    st.update(have=m["version"], fp=fingerprint(db), last=datetime.datetime.now().isoformat(timespec="seconds"),
              last_from=m.get("computer"), last_dir="loaded")
    save_state(st)
    db.log(f"Synced: loaded data saved on {m.get('computer')} at {m.get('saved_at')}", "system", "sync")
    return safety


def when(iso):
    try:
        t = datetime.datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return iso or "?"
    day = "today" if t.date() == datetime.date.today() else t.strftime("%b %d")
    return f"{day} {t.strftime('%I:%M %p').lstrip('0')}"


def describe(db):
    s = status(db)
    st, m = s["state"], s.get("manifest") or {}
    k = s["kind"]
    if k == "off":
        return "Off - this computer's data stays on this computer."
    where = folder_label(st.get("folder"))
    if k == "no_folder":
        return f"PROBLEM: the sync folder isn't available ({st.get('folder')})."
    if k == "first":
        return f"On ({where}). Nothing synced yet - this computer's data is saved there when you close the app."
    last = (f"Last sync {when(st.get('last'))} ({st.get('last_dir', '')}"
            + (f" from {st.get('last_from')}" if st.get("last_dir") == "loaded" else "") + ").")
    return {"same": f"On ({where}). Up to date. {last}",
            "local_newer": f"On ({where}). This computer has new changes - saved there when you close the app. {last}",
            "remote_newer": f"On ({where}). NEWER data from {m.get('computer')} ({when(m.get('saved_at'))}) - "
                            "click Sync now to load it.",
            "both_changed": f"On ({where}). Both computers have changes - click Sync now to choose."}[k]


def clear_folder(st=None):
    """Removes this app's synced copy (used by tests and 'start over')."""
    d = sync_dir(st)
    if d and os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)
