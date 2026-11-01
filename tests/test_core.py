import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp()
os.environ["BEVMARGIN_DB"] = os.path.join(tmp, "t.db")
from app import calc, io_utils
from app.db import Database, MIGRATIONS
from app.chatbot import ChatBot

assert calc.guess_case_units("BOULEVARD SPACE CAMPER 4/6 CAN") == 24
assert calc.guess_case_units("X 2/12 CAN") == 24
assert calc.guess_case_units("X 19.2 CAN") == 24
c = calc.compute({"qty": 1, "net": 33, "dep": 0, "case_units": 24, "case_sp": 44, "pk12_sp": 21.99, "pk6_sp": 10.99},
                 targets={"case": 25, "pk12": 25, "pk6": 30})
assert round(c["pk6_cost"], 2) == 8.25 and round(c["pk12_cost"], 2) == 16.5
assert round(c["case_margin"], 2) == 25.0, c
assert round(c["pk6_margin"], 1) == 24.9 and c["low_margin"]
assert c["pk6_suggested"] == 11.79
assert calc.compute({"qty": 1, "net": 10, "case_units": 6, "pk12_sp": 5})["pk12_margin"] is None

db = Database()
assert len(db.list_products()) == 3 and len(db.list_products(category="Liquor")) == 1
assert db.verify_user("admin", "admin") and not db.verify_user("admin", "x")
pid = db.list_products("56334")[0]["id"]
db.update_product(pid, {"case_sp": 44, "pk6_sp": 10.99})
bot = ChatBot(db)
print(bot.respond("margin for 56334")); print(bot.respond("low margin"))
print(bot.respond("price for cost 8.25 at 30%")); print(bot.respond("how do I import"))
print(bot.respond("stats"))

# export / import round trip (import updates by Item#)
csvp = os.path.join(tmp, "e.csv"); xl = os.path.join(tmp, "e.xlsx")
io_utils.export_csv(csvp, db.list_products(), False, db.all_targets())
io_utils.export_xlsx(xl, db.list_products(), False, db.all_targets())
got = io_utils.read_file(xl); assert len(got) == 3 and sorted(p["category"] for p in got) == ["Beer", "Beer", "Liquor"], got
assert io_utils.read_file(csvp)[0]["item_no"]
io_utils.export_pdf(os.path.join(tmp, "r.pdf"), db.list_products(), "Test", False, db.all_targets())

# liquor math: 12 bottles, net 168 -> bottle cost 14, 6 btl cost 84
lc = calc.compute({"category": "Liquor", "qty": 1, "net": 168, "case_units": 12, "pk6_sp": 19.99, "pk12_sp": 109.99})
assert round(lc["pk6_cost"], 2) == 14.0 and round(lc["pk12_cost"], 2) == 84.0
assert db.targets("Liquor")["case"] == 20 and db.targets("Beer")["case"] == 25
print(bot.respond("margin for vodka"))

# v1.0 -> v1.1 upgrade: an old database with a 'Seltzer' row keeps it and moves it to Beer
import sqlite3
from app.db import SCHEMA_V1
old = os.path.join(tmp, "v1.db"); oc = sqlite3.connect(old); oc.executescript(SCHEMA_V1)
oc.execute("CREATE TABLE schema_version(version INTEGER)"); oc.execute("INSERT INTO schema_version VALUES (1)")
oc.execute("INSERT INTO products(description,category,net,case_sp) VALUES ('OLD SELTZER','Seltzer',20,30)")
oc.execute("INSERT INTO products(description,category,net) VALUES ('OLD WINE','Wine',50)"); oc.commit(); oc.close()
up = Database(old)
assert up.schema_version() == 4 and len(up.list_products()) == 2
assert up.list_products("SELTZER")[0]["category"] == "Beer" and up.list_products("WINE")[0]["category"] == "Liquor"
assert up.list_products("SELTZER")[0]["case_sp"] == 30
assert up.list_products("SELTZER")[0]["s24_sp"] is None   # new columns added, old data untouched
up.close()

