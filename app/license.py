"""License keys, 14-day trial and yearly expiry.

A key is a small record (product, computer, store name, issue and expiry dates, serial number) signed with
Robin Mishra's PRIVATE key. The app holds only the PUBLIC key below, which can check a signature but cannot
make one - so nobody can create or change a key without the private key (kept by the developer, never in
this code). Checking works offline.
"""
import base64
import datetime
import hashlib
import os
import struct
import sys
import uuid

PUBLIC_KEY_B64 = "3PKH8FuZwWgeukmOCMJ2UpzG5N58BnZ34wKJ9Iag3mI="
PRODUCTS = {1: "Tobacco, Cigarettes & Vape Pricing", 2: "Beer and Liquor Pricing"}
THIS_PRODUCT = 2
TRIAL_DAYS = 14
WARN_DAYS = 15
EPOCH = datetime.date(2026, 1, 1)
_SALT = b"RM-store-apps-2026"
_REG_PATH = r"Software\RMStoreApps"


# ----------------------------------------------------------------- computer id
def _machine_guid():
    if sys.platform.startswith("win"):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                                winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)) as k:
                return winreg.QueryValueEx(k, "MachineGuid")[0]
        except OSError:
            pass
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(p) as f:
                v = f.read().strip()
                if v:
                    return v
        except OSError:
            pass
    return f"node-{uuid.getnode():x}"


def machine_bytes():
    return hashlib.sha256(_SALT + _machine_guid().encode()).digest()[:8]


def computer_id(mb=None):
    """16 characters shown to the customer, e.g. 3F9A-0C21-77BE-41D0 (same for both apps on one PC)."""
    h = (mb or machine_bytes()).hex().upper()
    return "-".join(h[i:i + 4] for i in range(0, 16, 4))


def parse_computer_id(text):
    h = "".join(ch for ch in (text or "").upper() if ch in "0123456789ABCDEF")
    if len(h) != 16:
        raise ValueError("A Computer ID has 16 letters/numbers, like 3F9A-0C21-77BE-41D0.")
    return bytes.fromhex(h)


# ----------------------------------------------------------------- key format
def _day(d):
    return (d - EPOCH).days


def _date(n):
    return EPOCH + datetime.timedelta(days=n)


def pack_payload(product, mb, customer, issued, expires, serial):
    name = (customer or "").strip().encode("utf-8")[:60]
    return struct.pack(">BB8sHHHB", 1, product, mb, _day(issued), _day(expires), serial & 0xFFFF, len(name)) + name


def encode_key(raw):
    s = base64.b32encode(raw).decode().rstrip("=")
    return "-".join(s[i:i + 5] for i in range(0, len(s), 5))


def decode_key(text):
    s = "".join(ch for ch in (text or "").upper() if ch.isalnum())
    s += "=" * (-len(s) % 8)
    return base64.b32decode(s)


def make_key(private_key, product, computer, customer, expires, serial, issued=None):
    """Used only by the License Generator (needs the private key)."""
    payload = pack_payload(product, parse_computer_id(computer) if isinstance(computer, str) else computer,
                           customer, issued or datetime.date.today(), expires, serial)
    return encode_key(payload + private_key.sign(payload))


