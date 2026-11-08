"""App identity and file locations.

Data is stored OUTSIDE the program folder so installing a new version
never touches it:
  Windows : %APPDATA%\\BevMargin\\bevmargin.db
  Mac/Linux: ~/.bevmargin/bevmargin.db
Portable mode: put an empty file named 'portable.flag' next to the .exe
and the data lives in a 'data' folder beside it (great for a USB stick).
"""
import os
import sys

APP_NAME = "Beer and Liquor Pricing"
APP_SHORT = "BevMargin"
APP_VERSION = "1.5.3"          # bump this for every release (and MyAppVersion in installer.iss)
DEVELOPER = "Robin Mishra"
CREDIT = "Developed by Robin Mishra  •  Copyright © 2026"


def base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(*parts):
    root = getattr(sys, "_MEIPASS", base_dir())
    return os.path.join(root, *parts)


def is_portable():
    return os.path.exists(os.path.join(base_dir(), "portable.flag"))


def data_dir():
    if is_portable():
        d = os.path.join(base_dir(), "data")
    elif os.name == "nt":
        d = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_SHORT)
    else:
        d = os.path.join(os.path.expanduser("~"), ".bevmargin")
    os.makedirs(d, exist_ok=True)
    return d


def db_path():
    return os.environ.get("BEVMARGIN_DB") or os.path.join(data_dir(), "bevmargin.db")


def backup_dir():
    d = os.path.join(data_dir(), "backups")
    os.makedirs(d, exist_ok=True)
    return d