# v1.2: Case = whole box, 12 Pk = 1/2 of a 2/12 case, 6 Pk = 1/4 of a 4/6 case, singles = Net / cans
b = calc.compute({"category": "Beer", "qty": 1, "net": 33, "case_units": 24, "case_sp": 44, "pk12_sp": 21.99, "pk6_sp": 10.99})
assert b["case_cost"] == 33 and b["pk12_cost"] == 16.5 and b["pk6_cost"] == 8.25
s24 = calc.compute({"category": "Beer", "qty": 1, "net": 36, "case_units": 12, "s24_sp": 3.99},
                   targets={"case": 25, "pk12": 25, "pk6": 30, "s24": 30, "s14": 30})
assert s24["s24_cost"] == 3.0 and round(s24["s24_margin"], 1) == 24.8 and s24["low_margin"] and s24["s24_suggested"] == 4.29
s14 = calc.compute({"category": "Beer", "qty": 1, "net": 30, "case_units": 24, "s14_sp": 1.99})
assert s14["s14_cost"] == 1.25 and round(s14["s14_margin"], 1) == 37.2
assert calc.guess_case_units("X 1/24 14OZ CAN") == 24
assert calc.guess_case_units("SAMPLE LAGER 12/24OZ CAN") == 12
assert calc.guess_case_units("BOULEVARD 4/6 CAN") == 24 and calc.guess_case_units("X 2/12 CAN") == 24
assert "s24_margin" not in calc.compute({"category": "Liquor", "net": 10, "case_units": 12})
assert set(db.targets("Beer")) == {"case", "pk12", "pk6", "s24", "s14"} and set(db.targets("Liquor")) == {"case", "pk12", "pk6"}
pid24 = db.add_product({"category": "Beer", "description": "SAMPLE LAGER 12/24OZ CAN", "item_no": "70001", "net": 36, "case_units": 12, "s24_sp": 3.99})
assert db.get_product(pid24)["s24_sp"] == 3.99
xl2 = os.path.join(tmp, "e2.xlsx"); io_utils.export_xlsx(xl2, db.list_products(), False, db.all_targets())
import openpyxl
hdr = [c.value for c in openpyxl.load_workbook(xl2)["Beer"][1]]
assert "Single 24oz SP" in hdr and "Single 14oz Margin %" in hdr, hdr
assert "Single 24oz SP" not in [c.value for c in openpyxl.load_workbook(xl2)["Liquor"][1]]
back = [p for p in io_utils.read_file(xl2) if p.get("item_no") == "70001"][0]
assert back["s24_sp"] == 3.99 and back["category"] == "Beer"
io_utils.export_pdf(os.path.join(tmp, "r2.pdf"), db.list_products(), "Test", False, db.all_targets())
print(bot.respond("margin for 70001"))
db.delete_products([pid24])

# ---------------- v1.3 features
import glob, sqlite3 as _sq
from app import db as dbmod
from app.config import backup_dir
# price history: old -> new recorded, unchanged fields not recorded
p0 = db.list_products("56334")[0]
ch = db.update_product(p0["id"], {"case_sp": 45.99, "net": 33.0, "description": p0["description"]}, "admin", source="test")
assert ch == [("case_sp", 44.0, 45.99)], ch
ph = db.price_history(product_id=p0["id"])
assert ph[0]["old_value"] == 44.0 and ph[0]["new_value"] == 45.99 and ph[0]["source"] == "test" and ph[0]["username"] == "admin"
# audit kinds
db.log("Signed in (admin)", "admin", "login"); db.log("Failed sign-in attempt for 'bob'", "bob", "security")
assert db.audit_log("security")[0]["username"] == "bob"
assert db.audit_log("product") and all(r["kind"] == "product" for r in db.audit_log("product"))
db.set_target("Beer", "pk6", 32, "admin")
assert db.audit_log("settings")[0]["action"].startswith("Beer 6 Pk target margin 30% -> 32%")
# validation
ok = {"description": "X", "category": "Beer", "qty": 1, "price": 10, "net": 10, "dep": 0, "case_units": 24}
assert calc.validate_product(ok) == ([], [])
assert calc.validate_product({**ok, "net": -1})[0]
assert calc.validate_product({**ok, "case_sp": 0})[0]
assert calc.validate_product({**ok, "case_units": 2.5})[0] and calc.validate_product({**ok, "case_units": 0})[0]
assert calc.validate_product({**ok, "description": " "})[0]
errs, warns = calc.validate_product({**ok, "case_sp": 9.0})
assert not errs and warns and "below cost" in warns[0]
assert calc.validate_target(100) and calc.validate_target(-1) and not calc.validate_target(99.5)
try:
    db.set_target("Beer", "case", 150); raise SystemExit("bad target accepted")