def read_key(text, public_key_b64=PUBLIC_KEY_B64):
    """Returns the key's details if the signature is genuine, else raises ValueError."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        raw = decode_key(text)
        payload, sig = raw[:-64], raw[-64:]
        ver, product, mb, iss, exp, serial, n = struct.unpack(">BB8sHHHB", payload[:17])
        name = payload[17:17 + n].decode("utf-8")
        if ver != 1 or len(payload) != 17 + n:
            raise ValueError
    except Exception:
        raise ValueError("That isn't a valid license key. Copy the whole key, including all the dashes.")
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64)).verify(sig, payload)
    except InvalidSignature:
        raise ValueError("That license key isn't genuine (it was changed or made by someone else).")
    return {"product": product, "machine": mb, "computer_id": computer_id(mb), "customer": name,
            "issued": _date(iss), "expires": _date(exp), "serial": serial}


# ----------------------------------------------------------------- trial / clock memory
def _reg_get(name):
    if not sys.platform.startswith("win"):
        try:
            with open(os.path.join(os.path.expanduser("~"), ".rmstoreapps", name)) as f:
                return f.read().strip()
        except OSError:
            return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH) as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except OSError:
        return None


def _reg_set(name, value):
    try:
        if not sys.platform.startswith("win"):
            d = os.path.join(os.path.expanduser("~"), ".rmstoreapps")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, name), "w") as f:
                f.write(str(value))
            return
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _REG_PATH) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, str(value))
    except OSError:
        pass


def _scramble(n):                     # dates kept outside the database are stored lightly disguised
    return str((n * 7919 + 104729) ^ 0x5A5A5)


def _unscramble(s):
    try:
        v = (int(s) ^ 0x5A5A5) - 104729
        return v // 7919 if v % 7919 == 0 else None
    except (TypeError, ValueError):
        return None


def _today(db, product):
    """Today's date, but never earlier than the latest date this computer has already seen
    (so turning the PC clock back doesn't extend a trial or license)."""
    today = datetime.date.today().toordinal()
    seen = [today]
    for v in (_unscramble(_reg_get(f"p{product}l")), _unscramble(db.get_setting("lic_seen", ""))):
        if v:
            seen.append(v)
    latest = max(seen)
    if latest == today or latest > today:
        _reg_set(f"p{product}l", _scramble(latest))
        db.set_setting("lic_seen", _scramble(latest))
    return datetime.date.fromordinal(latest)


def trial_start(db, product):
    """First day of the trial: the earliest date found in the database or on this computer."""
    found = [v for v in (_unscramble(_reg_get(f"p{product}t")), _unscramble(db.get_setting("lic_trial", ""))) if v]
    start = min(found) if found else datetime.date.today().toordinal()
    _reg_set(f"p{product}t", _scramble(start))
    db.set_setting("lic_trial", _scramble(start))
    return datetime.date.fromordinal(start)


# ----------------------------------------------------------------- status
def status(db, product=THIS_PRODUCT, public_key_b64=PUBLIC_KEY_B64, mb=None):
    """state: 'licensed' | 'expiring' | 'expired' | 'trial' | 'trial_over' | 'wrong_pc' | 'wrong_product'."""
    mb = mb or machine_bytes()
    today = _today(db, product)
    out = {"computer_id": computer_id(mb), "today": today}
    key = (db.get_setting("license_key", "") or "").strip()
    if key:
        try:
            k = read_key(key, public_key_b64)
        except ValueError as ex:
            k, out["key_error"] = None, str(ex)
        if k:
            out.update(customer=k["customer"], expires=k["expires"], serial=k["serial"])
            if k["product"] != product:
                out["state"] = "wrong_product"
            elif k["machine"] != mb:
                out["state"] = "wrong_pc"
            elif today > k["expires"]:
                out["state"] = "expired"
            else:
                left = (k["expires"] - today).days
                out.update(days_left=left, state="expiring" if left <= WARN_DAYS else "licensed")
            if out["state"] in ("licensed", "expiring"):
                return out
    start = trial_start(db, product)
    left = TRIAL_DAYS - (today - start).days
    out.update(trial_start=start, days_left=max(0, left))
    out.setdefault("state", "trial" if left > 0 else "trial_over")
    if out["state"] in ("wrong_pc", "wrong_product", "expired") and left > 0:
        out["also_trial"] = True
    return out


def can_use(st):
    return st["state"] in ("licensed", "expiring", "trial") or st.get("also_trial", False)


def activate(db, text, product=THIS_PRODUCT, public_key_b64=PUBLIC_KEY_B64, mb=None):
    """Checks a key for THIS computer and product, then saves it. Returns its details or raises ValueError."""
    k = read_key(text, public_key_b64)
    mb = mb or machine_bytes()
    if k["product"] != product:
        raise ValueError(f"That key is for '{PRODUCTS.get(k['product'], 'another app')}', not this app.")
    if k["machine"] != mb:
        raise ValueError(f"That key is for computer {k['computer_id']}, but this computer is {computer_id(mb)}.\n"
                         "Ask for a key made for this Computer ID.")
    if _today(db, product) > k["expires"]:
        raise ValueError(f"That key expired on {k['expires']:%b %d, %Y}. Ask for a renewal key.")
    db.set_setting("license_key", "-".join(decode_key_text_groups(text)))
    return k


def decode_key_text_groups(text):
    s = "".join(ch for ch in (text or "").upper() if ch.isalnum())
    return [s[i:i + 5] for i in range(0, len(s), 5)]


def describe(st):
    s = st["state"]
    if s in ("licensed", "expiring"):
        return (f"Licensed to {st['customer']} until {st['expires']:%b %d, %Y}"
                + (f"  ({st['days_left']} day(s) left)" if s == "expiring" else ""))
    if s == "trial":
        return f"Free trial: {st['days_left']} day(s) left"
    return {"trial_over": "The 14-day trial has ended",
            "expired": f"License expired on {st.get('expires'):%b %d, %Y}" if st.get("expires") else "License expired",
            "wrong_pc": "The saved license key is for a different computer",
            "wrong_product": "The saved license key is for a different app"}.get(s, s)
