"""Reads supplier invoice PDFs (offline, pure Python: pypdf).

Known layouts (from real invoices):
  * HUB KCCC LLC / KC Cash & Carry (hubtobacco.com)  - cigarettes, smokeless, candy...
  * Southern Glazer's                                 - liquor
  * Wil Fischer Companies                             - beer
Each line comes back as a plain dict; each app turns those into its own products.
Every invoice is checked against its own printed total, so a misread line is caught before anything is saved.
"""
import datetime
import re

MONEY = r"-?[\d,]*\.\d\d"


class PdfInvoiceError(ValueError):
    pass


def _num(s):
    s = (s or "").replace(",", "").strip()
    neg = s.endswith("-")
    v = float(s.rstrip("-") or 0)
    return -v if neg else v


def _text(path, mode):
    from pypdf import PdfReader
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                raise PdfInvoiceError("This PDF is password protected.")
        pages = []
        for p in reader.pages:
            try:
                pages.append(p.extract_text(extraction_mode="layout") if mode == "layout" else p.extract_text())
            except Exception:
                pages.append(p.extract_text() if mode == "layout" else "")
        return "\n".join(t or "" for t in pages)
    except PdfInvoiceError:
        raise
    except Exception as ex:
        raise PdfInvoiceError(f"Couldn't read this PDF ({type(ex).__name__}). Is it damaged?")