except ValueError:
    pass
# transaction rollback: nothing written on error
before = len(db.list_products())
try:
    with db.transaction():
        db.add_product({**ok, "description": "ROLLBACK ME"}, "admin")
        raise RuntimeError("boom")
except RuntimeError:
    pass
assert len(db.list_products()) == before and not db.list_products("ROLLBACK")
# safer import: bad rows skipped with row numbers, backup made, one transaction
csvbad = os.path.join(tmp, "bad.csv")
with open(csvbad, "w") as f:
    f.write("Category,Item#,Description,Qty,Net,Case Size,Case SP,6 Pk SP\n")
    f.write("Beer,80001,GOOD BEER 4/6 CAN,1,30,24,39.99,9.99\n")
    f.write("Beer,80002,NEGATIVE NET,1,-5,24,10,\n")
    f.write("Beer,80003,TEXT PRICE,1,20,24,abc,\n")
    f.write("Beer,,,,,,,\n")
    f.write("Beer,56334,,,33,,47.99,\n")                 # update existing: only case SP changes
items = io_utils.read_file(csvbad)
adds, updates, problems = io_utils.plan_import(db, items)
assert [a[1]["item_no"] for a in adds] == ["80001"] and [u[2] for u in updates] == [p0["id"]], (adds, updates)
assert any("row 3" in x and "negative" in x for x in problems) and any("row 4" in x and "not a number" in x for x in problems), problems
nb = len(glob.glob(os.path.join(backup_dir(), "before-import-*.db")))
bk = io_utils.apply_import(db, adds, updates, "admin", "bad.csv")
assert len(glob.glob(os.path.join(backup_dir(), "before-import-*.db"))) == nb + 1 and os.path.exists(bk)
assert db.find_by_item("80001") and db.get_product(p0["id"])["case_sp"] == 47.99
assert db.price_history(product_id=p0["id"])[0]["source"] == "import bad.csv"
assert db.audit_log("import")[0]["action"].startswith("Imported bad.csv: 1 added, 1 updated")
# import failure mid-way rolls back everything
n_before = len(db.list_products())
orig = db.update_product
db.update_product = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full"))
try:
    io_utils.apply_import(db, [("r", {**ok, "item_no": "90001", "description": "SHOULD NOT EXIST"})], [("r", {**ok}, p0["id"])], "admin", "x.csv")
except RuntimeError:
    pass
db.update_product = orig
assert len(db.list_products()) == n_before and not db.find_by_item("90001")
# retention: never more than 30 backups
for _ in range(35):
    db.auto_backup()
assert len(glob.glob(os.path.join(backup_dir(), "*.db"))) == dbmod.BACKUP_KEEP
# health check passes, and a damaged backup is refused on restore
okh, lines = db.health_check()
assert okh, lines
assert any("integrity check: passed" in l for l in lines)
junk = os.path.join(tmp, "junk.db"); open(junk, "wb").write(b"not a database at all" * 100)
try:
    db.restore(junk); raise SystemExit("junk restore accepted")
