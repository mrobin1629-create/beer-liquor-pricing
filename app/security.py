"""Security helpers shared by the app: passwords, sign-in lockout, safe file handling and safe exports.

Everything here works offline and is the same in both store apps.
"""
import datetime
import hashlib
import os
import re
import secrets
from xml.sax.saxutils import escape as _xml_escape

# ---------------------------------------------------------------- passwords
PBKDF2_ROUNDS = 600_000            # OWASP 2023+ recommendation for PBKDF2-HMAC-SHA256
LEGACY_ROUNDS = 120_000            # passwords saved by versions before the security update
MIN_PASSWORD = 8
_WEAK = {"admin", "password", "password1", "12345678", "123456789", "1234567890", "qwerty123", "letmein1",
         "welcome1", "changeme", "11111111", "00000000", "abcd1234", "store123", "iloveyou"}


def hash_pw(password, salt=None, rounds=PBKDF2_ROUNDS):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), rounds).hex()
    return f"pbkdf2_sha256${rounds}${salt}${h}"


def check_pw(password, stored):
    """True when the password matches. Understands the old 'salt$hash' format too."""
    try:
        parts = (stored or "").split("$")
        if len(parts) == 4 and parts[0] == "pbkdf2_sha256":
            rounds, salt, want = int(parts[1]), parts[2], parts[3]
        elif len(parts) == 2:
            rounds, salt, want = LEGACY_ROUNDS, parts[0], parts[1]
        else:
            return False
        if not 1000 <= rounds <= 5_000_000:
            return False
    except ValueError:
        return False
    got = hashlib.pbkdf2_hmac("sha256", (password or "").encode(), salt.encode(), rounds).hex()
    return secrets.compare_digest(got, want)


def needs_rehash(stored):
    return not (stored or "").startswith(f"pbkdf2_sha256${PBKDF2_ROUNDS}$")


def password_problem(password, username=""):
    """Returns a message when the password is too weak, else None."""
    p = password or ""
    if len(p) < MIN_PASSWORD:
        return f"Password must be at least {MIN_PASSWORD} characters."
    if p.strip() != p or not p.strip():
        return "Password can't start or end with a space."
    if username and p.lower() == username.strip().lower():
        return "Password can't be the same as the username."
    if p.lower() in _WEAK or len(set(p)) < 3:
        return "That password is too easy to guess. Please choose another."
    return None


# ---------------------------------------------------------------- sign-in lockout
MAX_TRIES = 5                       # wrong passwords allowed before a pause
FIRST_LOCK = 60                     # seconds; doubles each time, up to MAX_LOCK
MAX_LOCK = 15 * 60


def _lock_key(username):
    return "login_fail_" + re.sub(r"[^a-z0-9_.@-]", "_", (username or "").strip().lower())[:60]


def locked_for(db, username, now=None):
    """Seconds left before this username may try again (0 = may try now)."""
    now = now or datetime.datetime.now()
    try:
        _, _, until = (db.get_setting(_lock_key(username), "") or "0|0|").split("|")
        left = (datetime.datetime.fromisoformat(until) - now).total_seconds() if until else 0
    except ValueError:
        return 0
    return max(0, int(left + 0.999)) if left < MAX_LOCK + 60 else MAX_LOCK  # clock moved back: cap it


def record_failure(db, username, now=None):
    """Counts a wrong password. Returns the lock time in seconds (0 if not locked yet)."""
    now = now or datetime.datetime.now()
    try:
        fails, locks, _ = (db.get_setting(_lock_key(username), "") or "0|0|").split("|")
        fails, locks = int(fails), int(locks)
    except ValueError:
        fails, locks = 0, 0
    fails += 1
    secs, until = 0, ""
    if fails >= MAX_TRIES:
        secs = min(MAX_LOCK, FIRST_LOCK * (2 ** locks))
        until = (now + datetime.timedelta(seconds=secs)).isoformat(timespec="seconds")
        fails, locks = 0, locks + 1
    db.set_setting(_lock_key(username), f"{fails}|{locks}|{until}")
    return secs


def record_success(db, username):
    db.set_setting(_lock_key(username), "")


def wait_text(secs):
    return f"{secs} seconds" if secs < 90 else f"{(secs + 59) // 60} minutes"


# ---------------------------------------------------------------- files people choose
MAX_IMPORT_BYTES = 25 * 1024 * 1024        # spreadsheets / CSV
MAX_IMPORT_ROWS = 50_000
MAX_BACKUP_BYTES = 2 * 1024 * 1024 * 1024  # restore
MAX_KEY_BYTES = 16 * 1024                  # license key files
MAX_TEXT = 500                             # longest text kept from one imported cell
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def check_file(path, max_bytes, kinds=None):
    """Raises ValueError when the file is missing, empty, too big or the wrong type."""
    if not path or not os.path.isfile(path):
        raise ValueError("File not found.")
    if kinds and os.path.splitext(path)[1].lower() not in kinds:
        raise ValueError(f"Please choose a {' / '.join(sorted(kinds))} file.")
    size = os.path.getsize(path)
    if size == 0:
        raise ValueError("That file is empty.")
    if size > max_bytes:
        raise ValueError(f"That file is too big ({size / 1048576:.1f} MB). The limit is {max_bytes / 1048576:.0f} MB.")
    if kinds and os.path.splitext(path)[1].lower() in (".xlsx", ".xlsm"):
        with open(path, "rb") as f:
            if f.read(2) != b"PK":
                raise ValueError("That file is not a real Excel (.xlsx) file.")
    return size


def clean_text(v, limit=MAX_TEXT):
    """Imported text: control characters removed, length capped. Numbers pass through unchanged."""
    if not isinstance(v, str):
        return v
    return _CTRL.sub("", v)[:limit]


# ---------------------------------------------------------------- exports
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r", "＝", "＋", "－", "＠")


def safe_cell(v):
    """Stops a product name such as '=HYPERLINK(...)' from running as a formula when an export is opened
    in Excel (CSV / formula injection). Only text is changed, never numbers."""
    if isinstance(v, str) and v.startswith(_FORMULA_START):
        return "'" + v
    return v


def pdf_text(v):
    """Text placed inside a PDF paragraph: '<', '>' and '&' are shown as typed instead of read as markup."""
    return _xml_escape("" if v is None else str(v))


class csv_writer:
    """csv.writer that applies safe_cell to every value."""

    def __init__(self, f):
        import csv
        self._w = csv.writer(f)

    def writerow(self, row):
        self._w.writerow([safe_cell(v) for v in row])

    def writerows(self, rows):
        for r in rows:
            self.writerow(r)
