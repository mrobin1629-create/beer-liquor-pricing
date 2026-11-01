"""Shelf labels / price tags on standard Avery sheets (US Letter)."""
from reportlab.graphics import renderPDF
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from . import calc

SHEETS = {
    # name: cols, rows, label w, h, left margin, top margin, horizontal pitch, vertical pitch (inches)
    "5163": dict(title="Large - Avery 5163 / 8163 (2\" x 4\", 10 per sheet)", cols=2, rows=5, w=4.0, h=2.0,
                 left=0.15625, top=0.5, hp=4.1875, vp=2.0),
    "5160": dict(title="Small - Avery 5160 / 8160 (1\" x 2-5/8\", 30 per sheet)", cols=3, rows=10, w=2.625, h=1.0,
                 left=0.1875, top=0.5, hp=2.75, vp=1.0),
}
NAVY = colors.HexColor("#0D2F57")


def _barcode(code):
    try:                                   # loaded lazily: if barcodes are unavailable, labels still print
        from reportlab.graphics.barcode import createBarcodeDrawing
    except Exception:
        return None
    digits = "".join(ch for ch in str(code or "") if ch.isdigit())
    if not digits:
        return None
    tries = []
    if len(digits) in (11, 12):
        tries.append(("UPCA", digits))
    if len(digits) == 13:
        tries.append(("EAN13", digits))
    tries.append(("Code128", digits))
    for kind, val in tries:
        try:
            return createBarcodeDrawing(kind, value=val, barHeight=0.32 * inch, humanReadable=True, fontSize=6)
        except Exception:
            continue
    return None


def _fit(text, font, size, width, min_size=5):
    while size > min_size and stringWidth(text, font, size) > width:
        size -= 0.5
    return size


def _wrap(text, font, size, width, max_lines=2):
    words, lines, cur = (text or "").split(), [], ""
    for w in words:
        t = f"{cur} {w}".strip()
        if stringWidth(t, font, size) <= width:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and " ".join(lines) != " ".join(words):
        while lines[-1] and stringWidth(lines[-1] + "…", font, size) > width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


def _prices(p):
    lb = calc.labels(p.get("category"))
    return [(calc.short_label(lb[k]), p[f"{k}_sp"]) for k in calc.slots(p.get("category")) if p.get(f"{k}_sp")]


def _large(c, x, y, w, h, p, store, barcode):
    pad = 0.12 * inch
    c.setFillColor(NAVY)
    c.rect(x, y + h - 0.06 * inch, w, 0.06 * inch, stroke=0, fill=1)
    c.setFillColor(colors.black)
    lines = _wrap(p["description"], "Helvetica-Bold", 12, w - 2 * pad)
    ty = y + h - pad - 0.12 * inch
    for ln in lines:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(x + pad, ty, ln)
        ty -= 14
    prices = _prices(p)
    if prices:
        n = len(prices)
        bw = (w - 2 * pad) / n
        top = y + h * 0.60
        for i, (lbl, val) in enumerate(prices):
            bx = x + pad + i * bw
            c.setFont("Helvetica", 8)
            c.setFillColor(colors.HexColor("#555555"))
            c.drawCentredString(bx + bw / 2, top - 2, lbl.upper())
            txt = f"${val:,.2f}"
            size = _fit(txt, "Helvetica-Bold", 22 if n <= 3 else 17, bw - 4)
            c.setFillColor(colors.black)
            c.setFont("Helvetica-Bold", size)
            c.drawCentredString(bx + bw / 2, top - 4 - size, txt)
            if i:
                c.setStrokeColor(colors.HexColor("#CCCCCC"))
                c.line(bx, top - 2 - 30, bx, top + 6)
    foot_y = y + 0.1 * inch
    if barcode:
        d = _barcode(p.get("upc"))
        if d:
            scale = min(1.0, (w * 0.5) / d.width)
            c.saveState()
            c.translate(x + pad, foot_y)
            c.scale(scale, scale)
            renderPDF.draw(d, c, 0, 0)
            c.restoreState()
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor("#555555"))
    info = f"Item# {p.get('item_no') or '-'}   {p.get('case_units') or ''} per case"
    c.drawRightString(x + w - pad, foot_y + 12, info)
    if store:
        c.drawRightString(x + w - pad, foot_y + 2, store[:40])
    c.setFillColor(colors.black)


def _small(c, x, y, w, h, p, store, barcode):
    pad = 0.08 * inch
    avail = w - 2 * pad
    desc = p["description"] or ""
    size = _fit(desc, "Helvetica-Bold", 8, avail, 7)
    while stringWidth(desc, "Helvetica-Bold", size) > avail and len(desc) > 3:   # truncate, don't shrink further
        desc = desc[:-2].rstrip() + "…"
    c.setFont("Helvetica-Bold", size)
    c.drawString(x + pad, y + h - pad - size, desc)
    prices = [f"{lbl} ${val:,.2f}" for lbl, val in _prices(p)]
    if prices:
        rows = [prices] if len(prices) <= 3 else [prices[:3], prices[3:]]
        big = 13 if len(prices) == 1 else 10.5 if len(rows) == 1 else 8.5
        size = min(_fit("   ".join(r), "Helvetica-Bold", big, avail, 6.5) for r in rows)
        ty = y + h * (0.40 if len(rows) == 1 else 0.52)
        for r in rows:
            c.setFont("Helvetica-Bold", size)
            c.drawString(x + pad, ty, "   ".join(r))
            ty -= size + 2
    c.setFont("Helvetica", 5.5)
    c.setFillColor(colors.HexColor("#555555"))
    c.drawString(x + pad, y + pad * 0.6, f"Item# {p.get('item_no') or '-'}  UPC {p.get('upc') or '-'}")
    c.setFillColor(colors.black)


def make_labels(path, products, size="5163", start=1, outlines=False, barcode=True, store=""):
    """Writes a PDF of labels. `start` skips used labels on a partly used sheet (1 = first label)."""
    sh = SHEETS.get(size, SHEETS["5163"])
    per = sh["cols"] * sh["rows"]
    c = canvas.Canvas(path, pagesize=letter)
    c.setTitle("Shelf labels")
    pw, ph = letter
    slot = max(1, int(start)) - 1
    draw = _large if size == "5163" else _small
    for p in products:
        if slot and slot % per == 0:
            c.showPage()
        i = slot % per
        col, row = i % sh["cols"], i // sh["cols"]
        x = (sh["left"] + col * sh["hp"]) * inch
        y = ph - (sh["top"] + row * sh["vp"] + sh["h"]) * inch
        if outlines:
            c.setStrokeColor(colors.HexColor("#BBBBBB"))
            c.roundRect(x, y, sh["w"] * inch, sh["h"] * inch, 6, stroke=1, fill=0)
        draw(c, x, y, sh["w"] * inch, sh["h"] * inch, p, store, barcode)
        slot += 1
    c.save()
    return path