except ValueError:
    pass
assert len(db.list_products()) >= n_before            # still working after refusing
# remember me setting exists
assert db.get_setting("remember_user") == ""
print("v1.3 feature tests passed")

# ---------------- v1.4 time-savers
from app import pricing, labels as labelmod
# rounding always goes up
assert calc.round_price(11.73, "x9") == 11.79 and calc.round_price(11.20, "49_99") == 11.49
assert calc.round_price(11.79, "49_99") == 11.99 and calc.round_price(11.20, "99") == 11.99
assert calc.round_price(11.99, "99") == 11.99 and calc.round_price(11.734, "none") == 11.73
assert calc.suggested_price(8.25, 30, "99") == 11.99 and calc.suggested_price(8.25, 30) == 11.79
# UPC lookup: exact, leading zero (EAN-13), missing check digit, item# fallback
bp = db.add_product({"category": "Beer", "description": "UPC TEST 4/6", "item_no": "U1", "upc": "726959911074",
                     "net": 33, "case_units": 24, "case_sp": 42.99, "pk6_sp": 10.99}, "admin")
assert db.find_by_upc("726959911074")["id"] in (bp, p0["id"])
assert db.find_by_upc("0726959911074") and db.find_by_upc("72695991107")
assert db.find_by_upc("U1")["id"] == bp and db.find_by_upc("999999999999") is None
# bulk plan: +10% on 6 Pk with .99 rounding, only filled prices
chg, skp = pricing.bulk_plan(db, [db.get_product(bp)], ["pk6"], "pct", 10, "99")
assert len(chg) == 1 and chg[0]["old"] == 10.99 and chg[0]["new"] == 12.99, chg
chg, _ = pricing.bulk_plan(db, [db.get_product(bp)], ["case", "pk12", "pk6"], "target", None, "none", only_filled=False)
got = {c["key"]: c["new"] for c in chg}
assert got["pk12"] == 22.0 and got["pk6"] == round(8.25 / 0.68, 2), got     # pk6 target 32% set earlier
chg, skp = pricing.bulk_plan(db, [db.get_product(bp)], ["pk6"], "amt", -20)
assert not chg and skp and "not valid" in skp[0]
chg, skp = pricing.bulk_plan(db, [db.get_product(bp)], ["pk6"], "margin", 150)
assert not chg and skp
chg, _ = pricing.bulk_plan(db, [db.get_product(bp)], ["case", "pk6"], "pct", 5, "x9")
pricing.apply_changes(db, chg, "admin", "bulk update")
assert db.get_product(bp)["pk6_sp"] == 11.59 and db.price_history(product_id=bp)[0]["source"] == "bulk update"
assert glob.glob(os.path.join(backup_dir(), "before-bulk-update-*.db"))
# cost changes: net goes up, margin drops below target, suggested shown
import datetime as _dt
since = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
db.update_product(bp, {"net": 40.0}, "admin", source="import supplier.xlsx")
rows = pricing.cost_changes(db, since, source="import supplier.xlsx")
pk6 = [r for r in rows if r["key"] == "pk6"][0]
assert pk6["old_net"] == 33 and pk6["new_net"] == 40 and pk6["new_cost"] == 10.0 and pk6["below"]
assert pk6["old_margin"] > pk6["new_margin"] and pk6["suggested"] == round(10 / 0.68, 2)
assert not pricing.cost_changes(db, since, source="some other file")
# labels changed since today include this product; PDFs build for both sheet sizes
assert bp in [p["id"] for p in db.products_with_changes(since[:10] + " 00:00")]
for size in ("5163", "5160"):
    out = os.path.join(tmp, f"labels-{size}.pdf")
    labelmod.make_labels(out, db.list_products() * 4, size, start=3, outlines=True, store="Test Store")
    assert open(out, "rb").read(5) == b"%PDF-" and os.path.getsize(out) > 2000
db.delete_products([bp])
print("v1.4 time-saver tests passed")

