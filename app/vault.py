"""Encrypted data file and backups.

* The database is a SQLCipher file (AES-256): opened in Notepad, a hex editor or another SQLite tool it is noise.
* Its random 256-bit key is kept in <name>.key next to it, locked to the signed-in Windows user with Windows DPAPI,
  so nothing has to be typed day to day and a copied/stolen data file can't be read.
* The same key is also stored locked with the store's *backup password* (PBKDF2 + AES-GCM). That is what lets
  a backup, or a data folder copied to a new computer / USB stick, be opened somewhere else.
* Backup files are a small header (key fingerprint + password-locked key) followed by the encrypted database.
* Old unencrypted data files and backups are converted automatically the first time a new version opens them,
  and old unencrypted backup files can still be restored.
"""
import base64
import contextlib
import datetime
import glob
import hashlib
import json
import os
import secrets
import shutil
import struct
import sys
import tempfile

from sqlcipher3 import dbapi2 as sql

from .config import backup_dir
from .security import MAX_BACKUP_BYTES, check_file

try:                                    # SQLCipher prints decrypt errors to the console otherwise
    sql.connect(":memory:").execute("PRAGMA cipher_log_level = NONE").fetchall()
except Exception:
    pass

MAGIC = b"RMSTORE-ENCRYPTED-BACKUP-1\n"
PLAIN_HEADER = b"SQLite format 3\x00"
PW_ROUNDS = 600_000
_ENTROPY = b"RM-store-apps data key v1"
BACKUP_KEEP = 30


class NeedPassword(Exception):
    """The backup password is needed (data moved from another computer / Windows account)."""


class WrongPassword(NeedPassword):
    pass


# ------------------------------------------------------------------ Windows DPAPI
def _dpapi(data, protect):
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(b):
        buf = ctypes.create_string_buffer(b, len(b))
        return BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(BLOB), wintypes.LPCWSTR if protect else ctypes.c_void_p, ctypes.POINTER(BLOB),
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(BLOB)]
    fn.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    inp, _b1 = blob(data)
    ent, _b2 = blob(_ENTROPY)
    out = BLOB()
    ok = fn(ctypes.byref(inp), "RM Store Apps" if protect else None, ctypes.byref(ent), None, None,
            0x1, ctypes.byref(out))                                   # 0x1 = CRYPTPROTECT_UI_FORBIDDEN
    if not ok:
        raise OSError(f"Windows couldn't {'lock' if protect else 'unlock'} the data key (error {ctypes.GetLastError()}).")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def _protect(key):
    if sys.platform.startswith("win"):
        return {"by": "dpapi", "data": _b64(_dpapi(key, True))}
    return {"by": "none", "data": _b64(key)}          # Mac/Linux are only used for development and tests


def _unprotect(entry):
    raw = _unb64(entry["data"])
    if entry.get("by") == "dpapi":
        if not sys.platform.startswith("win"):
            raise OSError("Locked by Windows")
        return _dpapi(raw, False)
    if entry.get("by") == "none" and not sys.platform.startswith("win"):
        return raw
    raise OSError("This key can't be used here")


# ------------------------------------------------------------------ helpers
def _b64(b):
    return base64.b64encode(b).decode()


def _unb64(s):
    return base64.b64decode(s.encode())


def key_id(key):
    return hashlib.sha256(b"rm-key-id" + key).hexdigest()[:16]


def wrap_with_password(key, password):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    k = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PW_ROUNDS, 32)
    return {"salt": _b64(salt), "rounds": PW_ROUNDS, "nonce": _b64(nonce),
            "ct": _b64(AESGCM(k).encrypt(nonce, key, b"rm-backup-key"))}


def unwrap_with_password(w, password):
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        rounds = int(w["rounds"])
        if not 1000 <= rounds <= 5_000_000:
            raise ValueError
        k = hashlib.pbkdf2_hmac("sha256", (password or "").encode(), _unb64(w["salt"]), rounds, 32)
        return AESGCM(k).decrypt(_unb64(w["nonce"]), _unb64(w["ct"]), b"rm-backup-key")
    except (InvalidTag, KeyError, ValueError, TypeError):
        raise WrongPassword("That backup password is not correct.")


def _atomic_write(path, data):
    tmp = f"{path}.tmp-{secrets.token_hex(4)}"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def is_plain(path):
    try:
        with open(path, "rb") as f:
            return f.read(16) == PLAIN_HEADER
    except OSError:
        return False