def _date(s):
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%b %d, %Y"):
        try:
            return datetime.datetime.strptime(s.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def _line(**kw):
    d = {"item_no": "", "description": "", "qty": None, "price": None, "net": None, "dep": None, "ext": None,
         "upc": "", "case_units": None, "allowance": None, "section": "", "kind": "", "note": ""}
    d.update(kw)
    return d


# ---------------------------------------------------------------- HUB KCCC LLC (KC Cash & Carry)
_HUB_ITEM = re.compile(r"^\s*(\d{4,8})\s+(\d+)\s+(\d+)\s+(\d+)\s+([A-Z]{2,4})\s+(.+?)\s+(\d{6,14})\s+(" + MONEY + r")\s+("
                       + MONEY + r")\s*$")
_HUB_ALLOW = re.compile(r"\*\*\*\s*Charges/Allowances\s*\*\*\*\s+([\d,]*\.\d\d)(-?)")
_HUB_SECTION = re.compile(r"^\s{15,}([A-Z][A-Z0-9 /&'.,-]*[A-Z])\s{3,}(" + MONEY + r")\s*$")


def _hub(text):
    lines, pending, sections = [], [], {}
    for raw in text.splitlines():
        m = _HUB_ITEM.match(raw)
        if m:
            item, ordered, shipped, pack, unit, desc, upc, price, amount = m.groups()
            ln = _line(item_no=item, description=" ".join(desc.split()), qty=float(shipped), price=_num(price),
                       net=_num(price), ext=_num(amount), upc=upc, case_units=int(pack), unit=unit,
                       note="" if ordered == shipped else f"ordered {ordered}, shipped {shipped}")
            lines.append(ln)
            pending.append(ln)
            continue
        m = _HUB_ALLOW.search(raw)
        if m and lines:
            v = _num(m.group(1))
            lines[-1]["allowance"] = v if m.group(2) == "-" else -v      # '5.00-' = a 5.00 allowance per unit
            continue
        m = _HUB_SECTION.match(raw)
        if m and pending:
            name = m.group(1).strip()
            for ln in pending:
                ln["section"] = name
            sections[name] = _num(m.group(2))
            pending = []
    for ln in pending:
        ln["section"] = ln["section"] or "OTHER"
    inv = re.search(r"INVOICE NO\.\s+(\S+)", text)
    dt = re.search(r"INVOICE DATE\s+(\d{1,2}/\d{1,2}/\d{2,4})", text)
    total = None
    m = re.search(r"BALANCE DUE\s*\n\s*\n?\s*\d+\s+\d+\s+\d+\s+\d+\s+\d+\s+(" + MONEY + ")", text)
    if m:
        total = _num(m.group(1))
    # check: each section's printed total, and the invoice subtotal
    checks = []
    for name, tot in sections.items():
        got = round(sum(ln["ext"] for ln in lines if ln["section"] == name), 2)
        checks.append((name.title(), got, tot))
    if total is not None:
        checks.append(("Invoice subtotal", round(sum(ln["ext"] for ln in lines), 2), total))
    return {"supplier": "HUB KCCC LLC (KC Cash & Carry)", "invoice_no": inv.group(1) if inv else "",
            "date": _date(dt.group(1)) if dt else "", "lines": lines, "checks": checks, "kind": "tobacco"}


# ---------------------------------------------------------------- Southern Glazer's
_SG_ITEM = re.compile(r"^\s*(\d+)/(\d+)\s+(?:(\d+)/(\d+)\s+)?(.+?)\s+(" + MONEY + r")\s+(" + MONEY + r")\s+(" + MONEY
                      + r")\s+(" + MONEY + r")\s*$")
_SG_INFO = re.compile(r"ITEM#:\s*(\S+)\s+BPC:\s*(\d+)(?:\s+SIZE:\s*(\S+))?")
_SG_UPC = re.compile(r"UPC:\s*([\d-]{8,})")


def _glazers(text):
    lines = []
    for raw in text.splitlines():
        m = _SG_ITEM.match(raw)
        if m:
            cs_o, cs_d, b_o, b_d, desc, price, disc, net, total = m.groups()
            lines.append(_line(description=" ".join(desc.split()), qty=float(cs_d), price=_num(price),
                               net=_num(net), ext=_num(total), bottles=int(b_d or 0),
                               note=("" if cs_o == cs_d else f"ordered {cs_o}, delivered {cs_d}")))
            continue
        if not lines:
            continue
        m = _SG_INFO.search(raw)
        if m:
            lines[-1]["item_no"], lines[-1]["case_units"] = m.group(1), int(m.group(2))
            size = (m.group(3) or "").rstrip(".").replace(".L", "L")
            if size and size.lower() not in lines[-1]["description"].lower():
                lines[-1]["description"] += f" {size}"
            continue
        m = _SG_UPC.search(raw)
        if m:
            lines[-1]["upc"] = m.group(1).replace("-", "")
    for ln in lines:                                     # loose bottles count as part of a case
        if ln.get("bottles") and ln.get("case_units"):
            ln["qty"] = round(ln["qty"] + ln["bottles"] / ln["case_units"], 3)
    inv = re.search(r"INVOICE\s*\n\s*(\d{6,})", text)
    dt = re.search(r"INVOICE DATE.*\n.*?(\d{1,2}/\d{1,2}/\d{4})", text)
    total = re.search(r"TOTAL NET AMOUNT\s*\n.*?(" + MONEY + r")\s*$", text, re.M)
    checks = []
    if total:
        checks.append(("Total net amount", round(sum(ln["ext"] for ln in lines), 2), _num(total.group(1))))
    return {"supplier": "Southern Glazer's", "invoice_no": inv.group(1) if inv else "",
            "date": _date(dt.group(1)) if dt else "", "lines": lines, "checks": checks, "kind": "liquor"}


# ---------------------------------------------------------------- Wil Fischer Companies
_WF_ITEM = re.compile(r"^\s*(\d{3,8})\s+(-?\d+)\s+(" + MONEY + r")\s+(" + MONEY + r")\s+(" + MONEY + r")\s+(" + MONEY
                      + r")\s*(.*)$")


def _wilfischer(text):
    lines, in_items = [], False
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("ITEM#"):
            in_items = True
            continue
        if not in_items:
            continue
        if s.startswith("Cases:"):
            break
        m = _WF_ITEM.match(s)
        if m:
            item, qty, price, disc, dep, ext, desc = m.groups()
            p, d = _num(price), _num(disc)
            lines.append(_line(item_no=item, description=" ".join(desc.split()), qty=float(qty), price=p,
                               net=round(p - d, 2), dep=_num(dep), ext=_num(ext)))
        elif lines and s and not s.startswith("---"):
            if re.search(r"out of stock", s, re.I):
                lines[-1]["note"] = "out of stock"
            elif not re.match(r"^-?\d+\s", s):
                lines[-1]["description"] = f"{lines[-1]['description']} {' '.join(s.split())}".strip()
    inv = re.search(r"Invoice#:\s*(\S+)", text)
    dt = re.search(r"\b([A-Z][a-z]{2} \d{1,2}, \d{4})\b", text)
    sales = re.search(r"Total Sales\s+(" + MONEY + ")", text)
    checks = []
    if sales:
        checks.append(("Total sales", round(sum(ln["qty"] * ln["price"] for ln in lines), 2), _num(sales.group(1))))
    return {"supplier": "Wil Fischer Companies", "invoice_no": inv.group(1) if inv else "",
            "date": _date(dt.group(1)) if dt else "", "lines": lines, "checks": checks, "kind": "beer"}


# ---------------------------------------------------------------- entry point
LAYOUTS = (("HUB KCCC", "layout", _hub), ("hubtobacco", "layout", _hub), ("Southern Glazer", "layout", _glazers),
           ("WIL FISCHER", "plain", _wilfischer))


def read_invoice(path):
    """{'supplier', 'invoice_no', 'date', 'kind', 'lines': [...], 'checks': [(what, read, printed)], 'ok': bool}"""
    plain = _text(path, "plain")
    if len(plain.strip()) < 20:
        raise PdfInvoiceError("This PDF has no readable text (it's probably a scan or photo), so it can't be imported. "
                              "Ask the supplier for the PDF or Excel version of the invoice.")
    for marker, mode, parser in LAYOUTS:
        if marker.lower() in plain.lower():
            text = plain if mode == "plain" else _text(path, "layout")
            inv = parser(text)
            if not inv["lines"]:
                raise PdfInvoiceError(f"This looks like a {inv['supplier']} invoice, but no item lines were found.")
            inv["ok"] = all(abs(a - b) < 0.015 for _, a, b in inv["checks"])
            return inv
    first = next((ln.strip() for ln in plain.splitlines() if ln.strip()), "")[:60]
    raise PdfInvoiceError("This supplier's PDF layout isn't known yet"
                          + (f" ('{first}')" if first else "") + ". Known: HUB KCCC (KC Cash & Carry), "
                          "Southern Glazer's, Wil Fischer. Send a sample to Robin Mishra to add it, "
                          "or import the supplier's Excel/CSV file instead.")


def check_lines(inv):
    """Readable lines for the import report: did every total match?"""
    out = []
    for what, got, printed in inv["checks"]:
        ok = abs(got - printed) < 0.015
        out.append(f"PDF check - {what}: read ${got:,.2f}, invoice says ${printed:,.2f} "
                   + ("✔" if ok else "✖ DOES NOT MATCH - check the lines before importing"))
    return out
