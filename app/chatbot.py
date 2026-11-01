"""Offline help assistant. Works with no internet: it answers how-to
questions and can look things up in your own data."""
import re

from . import calc

HELP_TOPICS = [
    (("add", "new product", "new item", "enter"),
     "To add a product click '+ Add Product' in the toolbar. Fill in the ticket columns "
     "(Item#, Description, Qty, Price, Net, Dep, UPC), set the Case Size (cans per case), then "
     "type your Case, 12 Pk and 6 Pk selling prices. Margins update live while you type."),
    (("edit", "change", "modify", "update price", "selling price", "s.p"),
     "Select a row and click Edit, or double-click any cell. Double-clicking a selling price, "
     "Qty, Net, Price, Dep or Case Size cell lets you type the new value right in the table; "
     "press Enter to save or Esc to cancel."),
    (("delete", "remove"),
     "Select one or more rows (hold Ctrl or Shift) and click Delete. Only admin users can delete."),
    (("margin", "formula", "calculate", "how is"),
     "Margin % = (Selling Price - Cost) / Selling Price x 100. Case cost is the Net price. "
     "Beer: Case = one complete box. 12 Pk cost = Net x 12 / Case Size (a 2/12 case = Net / 2), "
     "6 Pk cost = Net x 6 / Case Size (a 4/6 case = Net / 4), Single 24oz or 14oz can = Net / cans in the case. "
     "Liquor: 6 Btl cost = Net x 6 / Case Size, 1 Btl cost = Net / Case Size. "
     "Example: Net $33.00, 24 cans: a 6 pk costs $8.25, so selling at $10.99 gives a 24.9% margin. "
     "You can include the deposit in cost under Home > target margin bar."),
    (("suggest", "target"),
     "The target margin boxes above each table (Beer and Liquor have their own) set your goal for each size. Any product "
     "under target is highlighted red. In the Add/Edit window, 'Use suggested' fills a selling "
     "price that hits the target: Suggested SP = Cost / (1 - Target%)."),
    (("import",),
     "Go to Import / Export > Import. CSV and Excel (.xlsx) work. Every row is checked first and you see a "
     "report (rows with errors are skipped, with the row number and reason). Then a backup is made and all rows "
     "are saved together, so if anything fails nothing changes. Rows with an Item# you already have are updated, "
     "and price changes go into Price History. Click 'Save import template' for a ready-made file."),
    (("export", "excel", "csv"),
     "Import / Export > Export to Excel or CSV saves every product with all margins included."),
    (("pdf", "report"),
     "Reports (PDF) has three reports: all products, low-margin items and out-of-stock items. "
     "Low margins print in red."),
    (("print",),
     "Click Print in the toolbar or on the Reports page. A PDF is made and sent to your default printer."),
    (("backup", "restore", "usb", "move", "another computer", "carry", "transfer"),
     "Backup > Back up now saves a single .db file containing everything. To move to another "
     "computer: install the app there, then Backup > Restore from file. Automatic backups are made when the "
     "app closes, before every import, before every restore and before a database upgrade; the newest 30 are "
     "kept. Double-click one on the Backup page to restore it."),
    (("audit", "who changed", "log", "history of changes", "sign-in", "login attempt"),
     "Audit Log (sidebar, admin only) records sign-ins, failed sign-ins, sign-outs, product changes, imports, "
     "exports, backups, restores, user changes and settings. Filter by type, search, or export to CSV."),
    (("price history", "old price", "price change", "previous price"),
     "Every time a price, net, deposit, case size or selling price changes, the old and new value are recorded. "
     "See them in Audit Log > Price History, or open a product with Edit and click 'Price history'."),
    (("health", "integrity", "corrupt", "damaged", "check database"),
     "Backup > Run health check verifies SQLite integrity, the database version, users, target margins and "
     "product values. A quick check also runs every time the app starts."),
    (("scan", "barcode", "scanner", "upc"),
     "Click the Scan box (or press F2) and scan a barcode with a USB scanner. Mode 'Open' opens the product to "
     "edit; mode 'Select' adds it to the selection so you can scan several items, then click Labels or Bulk Update. "
     "If the UPC isn't found, the app offers to add it with the UPC filled in. Leading zeros and missing check "
     "digits are handled."),
    (("label", "tag", "shelf", "avery"),
     "Click 'Labels' (or Ctrl+L). Choose selected/scanned products, everything whose price changed since a date, or "
     "a whole tab. Sheets: Avery 5163 large (10 per sheet, all prices + barcode) or Avery 5160 small (30 per sheet). "
     "'Start at label #' lets you use up a partly used sheet."),
    (("bulk", "raise", "increase all", "many prices", "percent"),
     "Select products (or scan them in Select mode), then click 'Bulk Update' (Ctrl+B). Change by %, by $, set to "
     "your target margin, set to a margin you type, or an exact price. You see a preview of old vs new prices and "
     "margins before anything is saved; a backup is made and every change goes into Price History."),
    (("round", ".99", ".49", "ending"),
     "Click '⚙ Pricing' to pick a rounding rule for suggested prices and bulk updates: none, next price ending in 9, "
     ".49/.99, or .99. Prices always round up so they never drop below your target."),
    (("cost change", "cost went up", "price increase from supplier", "alert", "invoice"),
     "When an import changes Net costs, a Cost Changes window opens automatically showing old vs new margins and "
     "suggested prices; apply them in one click and print labels. You can also open it any time from Reports > "
     "Cost changes."),
    (("shortcut", "keyboard", "hotkey"),
     "Shortcuts on the Home screen: F2 scan, Ctrl+F search, Ctrl+N new product, Ctrl+E edit, Ctrl+B bulk update, "
     "Ctrl+L labels, Ctrl+P print, F5 refresh, Delete to delete."),
    (("remember",),
     "Tick 'Remember me' on the sign-in window to keep your username filled in next time. Passwords are never "
     "stored, so you still type it each time."),
    (("invalid", "negative", "validation", "error"),
     "The app won't save negative prices, a selling price of 0, a case size that isn't a whole number from 1 to 500, "
     "or a target margin of 100% or more. Selling below cost is allowed, but it asks you to confirm."),
    (("license", "licence", "registration", "trial", "computer id", "activate", "key"),
     "The app has a 14-day free trial. To keep using it, go to About > License, copy your Computer ID (or click "
     "'Copy request message') and send it to Robin Mishra. Paste the key you get back and click Activate. "
     "A key works on one computer for one year; your data is never deleted when a trial or license ends."),
    (("check for update", "new version available", "auto update"),
     "About > Check for updates downloads the newest version and installs it over this one (needs internet). "
     "A backup is made first, and your data, license and settings are kept. A yellow link in the footer "
     "appears when a new version is out."),
    (("version", "upgrade", "new version", "update the app", "updates"),
     "To update, just run the new setup file over the old one. Your data is stored in a separate "
     "folder and is never touched by the installer. Before any database upgrade, the app takes a "
     "backup automatically."),
    (("user", "password", "login", "admin"),
     "Users page (admin only): add users as admin or clerk, reset passwords and delete accounts. "
     "Change your own password there too. The first login is admin / admin, change it right away."),
    (("liquor", "bottle", "beer tab", "tab"),
     "There are two tabs: Beer (Case / 12 Pk / 6 Pk) and Liquor (Case / 6 Btl / 1 Btl). Each has its own "
     "target margins. Click a tab before '+ Add Product' and the new product goes into that tab. To move a "
     "product, edit it and change Category. For liquor, Case Size is bottles per case: '12/750ML' = 12."),
    (("single", "24oz", "14oz", "24 oz", "14 oz"),
     "Beer has two single-can columns: Single 24oz and Single 14oz. Fill in the one that fits the product. "
     "Single cost = Net / cans in the case, e.g. a $36.00 case of 12 x 24oz cans = $3.00 per can. "
     "Set Case Size to the number of cans: '12/24OZ' is detected as 12."),
    (("case size", "4/6", "2/12", "cans per case", "units"),
     "Case Size is how many cans/bottles are in one case. '4/6' means 4 six-packs = 24. "
     "'2/12' = 24. The app guesses this from the description but you can change it. "
     "If a case has fewer than 12 units, the 12 Pk margin shows as blank."),
    (("out of stock", "oos"),
     "Products with Qty 0 are shown greyed out. Ask me 'out of stock' to list them."),
    (("search", "find"),
     "Type in the search box above the table. It matches description, Item#, UPC, pallet and category."),
]