def connect(path, key):
    """Opens an encrypted database. Raises sql.DatabaseError if the key is wrong or the file isn't one."""
    c = sql.connect(path)
    try:
        c.execute(f"PRAGMA key = \"x'{key.hex()}'\"")
        c.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except Exception:
        c.close()
        raise
    c.row_factory = sql.Row
    return c


def export_to(src_conn, dest, key):
    """Copies everything in src_conn (encrypted or not) into a new encrypted file `dest`."""
    if os.path.exists(dest):
        os.remove(dest)
    src_conn.commit()
    src_conn.execute(f"ATTACH DATABASE ? AS rm_out KEY \"x'{key.hex()}'\"", (dest,))
    try:
        src_conn.execute("SELECT sqlcipher_export('rm_out')").fetchall()
    finally:
        src_conn.execute("DETACH DATABASE rm_out")


# ------------------------------------------------------------------ key file
class KeyFile:
    def __init__(self, db_file):
        self.path = os.path.splitext(db_file)[0] + ".key"

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def exists(self):
        return bool(self.load().get("id"))

    def _save(self, d):
        _atomic_write(self.path, json.dumps(d, indent=1).encode())

    def create(self):
        key = secrets.token_bytes(32)
        self._save({"v": 1, "id": key_id(key), "local": _protect(key),
                    "created": datetime.datetime.now().isoformat(timespec="seconds")})
        return key

    def get_key(self, ask_password=None):
        """The data key, or None when there is no key file yet."""
        d = self.load()
        if not d.get("id"):
            return None
        try:
            key = _unprotect(d["local"])
            if key_id(key) == d["id"]:
                return key
        except (OSError, KeyError, ValueError):
            pass
        if not d.get("pw"):
            raise RuntimeError("The data file is locked to a different computer or Windows account, and no backup "
                               "password was set, so it can't be opened here.")
        if not ask_password:
            raise NeedPassword("The backup password is needed to open this data.")
        msg = None
        while True:
            password = ask_password(msg)
            if password is None:
                raise NeedPassword("Cancelled")
            try:
                key = unwrap_with_password(d["pw"], password)
            except WrongPassword as ex:
                msg = str(ex)
                continue
            d["local"] = _protect(key)                 # lock it to this computer/account from now on
            self._save(d)
            return key

    def password_wrap(self):
        return self.load().get("pw")

    def set_password(self, key, password):
        d = self.load()
        d["pw"] = wrap_with_password(key, password)
        d["pw_set"] = datetime.datetime.now().isoformat(timespec="seconds")
        self._save(d)


# ------------------------------------------------------------------ backup files
def write_backup(conn, dest, key, pw_wrap):
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    tmpdir = tempfile.mkdtemp(prefix="rm-bak-")
    tmp = os.path.join(tmpdir, "b.db")
    try:
        export_to(conn, tmp, key)
        with open(tmp, "rb") as f:
            payload = f.read()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    header = json.dumps({"v": 1, "id": key_id(key), "pw": pw_wrap,
                         "made": datetime.datetime.now().isoformat(timespec="seconds")}).encode()
    _atomic_write(dest, MAGIC + struct.pack(">I", len(header)) + header + payload)
    return dest


def read_header(path):
    with open(path, "rb") as f:
        head = f.read(len(MAGIC))
        if head != MAGIC:
            return None
        n = struct.unpack(">I", f.read(4))[0]
        if n > 64 * 1024:
            raise ValueError("Damaged backup header.")
        return json.loads(f.read(n).decode()), len(MAGIC) + 4 + n


