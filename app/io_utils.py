"""Import / export (CSV, Excel) and PDF reports."""
import csv
import datetime
import os
import re
import subprocess
import sys

from . import calc

def export_columns(category=None):
    """Columns for export. With a category, price headers use its labels (e.g. '6 Btl SP')."""
    if category:
        lb = calc.labels(category)
        keys = calc.slots(category)
    else:
        lb = {"case": "Case", "pk12": "12 Pk / 6 Btl", "pk6": "6 Pk / 1 Btl", "s24": "Single 24oz", "s14": "Single 14oz"}
        keys = calc.ALL_SLOTS
    cols = [("category", "Category"), ("pallet", "Pallet"), ("item_no", "Item#"), ("description", "Description"),
            ("qty", "Qty"), ("price", "Price"), ("net", "Net"), ("dep", "Dep"), ("ext", "Ext"), ("upc", "UPC"),
            ("case_units", "Case Size")]
    cols += [(f"{k}_sp", f"{lb[k]} SP") for k in keys]
    cols += [(f"{k}_margin", f"{lb[k]} Margin %") for k in keys]
    return cols + [("notes", "Notes")]


EXPORT_COLUMNS = export_columns()

ALIASES = {
    "pallet": ["pallet", "palletno", "invoice"],
    "item_no": ["item", "itemno", "itemnumber", "item#", "sku"],
    "description": ["description", "desc", "name", "product", "productname"],
    "category": ["category", "type"],
    "qty": ["qty", "quantity", "cases"],
    "price": ["price", "listprice"],
    "net": ["net", "netcost", "cost", "netprice"],
    "dep": ["dep", "deposit"],
    "upc": ["upc", "barcode", "upccode"],
    "case_units": ["casesize", "units", "unitspercase", "cans", "caseunits", "pack"],
    "case_sp": ["casesp", "casesellingprice", "caseprice", "caseretail"],
    "pk12_sp": ["12pksp", "pk12sp", "12packsp", "12pkprice", "12pksellingprice", "12packprice",
                "6btlsp", "6bottlesp", "6btlprice", "12pk6btlsp"],
    "pk6_sp": ["6pksp", "pk6sp", "6packsp", "6pkprice", "6pksellingprice", "6packprice",
               "1btlsp", "btlsp", "bottlesp", "bottleprice", "singlesp", "6pk1btlsp"],
    "s24_sp": ["single24ozsp", "24ozsp", "24ozsinglesp", "s24sp", "24ozprice", "single24oz", "24oz"],
    "s14_sp": ["single14ozsp", "14ozsp", "14ozsinglesp", "s14sp", "14ozprice", "single14oz", "14oz"],
    "notes": ["notes", "note", "comment"],
}
NUMERIC = {"qty", "price", "net", "dep", "case_units", "case_sp", "pk12_sp", "pk6_sp", "s24_sp", "s14_sp"}


def _norm(h):
    return re.sub(r"[^a-z0-9#]", "", str(h or "").lower())


def map_headers(headers):
    lookup = {a.replace("#", ""): f for f, al in ALIASES.items() for a in al}
    lookup.update({a: f for f, al in ALIASES.items() for a in al})
    return {i: lookup.get(_norm(h)) or lookup.get(_norm(h).replace("#", "")) for i, h in enumerate(headers)}


def _rows_to_products(headers, rows, default_category="Beer", where=""):
    """Turns sheet rows into product dicts. Each dict gets '_row' (for error messages)
    and '_bad' (cells that were not valid numbers)."""
    mapping = map_headers(headers)
    if "description" not in mapping.values() and "item_no" not in mapping.values():
        raise ValueError(f"{where or 'The file'} needs at least a 'Description' or 'Item#' column.")
    out = []
    for n, row in enumerate(rows, start=2):
        if not row or not any(c not in (None, "") and str(c).strip() for c in row):
            continue
        p = {"_row": f"{where + ' ' if where else ''}row {n}", "_bad": []}
        for i, val in enumerate(row):
            f = mapping.get(i)
            if not f:
                continue
            if f in NUMERIC:
                v = calc.to_float(val)
                if v is None and val not in (None, "") and str(val).strip() not in ("", "-", "—"):
                    p["_bad"].append(f"{headers[i]} '{val}' is not a number.")
                if f == "case_units" and v is not None:
                    if v != int(v):
                        p["_bad"].append(f"{headers[i]} '{val}' must be a whole number.")
                    v = int(v)
                p[f] = v
            else:
                p[f] = "" if val is None else str(val).strip()
        cat = str(p.get("category") or default_category).strip().title()
        p["category"] = "Liquor" if cat in ("Liquor", "Wine", "Spirits") else "Beer"
        if not p.get("case_units"):
            prof = calc.profile(p["category"])
            p["case_units"] = calc.guess_case_units(p.get("description", ""), prof["default_units"], p["category"])
        for k in ("upc", "item_no"):
            if str(p.get(k, "")).endswith(".0"):
                p[k] = p[k][:-2]
        out.append(p)
    return out