# simulate upgrade: new migration must keep old rows and back up first
count_before = len(db.list_products())
case_sp_before = db.get_product(pid)["case_sp"]
hist_before = len(db.price_history())
db.backup(os.path.join(tmp, "b.db"))
db.close()
MIGRATIONS.append((5, "ALTER TABLE products ADD COLUMN supplier TEXT DEFAULT '';"))
db2 = Database()
assert db2.schema_version() == 5 and len(db2.list_products()) == count_before
assert db2.get_product(pid)["case_sp"] == case_sp_before
assert len(db2.price_history()) == hist_before            # price history survives upgrades
db2.restore(os.path.join(tmp, "b.db"))   # restore an older backup -> auto-upgraded
assert db2.schema_version() == 5 and len(db2.list_products()) == count_before
import datetime
db = Database()
# ---------------- license keys (v1.4). Uses a TEST key pair and product 99 so a real trial/license is never touched.
import base64 as _b64
from unittest import mock
from cryptography.hazmat.primitives import serialization as _ser
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from app import license as lic
_mem = {}                                                  # trial memory kept in memory (never the registry)
lic._reg_get, lic._reg_set = _mem.get, _mem.__setitem__
tk_priv = Ed25519PrivateKey.generate()
tk_pub = _b64.b64encode(tk_priv.public_key().public_bytes(_ser.Encoding.Raw, _ser.PublicFormat.Raw)).decode()
PC1, PC2 = bytes.fromhex("1122334455667788"), bytes.fromhex("99AABBCCDDEEFF00")
today = datetime.date.today()
key = lic.make_key(tk_priv, 99, lic.computer_id(PC1), "Robin's Liquor Store", today + datetime.timedelta(days=365), 7)
k = lic.read_key(key, tk_pub)
assert k["customer"] == "Robin's Liquor Store" and k["computer_id"] == "1122-3344-5566-7788" and k["serial"] == 7
assert lic.read_key(key.lower().replace("-", " "), tk_pub)["serial"] == 7            # pasted with spaces / lower case
other = Ed25519PrivateKey.generate()
fake = lic.make_key(other, 99, PC1, "Pirate", today + datetime.timedelta(days=3650), 1)
for bad in (fake, key[:-6] + ("AAAAA" if key[-5:] != "AAAAA" else "BBBBB") + key[-1:], "hello", ""):
    try:
        lic.read_key(bad, tk_pub)
        raise SystemExit(f"bad key accepted: {bad[:20]}")
    except ValueError:
        pass
tamper = bytearray(lic.decode_key(key)); tamper[11] ^= 1                         # change the expiry byte
try:
    lic.read_key(lic.encode_key(bytes(tamper)), tk_pub)
    raise SystemExit("edited key accepted")
except ValueError:
    pass
assert lic.parse_computer_id("1122 3344 5566 7788") == PC1
# trial: day 0 ok, day 15 over
db.set_setting("license_key", "")
for kk in ("lic_trial", "lic_seen"):
    db.set_setting(kk, "")
st = lic.status(db, 99, tk_pub, PC1)
assert st["state"] == "trial" and st["days_left"] == 14 and lic.can_use(st)
with mock.patch.object(lic, "_today", lambda d, p: today + datetime.timedelta(days=15)):
    st = lic.status(db, 99, tk_pub, PC1)
    assert st["state"] == "trial_over" and not lic.can_use(st)
# activate: wrong computer / wrong product refused, right one accepted
for bad_mb, prod in ((PC2, 99), (PC1, 98)):
    try:
        lic.activate(db, key, prod, tk_pub, bad_mb)
        raise SystemExit("wrong pc/product accepted")
    except ValueError:
        pass