@contextlib.contextmanager
def open_backup(path, local_key, ask_password=None, found=None):
    """Yields a connection to the database inside a backup file (encrypted or an old unencrypted one).
    `found` (a dict), if given, receives the key and header that opened it."""
    check_file(path, MAX_BACKUP_BYTES)
    tmpdir = tempfile.mkdtemp(prefix="rm-res-")
    conn = None
    try:
        if is_plain(path):
            work = os.path.join(tmpdir, "plain.db")
            shutil.copyfile(path, work)
            conn = sql.connect(work)
            conn.row_factory = sql.Row
        else:
            try:
                got = read_header(path)
            except (OSError, ValueError, struct.error):
                got = None
            if not got:
                raise ValueError("That file is not a backup from this app.")
            header, offset = got
            if header.get("id") == key_id(local_key):
                key = local_key
            elif header.get("pw"):
                if not ask_password:
                    raise NeedPassword("This backup came from another computer. Its backup password is needed.")
                msg = None
                while True:
                    password = ask_password(msg)
                    if password is None:
                        raise NeedPassword("Cancelled")
                    try:
                        key = unwrap_with_password(header["pw"], password)
                        break
                    except WrongPassword as ex:
                        msg = str(ex)
            else:
                raise ValueError("This backup was made on another computer before a backup password was set, "
                                 "so it can't be opened here.")
            work = os.path.join(tmpdir, "enc.db")
            with open(path, "rb") as f, open(work, "wb") as out:
                f.seek(offset)
                shutil.copyfileobj(f, out)
            try:
                conn = connect(work, key)
            except sql.DatabaseError:
                raise ValueError("That backup file is damaged and can't be opened.")
            if found is not None:
                found.update(key=key, header=header)
        yield conn
    finally:
        if conn is not None:
            conn.close()
        shutil.rmtree(tmpdir, ignore_errors=True)


