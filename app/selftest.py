"""Built-program self-test.  TobaccoPricing.exe --selftest result.json

Run by the GitHub build on Windows against the finished program (before it is released), so a packaging
problem (missing library, data file, encryption or Windows key-lock trouble) stops the release instead of
reaching a store. Uses only a temporary folder; the real data folder is never touched.
"""
import inspect
import json
import os
import shutil
import sys
import tempfile
import traceback


def run(out_path):
    results, ok = {}, True
    tmp = tempfile.mkdtemp(prefix="selftest-")

    def check(name, fn):
        nonlocal ok
        try:
            results[name] = fn() or "ok"
        except Exception:
            ok = False
            results[name] = "FAILED: " + traceback.format_exc()[-1500:]

    from .config import APP_NAME, APP_VERSION
    results["app"] = f"{APP_NAME} {APP_VERSION} ({sys.platform}, frozen={getattr(sys, 'frozen', False)})"

    def windows_key_lock():
        from . import vault
        key = os.urandom(32)
        entry = vault._protect(key)
        assert vault._unprotect(entry) == key
        return f"locked by {entry['by']}"

    def database():
        from . import vault
        from .db import Database
        db = Database(os.path.join(tmp, "st.db"))
        prods = db.list_products()
        raw = open(db.path, "rb").read()
        assert not raw.startswith(b"SQLite format 3") and prods and prods[0]["description"].encode() not in raw
        db.set_backup_password("Self-Test-Pass-9")
        bk = db.backup(os.path.join(tmp, "st-backup.db"))
        assert open(bk, "rb").read(len(vault.MAGIC)) == vault.MAGIC
        db.restore(bk)
        assert len(db.list_products()) == len(prods) and db.health_check()[0]
        results["_db"] = db
        return f"encrypted, {len(prods)} sample products, cipher {db.conn.execute('PRAGMA cipher_version').fetchone()[0]}"

    def files():
        from . import io_utils
        db = results["_db"]
        prods = db.list_products()
        pdf, xlsx = os.path.join(tmp, "st.pdf"), os.path.join(tmp, "st.xlsx")
        if "db" in inspect.signature(io_utils.export_pdf).parameters:
            io_utils.export_pdf(pdf, db, prods, "Self test")
            io_utils.export_xlsx(xlsx, db, prods)
        else:
            io_utils.export_pdf(pdf, prods, "Self test")
            io_utils.export_xlsx(xlsx, prods)
        assert os.path.getsize(pdf) > 1000 and io_utils.read_file(xlsx)
        from reportlab.graphics.barcode import createBarcodeDrawing
        createBarcodeDrawing("UPCA", value="01234567890")
        __import__("defusedxml")             # protects Excel imports
        from reportlab.pdfgen import canvas  # a small Wil Fischer-style invoice, read back with the PDF reader
        from . import pdf_invoices
        inv_pdf = os.path.join(tmp, "inv.pdf")
        c = canvas.Canvas(inv_pdf)
        for i, line in enumerate(("WIL FISCHER COMPANIES", "Account: X Invoice#: 4871 PO#:", "Tue Nov 03, 2026",
                                  "ITEM# QTYDESCRIPTION PRICE DISC DEP EXT", "86030 2 22.60 0.70 0.00 43.80BUSCH LIGHT 30/12 CAN",
                                  "Cases: 2", "Total Sales 45.20")):
            c.drawString(40, 800 - i * 14, line)
        c.save()
        inv = pdf_invoices.read_invoice(inv_pdf)
        assert inv["ok"] and inv["lines"][0]["net"] == 21.90, inv
        return "PDF, Excel, barcode, PDF invoice reader"

    def sounds_check():
        from . import sounds
        for name in sounds.SOUNDS:
            assert os.path.getsize(sounds._file(name)) > 1000
        if sys.platform.startswith("win"):
            __import__("winsound")
        return f"{len(sounds.SOUNDS)} sounds ready"

    def license_and_updates():
        from . import license as lic
        from . import updater
        try:
            lic.read_key("AAAAA-BBBBB")
            raise AssertionError("bad key accepted")
        except ValueError:
            pass
        assert updater.allowed_url("https://raw.githubusercontent.com/x") and not updater.allowed_url("https://evil.com")
        return f"computer id {lic.computer_id()}"

    def screen():
        import tkinter as tk
        from .config import resource_path
        root = tk.Tk()
        root.withdraw()
        img = tk.PhotoImage(file=resource_path("assets", "logo.png"))
        size = f"{img.width()}x{img.height()}"
        root.update()
        root.destroy()
        return f"tk {tk.TkVersion}, logo {size}"

    for name, fn in (("windows_key_lock", windows_key_lock), ("database", database), ("files", files),
                     ("license_and_updates", license_and_updates), ("sounds", sounds_check), ("screen", screen)):
        if name == "files" and "_db" not in results:
            results[name] = "skipped (database failed)"
            ok = False
            continue
        check(name, fn)
    db = results.pop("_db", None)
    if db:
        db.close()
    results["passed"] = ok
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1