MENU = ("I can help with: adding/editing products, margin formula, target margins, import, export, "
        "PDF reports, print, backup/restore, updates and users. I can also check your data, try:\n"
        "  - 'low margin'\n  - 'out of stock'\n  - 'stats'\n  - 'margin for 56334' or 'margin for space camper'\n"
        "  - 'price for cost 8.25 at 30%'\n  - 'margin cost 8.25 sell 10.99'")

LABELS = {"case": "Case", "pk12": "12 Pk", "pk6": "6 Pk"}


def _money(v):
    return "-" if v is None else f"${v:,.2f}"


def _pct(v):
    return "-" if v is None else f"{v:.1f}%"


class ChatBot:
    def __init__(self, db):
        self.db = db

    def _computed(self, products=None):
        tgs, inc = self.db.all_targets(), self.db.include_dep()
        products = self.db.list_products() if products is None else products
        rnd = self.db.rounding()
        return [(p, calc.compute(p, inc, tgs.get(p.get("category"), tgs["Beer"]), rnd)) for p in products], tgs

    def _describe(self, p):
        (pair,), tgs = self._computed([p])
        c = pair[1]
        tg = tgs.get(p.get("category"), tgs["Beer"])
        lbl = calc.labels(p.get("category"))
        lines = [f"{p['description']} [{p.get('category', 'Beer')}] (Item# {p['item_no']}, UPC {p['upc'] or '-'}) - "
                 f"Qty {p['qty']:g}, Net {_money(p['net'])}, {p['case_units']} per case"]
        for k in calc.slots(p.get("category")):
            lines.append(f"  {lbl[k]}: cost {_money(c[k + '_cost'])}, sell {_money(p.get(k + '_sp'))}, "
                         f"margin {_pct(c[k + '_margin'])} (target {tg[k]:g}%, suggested price "
                         f"{_money(c[k + '_suggested'])})")
        return "\n".join(lines)

    def respond(self, text):
        t = (text or "").strip().lower()
        if not t:
            return "Type a question, for example 'how do I import' or 'low margin'."
        if re.fullmatch(r"(hi|hello|hey|salam|namaste)\W*", t):
            return "Hi! " + MENU
        if t in ("help", "?", "menu", "what can you do"):
            return MENU

        nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", t)]
        # price for cost X at Y%
        if ("price" in t or "sell" in t) and "%" in t and len(nums) >= 2 and "margin cost" not in t:
            cost, pct = nums[0], nums[1]
            sp = calc.suggested_price(cost, pct)
            if sp is None:
                return "The margin must be below 100%."
            return f"To make {pct:g}% on a cost of {_money(cost)}, sell at {_money(sp)}."
        # margin cost X sell Y
        if "margin" in t and "cost" in t and ("sell" in t or "sp" in t) and len(nums) >= 2:
            m = calc.margin(nums[1], nums[0])
            return f"Cost {_money(nums[0])}, selling {_money(nums[1])}: margin {_pct(m)}, profit {_money(nums[1] - nums[0])}."

        if "low margin" in t or "below target" in t or "under target" in t:
            rows, _ = self._computed()
            low = [p for p, c in rows if c["low_margin"]]
            if not low:
                return "Every product with a selling price is at or above your target margins."
            return f"{len(low)} product(s) below target:\n" + "\n".join(
                f"  - {p['item_no']} {p['description']}" for p in low[:25])
        if "missing" in t or "no price" in t or "no selling" in t:
            rows, _ = self._computed()
            miss = [p for p, _ in rows if not p.get("case_sp")]
            if not miss:
                return "All products have a case selling price."
            return f"{len(miss)} product(s) have no case selling price yet:\n" + "\n".join(
                f"  - {p['item_no']} {p['description']}" for p in miss[:25])
        if "out of stock" in t or t == "oos":
            rows, _ = self._computed()
            oos = [p for p, c in rows if c["out_of_stock"]]
            if not oos:
                return "Nothing is out of stock."
            return f"{len(oos)} out of stock:\n" + "\n".join(f"  - {p['item_no']} {p['description']}" for p in oos[:25])
        if any(w in t for w in ("stats", "summary", "how many", "count", "total value", "inventory value")):
            rows, _ = self._computed()
            total = sum(c["ext"] for _, c in rows)
            beer = sum(1 for p, _ in rows if p.get("category") != "Liquor")
            return (f"{len(rows)} products ({beer} beer, {len(rows) - beer} liquor), {sum(c['out_of_stock'] for _, c in rows)} out of stock, "
                    f"{sum(c['low_margin'] for _, c in rows)} below target margin. "
                    f"Inventory value (Ext): {_money(total)}.")

        m = re.search(r"(?:margin|price|details|info|show|find|lookup|look up)\s+(?:for|of|on)?\s*(.+)", t)
        if m and not any(k in t for k in ("how", "formula", "calculate")):
            q = m.group(1).strip(" ?.")
            found = self.db.list_products(q)
            if len(found) == 1:
                return self._describe(found[0])
            if found:
                return f"{len(found)} matches - be more specific:\n" + "\n".join(
                    f"  - {p['item_no']} {p['description']}" for p in found[:15])
            return f"No product matches '{q}'."
        if re.fullmatch(r"\d{4,14}", t):
            found = self.db.list_products(t)
            if found:
                return "\n\n".join(self._describe(p) for p in found[:3])

        best, score = None, 0
        for keys, answer in HELP_TOPICS:
            s = sum(len(k) for k in keys if k in t)
            if s > score:
                best, score = answer, s
        if best:
            return best

        found = self.db.list_products(t) if len(t) >= 3 else []
        if len(found) == 1:
            return self._describe(found[0])
        return "I'm not sure about that one. " + MENU