assert lic.activate(db, key, 99, tk_pub, PC1)["serial"] == 7
st = lic.status(db, 99, tk_pub, PC1)
assert st["state"] == "licensed" and st["customer"] == "Robin's Liquor Store" and lic.can_use(st)
assert lic.status(db, 99, tk_pub, PC2)["state"] == "wrong_pc"                  # database copied to another PC
with mock.patch.object(lic, "_today", lambda d, p: today + datetime.timedelta(days=355)):
    st = lic.status(db, 99, tk_pub, PC1)
    assert st["state"] == "expiring" and st["days_left"] == 10 and lic.can_use(st)
with mock.patch.object(lic, "_today", lambda d, p: today + datetime.timedelta(days=366)):
    st = lic.status(db, 99, tk_pub, PC1)
    assert st["state"] == "expired" and not lic.can_use(st)
# turning the clock back doesn't help: the latest date seen is used
db.set_setting("lic_seen", lic._scramble((today + datetime.timedelta(days=400)).toordinal()))
assert lic.status(db, 99, tk_pub, PC1)["state"] == "expired"
db.set_setting("lic_seen", "")
_mem.clear()
assert lic.status(db, 99, tk_pub, PC1)["state"] == "licensed"
db.set_setting("license_key", "")
assert lic.describe({"state": "trial", "days_left": 3}) == "Free trial: 3 day(s) left"
assert len(lic.computer_id()) == 19

# ---------------- updates (no internet needed: GitHub's answer is faked)
import io as _io
import json as _json
import hashlib as _hl
from app import updater
from app.config import APP_VERSION
blob = b"fake installer bytes" * 1000
fake_rel = [{"draft": False, "body": "New things", "assets": [
    {"name": "BevMargin-Setup-99.1.0.exe", "browser_download_url": "https://x/a.exe", "size": len(blob),
     "digest": "sha256:" + _hl.sha256(blob).hexdigest()},
    {"name": "TobaccoPricing-Setup-99.9.9.exe", "browser_download_url": "https://x/b.exe", "size": 1}]},
    {"draft": False, "body": "", "assets": [{"name": "BevMargin-Setup-1.0.0.exe", "browser_download_url": "u", "size": 1}]}]


class _Resp(_io.BytesIO):
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


with mock.patch.object(updater, "_open", lambda url, t: _Resp(b"{}" if "latest.json" in url else
                                                              _json.dumps(fake_rel).encode() if "api." in url else blob)):
    info = updater.newer_available()
    assert info and info["text"] == "99.1.0" and info["name"].startswith("BevMargin")   # tobacco app's file ignored
    path = updater.download(info)
    assert open(path, "rb").read() == blob
    os.remove(path)
    try:
        updater.download({**info, "sha256": "0" * 64})
        raise SystemExit("bad download accepted")
    except IOError:
        pass
# latest.json on the downloads page (no Releases there): newer version found, offline -> clear error
man = {"BevMargin": {"version": "99.2.0", "file": "BevMargin-Setup-99.2.0.exe", "url": "https://x/c.exe",
                          "size": len(blob), "sha256": _hl.sha256(blob).hexdigest(), "notes": "Notes"}}


def _fake(url, t):
    if "latest.json" in url:
        return _Resp(_json.dumps(man).encode())
    if "api." in url:
        return _Resp(b"[]")
    return _Resp(blob)


with mock.patch.object(updater, "_open", _fake):
    info = updater.newer_available()
    assert info["text"] == "99.2.0" and updater.download(info)


def _offline(url, t):
    raise OSError("no internet")


with mock.patch.object(updater, "_open", _offline):
    try:
        updater.newer_available()
        raise SystemExit("offline not reported")
    except OSError:
        pass
old = [{"draft": False, "assets": [{"name": f"BevMargin-Setup-{APP_VERSION}.exe", "browser_download_url": "u", "size": 1}]}]
with mock.patch.object(updater, "_open", lambda url, t: _Resp(b"{}" if "latest.json" in url else _json.dumps(old).encode())):
    assert updater.newer_available() is None                                   # same version: nothing to do

assert lic.THIS_PRODUCT == 2
print("ALL TESTS PASSED")
