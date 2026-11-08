"""Short sound effects (Windows), made by the app itself - no sound files to ship.

  error    - scan found nothing, a file couldn't be read, something was refused
  warning  - needs a look (e.g. a PDF whose lines don't add up to its total)
  success  - import / upload finished
  saved    - a product, invoice or other record was changed
  up       - a price or cost went UP
  down     - a price or cost went DOWN
Turned on/off on the About page (setting 'sounds'). On Mac/Linux (tests) nothing plays.
"""
import math
import os
import struct
import sys
import tempfile
import time
import wave

RATE = 22050
_enabled = True
_last = 0.0
_files = {}

# (frequency start Hz, frequency end Hz, seconds, volume 0..1, shape)
SOUNDS = {
    "error":   [(240, 200, 0.12, 0.55, "square"), (0, 0, 0.05, 0, "sine"), (240, 200, 0.16, 0.55, "square")],
    "warning": [(660, 660, 0.11, 0.45, "sine"), (0, 0, 0.04, 0, "sine"), (520, 520, 0.16, 0.45, "sine")],
    "success": [(660, 660, 0.08, 0.40, "sine"), (880, 880, 0.08, 0.40, "sine"), (1320, 1320, 0.18, 0.40, "sine")],
    "saved":   [(1200, 1000, 0.06, 0.35, "sine")],
    "up":      [(520, 980, 0.22, 0.40, "sine")],
    "down":    [(980, 520, 0.22, 0.40, "sine")],
}
_IMPORTANT = {"error", "warning", "success"}         # never skipped by the anti-spam pause


def _wave_bytes(parts):
    frames = bytearray()
    for f0, f1, secs, vol, shape in parts:
        n = int(RATE * secs)
        phase = 0.0
        for i in range(n):
            f = f0 + (f1 - f0) * i / max(n - 1, 1)
            phase += 2 * math.pi * f / RATE
            s = math.sin(phase)
            if shape == "square":
                s = 0.6 if s >= 0 else -0.6
            env = min(1.0, i / (RATE * 0.005), (n - i) / (RATE * 0.02))   # no clicks at start / end
            frames += struct.pack("<h", int(32767 * vol * s * max(env, 0)))
    return bytes(frames)


def _file(name):
    if name not in _files:
        folder = os.path.join(tempfile.gettempdir(), "rm-store-sounds")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{name}-v1.wav")
        if not os.path.exists(path):
            tmp = path + f".{os.getpid()}.tmp"
            with wave.open(tmp, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(RATE)
                w.writeframes(_wave_bytes(SOUNDS[name]))
            os.replace(tmp, path)
        _files[name] = path
    return _files[name]


def set_enabled(on):
    global _enabled
    _enabled = bool(on)


def enabled():
    return _enabled


def play(name):
    """Plays one effect without waiting. Never raises: a sound must not stop the app."""
    global _last
    if not _enabled or name not in SOUNDS:
        return False
    now = time.monotonic()
    if name not in _IMPORTANT and now - _last < 0.25:      # bulk changes: one sound, not hundreds
        return False
    _last = now
    if not sys.platform.startswith("win"):
        return True
    try:
        import winsound
        winsound.PlaySound(_file(name), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        return True
    except Exception:
        return False


SELL_FIRST = ("case_sp", "unit_sp", "pk12_sp", "pk6_sp", "s24_sp", "s14_sp", "sell_pack")
COST = ("net", "price", "cost_ctn", "buydown", "allowance", "dep")


def for_changes(changes):
    """Which sound fits a list of (field, old, new) changes: up / down for prices or costs, else saved.
    Buydowns and allowances lower the cost, so a bigger buydown counts as 'down'."""
    by = {f: (o, n) for f, o, n in changes or ()}
    for group in (SELL_FIRST, COST):
        diff = 0.0
        for f in group:
            if f in by:
                o, n = by[f]
                try:
                    d = float(n or 0) - float(o or 0)
                except (TypeError, ValueError):
                    continue
                diff += -d if f in ("buydown", "allowance") else d
        if abs(diff) > 0.0001:
            return "up" if diff > 0 else "down"
    return "saved"