def read_file(path, default_category="Beer"):
    """Excel: every sheet is read; a sheet named Beer or Liquor sets the category
    for rows that don't have a Category column."""
    if path.lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        out = []
        for ws in wb.worksheets:
            rows = list(ws.iter_rows(values_only=True))
            if len(rows) < 2 or not rows[0] or not any(rows[0]):
                continue
            name = ws.title.strip().title()
            cat = name if name in calc.CATEGORIES else default_category
            out += _rows_to_products(rows[0], rows[1:], cat, where=f"Sheet '{ws.title}'")
        return out
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows:
        return []
    return _rows_to_products(rows[0], rows[1:], default_category, where="")


def _tg(targets, category):
    """targets may be one dict or {category: dict}."""
    if targets and category in targets and isinstance(targets[category], dict):
        return targets[category]
    if targets and "Beer" in targets and isinstance(targets["Beer"], dict):
        return targets["Beer"]
    return targets or {}


def _export_rows(products, include_dep, targets):
    rows = []
    for p in products:
        d = dict(p)
        d.update(calc.compute(p, include_dep, _tg(targets, p.get("category"))))
        rows.append(d)
    return rows


def _cell(key, d):
    v = d.get(key)
    if v is None:
        return ""
    if key.endswith("_margin"):
        return round(v, 1)
    return v


def export_csv(path, products, include_dep=False, targets=None):
    rows = _export_rows(products, include_dep, targets)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([h for _, h in EXPORT_COLUMNS])
        for d in rows:
            w.writerow([_cell(k, d) for k, _ in EXPORT_COLUMNS])