# ------------------------------------------------------------------ shared Database behaviour
class VaultMixin:
    """Encrypted open / backup / restore, shared by both apps' Database classes.
    The Database class supplies APP_LABEL, _migrate(is_new) and optionally _after_connect()."""
    APP_LABEL = "this app"
    ask_password = None

    def _open(self):
        kf = KeyFile(self.path)
        self.keyfile = kf
        exists = os.path.exists(self.path) and os.path.getsize(self.path) > 0
        if exists and is_plain(self.path):
            self._encrypt_old_data(kf)
        key = kf.get_key(self.ask_password)
        if key is None:
            if exists:            # encrypted data but its key file is gone: keep it aside, start fresh
                aside = f"{os.path.splitext(self.path)[0]}-locked-{self._stamp()}.db"
                os.replace(self.path, aside)
                self.locked_aside = aside
                exists = False
            key = kf.create()
        self._key = key
        try:
            self.conn = connect(self.path, key)
        except sql.DatabaseError:
            raise RuntimeError(f"The data file {self.path} doesn't match its key file. "
                               "Restore your newest backup, or contact Robin Mishra.")
        self._cache = {}
        if hasattr(self, "_after_connect"):
            self._after_connect()
        self._migrate(not exists)
        self.startup_ok = self.conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        if getattr(self, "_just_encrypted", False):
            self._just_encrypted = False
            self.log("Data file and backups encrypted (key locked to this Windows user)", "system", "security")

    def _encrypt_old_data(self, kf):
        """One-time upgrade: unencrypted data file and backups -> encrypted. The old file is only removed after
        the encrypted copy has been opened and checked."""
        key = kf.get_key(self.ask_password) or kf.create()
        tmp = self.path + ".encrypting"
        src = sql.connect(self.path)
        try:
            export_to(src, tmp, key)
            n_src = src.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]
        finally:
            src.close()
        chk = connect(tmp, key)
        try:
            if chk.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] != n_src or \
                    chk.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Encrypting the data file failed its check. Nothing was changed.")
        finally:
            chk.close()
        os.replace(tmp, self.path)
        for extra in ("-journal", "-wal", "-shm"):
            with contextlib.suppress(OSError):
                os.remove(self.path + extra)
        for old in glob.glob(os.path.join(backup_dir(), "*.db")):      # old backups too
            if not is_plain(old):
                continue
            try:
                c = sql.connect(old)
                try:
                    write_backup(c, old + ".enc", key, kf.password_wrap())
                finally:
                    c.close()
                with open_backup(old + ".enc", key) as test:
                    test.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
                stamp = os.path.getmtime(old)
                os.replace(old + ".enc", old)
                os.utime(old, (stamp, stamp))           # keep the backup's original date
            except Exception:
                with contextlib.suppress(OSError):
                    os.remove(old + ".enc")
        self._just_encrypted = True

    # ---------- backup password ----------
    def has_backup_password(self):
        return bool(self.keyfile.password_wrap())

    def set_backup_password(self, password, user="admin"):
        self.keyfile.set_password(self._key, password)
        self.log("Backup password set", user, "security")

    # ---------- backups ----------
    def backup(self, dest):
        self.conn.commit()
        return write_backup(self.conn, dest, self._key, self.keyfile.password_wrap())

    def safety_backup(self, reason):
        # Unique name even when two backups happen in the same clock tick (Windows' clock only
        # moves every ~15 ms, so a timestamp alone can repeat and overwrite an earlier backup).
        base = os.path.join(backup_dir(), f"{reason}-{self._stamp()}")
        dest, n = base + ".db", 1
        while os.path.exists(dest):
            n += 1
            dest = f"{base}-{n}.db"
        dest = self.backup(dest)
        self.prune_backups(protect=dest)
        return dest

    @staticmethod
    def _backup_order(path):
        """Newest first. Ties in modified time (common on Windows) fall back to the creation counter."""
        try:
            return (os.path.getmtime(path), os.stat(path).st_ctime_ns, path)
        except OSError:
            return (0, 0, path)

    def prune_backups(self, keep=BACKUP_KEEP, protect=None):
        files = sorted(glob.glob(os.path.join(backup_dir(), "*.db")), key=self._backup_order, reverse=True)
        if protect in files:                      # never delete the backup that was just made
            files.remove(protect)
            files.insert(0, protect)
        for old in files[keep:]:
            with contextlib.suppress(OSError):
                os.remove(old)

    def auto_backup(self):
        return self.safety_backup("auto")

    def list_backups(self):
        files = sorted(glob.glob(os.path.join(backup_dir(), "*.db")), key=self._backup_order, reverse=True)
        return [(os.path.basename(f), datetime.datetime.fromtimestamp(os.path.getmtime(f)).strftime("%Y-%m-%d %H:%M"),
                 os.path.getsize(f)) for f in files]

    # settings that belong to this computer, never taken from another computer's data
    MACHINE_SETTINGS = ("license_key", "lic_seen", "lic_trial")

    def restore(self, src, ask_password=None, found=None, reason="before-restore"):
        """Replaces the data with a backup (encrypted, or an old unencrypted one). Checks it first and saves a
        safety backup of the current data. Returns the safety backup's path."""
        not_ours = f"That file is not a {self.APP_LABEL} backup."
        newfile = self.path + ".restoring"
        mine = {k: self.get_setting(k, "") for k in self.MACHINE_SETTINGS}
        with open_backup(src, self._key, ask_password, found) as test:
            try:
                ok = test.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'").fetchone()
                extra = test.execute("SELECT COUNT(*) FROM sqlite_master WHERE type IN ('trigger','view')").fetchone()[0]
                healthy = test.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            except sql.DatabaseError:
                ok, extra, healthy = False, 0, False
            if not ok:
                raise ValueError(not_ours)
            if extra:
                raise ValueError("That backup file contains extra database code this app never creates, "
                                 "so it was refused. Nothing was changed.")
            if not healthy:
                raise ValueError("That backup file is damaged (failed the integrity check). Nothing was changed.")
            export_to(test, newfile, self._key)
        safety = self.safety_backup(reason)
        try:
            src = connect(newfile, self._key)       # copied in page by page through SQLite itself, so it works
            try:                                    # even while Windows has the data file open
                src.backup(self.conn)
            finally:
                src.close()
        finally:
            with contextlib.suppress(OSError):
                os.remove(newfile)
        self.conn.close()
        self._open()           # also upgrades an older backup to the current schema
        for k, v in mine.items():                  # this computer's license / trial stay this computer's
            self.set_setting(k, v)
        return safety

    def load_from_other_computer(self, src, ask_password=None):
        """Loads another computer's synced copy. The first time, the backup password unlocks it; then this computer
        switches to the same data key (locked to this Windows user), so later syncs need no password."""
        found = {}
        safety = self.restore(src, ask_password, found, reason="before-sync")
        key, header = found.get("key"), found.get("header") or {}
        if key and key != self._key:
            self.conn.execute(f"PRAGMA rekey = \"x'{key.hex()}'\"")
            d = self.keyfile.load()
            d.update(id=key_id(key), local=_protect(key))
            if header.get("pw"):
                d["pw"] = header["pw"]                 # the store's backup password (same on both computers now)
            self.keyfile._save(d)
            self._key = key
        return safety

    def encryption_lines(self):
        return ["Encryption: on - data file and backups are AES-256 encrypted (SQLCipher); "
                "the key is locked to this Windows user",
                "Backup password: set (needed to open backups on another computer)" if self.has_backup_password()
                else "Note: no backup password yet - backups can't be opened on another computer. "
                     "Set one on the Backup page."]