def export_xlsx(path, products, include_dep=False, targets=None):
    """One sheet per tab (Beer, Liquor) with that tab's column names."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for cat in calc.CATEGORIES:
        cols = export_columns(cat)
        ws = wb.create_sheet(cat)
        ws.append([h for _, h in cols])
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="0D2F57" if cat == "Beer" else "6B3A0E")
        for d in _export_rows([p for p in products if p.get("category") == cat], include_dep, targets):
            ws.append([_cell(k, d) for k, _ in cols])
        widths = {"Description": 38, "UPC": 16}
        for i, (_, h) in enumerate(cols, 1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = widths.get(h, 13)
        ws.freeze_panes = "A2"
    wb.save(path)


def write_template(path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Category", "Pallet", "Item#", "Description", "Qty", "Price", "Net", "Dep", "UPC",
                    "Case Size", "Case SP", "12 Pk / 6 Btl SP", "6 Pk / 1 Btl SP", "Single 24oz SP", "Single 14oz SP"])
        w.writerow(["Beer", "180816", "56334", "BOULEVARD SPACE CAMPER 4/6 CAN", 1, 33.00, 33.00, 0,
                    "726959911074", 24, 42.99, 21.99, 11.49, "", ""])
        w.writerow(["Beer", "", "70001", "SAMPLE LAGER 12/24OZ CAN", 1, 36.00, 36.00, 0,
                    "", 12, 45.99, "", "", 3.99, ""])
        w.writerow(["Liquor", "", "L1001", "SAMPLE VODKA 12/750ML", 1, 180.00, 168.00, 0,
                    "", 12, 210.00, 109.99, 19.99, "", ""])


def _fmt_money(v):
    return "" if v is None else f"${v:,.2f}"


def _fmt_pct(v):
    return "" if v is None else f"{v:.1f}%"


def export_pdf(path, products, title, include_dep=False, targets=None):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    small = styles["BodyText"].clone("small", fontSize=7, leading=8)
    doc = SimpleDocTemplate(path, pagesize=landscape(letter), leftMargin=0.35 * inch,
                            rightMargin=0.35 * inch, topMargin=0.4 * inch, bottomMargin=0.4 * inch)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    all_rows = _export_rows(products, include_dep, targets)
    story = [Paragraph(title, styles["Title"]),
             Paragraph(f"Generated {stamp} &nbsp;|&nbsp; {len(all_rows)} products &nbsp;|&nbsp; Inventory value (Ext): "
                       f"{_fmt_money(sum(r['ext'] or 0 for r in all_rows))} &nbsp;|&nbsp; red = below target margin",
                       styles["Normal"])]
    for cat in calc.CATEGORIES:
        rows = [r for r in all_rows if r.get("category") == cat]
        if not rows:
            continue
        lb, tg, keys = calc.labels(cat), _tg(targets, cat), calc.slots(cat)
        head = ["Item#", "Description", "Qty", "Net", "Dep", "Ext", "Size"]
        head += [f"{calc.short_label(lb[k])} SP" for k in keys] + [f"{calc.short_label(lb[k])} %" for k in keys]
        n0 = 7
        data, low_cells = [head], []
        for r_i, d in enumerate(rows, start=1):
            data.append([
                d.get("item_no", ""), Paragraph(d.get("description", ""), small),
                f"{d.get('qty') or 0:g}", _fmt_money(d.get("net")), _fmt_money(d.get("dep")),
                _fmt_money(d.get("ext")), d.get("case_units") or ""]
                + [_fmt_money(d.get(f"{k}_sp")) for k in keys] + [_fmt_pct(d.get(f"{k}_margin")) for k in keys])
            for j, key in enumerate(keys):
                m, t = d.get(f"{key}_margin"), tg.get(key)
                if m is not None and t is not None and round(m, 1) < t:
                    low_cells.append((n0 + len(keys) + j, r_i))
        fixed = [0.5, 2.2 if len(keys) <= 3 else 1.75, 0.35, 0.55, 0.45, 0.6, 0.38]
        rest = (10.3 - sum(fixed)) / (2 * len(keys))
        widths = fixed + [rest] * (2 * len(keys))
        t = Table(data, colWidths=[w * inch for w in widths], repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0D2F57" if cat == "Beer" else "#6B3A0E")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5FA")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C9D3DF")),
            ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
        for c_i, r_i in low_cells:
            style.append(("TEXTCOLOR", (c_i, r_i), (c_i, r_i), colors.HexColor("#C62828")))
        t.setStyle(TableStyle(style))
        story += [Spacer(1, 10),
                  Paragraph(f"{cat} &nbsp;({len(rows)} products) &nbsp;- target margins: "
                            + ", ".join(f"{lb[k]} {tg.get(k, 0):g}%" for k in keys), styles["Heading3"]),
                  t]
    doc.build(story)
    return path


def open_file(path, action=None):
    if sys.platform.startswith("win"):
        if action == "print":
            os.startfile(path, "print")
        else:
            os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def plan_import(db, items):
    """Checks every imported row against what is already saved. Nothing is written.
    Returns (adds, updates, problems): adds/updates are lists of (row_label, data[, product_id]);
    problems is a list of 'row label: message' strings for rows that will be skipped."""
    adds, updates, problems = [], [], []
    seen = {}
    for p in items:
        row = p.get("_row", "row ?")
        incoming = {k: v for k, v in p.items() if not k.startswith("_") and v not in (None, "")}
        key = str(p.get("item_no") or "").strip()
        existing = db.find_by_item(key) if key else None
        if key and key in seen:                           # same Item# twice in the file: last one wins
            problems.append(f"{row}: Item# {key} also appears in {seen[key]}; this later row will be used.")
        if existing:
            merged = {**existing, **incoming}
        else:
            merged = {"qty": 0.0, "price": 0.0, "net": 0.0, "dep": 0.0, **incoming}
        merged["_bad"] = p.get("_bad")
        errors, warnings = calc.validate_product(merged)
        if errors:
            problems.append(f"{row}: skipped - {' '.join(errors)}")
            continue
        for w in warnings:
            problems.append(f"{row}: warning - {w}")
        data = {k: v for k, v in merged.items() if not k.startswith("_")}
        if key and key in seen:
            adds = [a for a in adds if str(a[1].get("item_no") or "") != key]
            updates = [u for u in updates if str(u[1].get("item_no") or "") != key]
        if key:
            seen[key] = row
        if existing:
            updates.append((row, data, existing["id"]))
        else:
            adds.append((row, data))
    return adds, updates, problems


def apply_import(db, adds, updates, user, filename):
    """Backs up first, then writes everything in ONE transaction (all or nothing)."""
    backup = db.safety_backup("before-import")
    with db.transaction():
        for _, data in adds:
            db.add_product(data, user, log=False)
        changes = 0
        for _, data, pid in updates:
            changes += len(db.update_product(pid, data, user, log=False, source=f"import {filename}"))
        db.log(f"Imported {filename}: {len(adds)} added, {len(updates)} updated, {changes} price change(s)",
               user, "import")
    return backup
