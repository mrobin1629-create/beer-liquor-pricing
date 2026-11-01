"""All pricing / margin math lives here so it is easy to check and test.

Cost basis = NET case cost (what you actually paid per case).
  case cost  = net (+ dep if 'include deposit in cost' is turned on)
  12 pk cost = case cost * 12 / case size
  6 pk cost  = case cost *  6 / case size
  margin %   = (selling price - cost) / selling price * 100
  suggested selling price = cost / (1 - target margin %)
"""
import re

# Selling-price slots. Each slot <key> is stored in DB column <key>_sp.
# pack size None = whole case; a number = that many units out of the case.
#   Beer:   Case (one box) | 12 Pk (2/12 per case) | 6 Pk (4/6 per case) | Single 24oz | Single 14oz
#   Liquor: Case | 6 Btl | 1 Btl
ALL_SLOTS = ("case", "pk12", "pk6", "s24", "s14")
PROFILES = {
    "Beer": {
        "packs": (("case", None, "Case"), ("pk12", 12, "12 Pk"), ("pk6", 6, "6 Pk"),
                  ("s24", 1, "Single 24oz"), ("s14", 1, "Single 14oz")),
        "default_units": 24, "unit": "cans", "icon": "🍺",
        "title": "Beer  (Case / 12 Pk / 6 Pk / Singles)",
        "targets": {"case": 25, "pk12": 25, "pk6": 30, "s24": 30, "s14": 30},
    },
    "Liquor": {
        "packs": (("case", None, "Case"), ("pk12", 6, "6 Btl"), ("pk6", 1, "1 Btl")),
        "default_units": 12, "unit": "bottles", "icon": "🥃",
        "title": "Liquor  (Case / 6 Btl / 1 Btl)",
        "targets": {"case": 20, "pk12": 25, "pk6": 30},
    },
}
CATEGORIES = tuple(PROFILES)
PACKS = tuple((k, size) for k, size, _ in PROFILES["Beer"]["packs"])


def profile(category):
    return PROFILES.get(category if category in PROFILES else "Beer")


def labels(category):
    return {k: lbl for k, _, lbl in profile(category)["packs"]}


def slots(category):
    return tuple(k for k, _, _ in profile(category)["packs"])


def short_label(label):
    return label.replace("Single ", "")


def to_float(v, default=None):
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("$", "").replace(",", "").replace("%", "")
    if s in ("", "-", "—"):
        return default
    try:
        return float(s)
    except ValueError:
        return default


def guess_case_units(description, default=24, category="Beer"):
    """Beer: '4/6 CAN' -> 24, '2/12 CAN' -> 24, '12/24OZ CAN' -> 12, '1/24 14OZ' -> 24.
    Liquor: '12/750ML' -> 12, '6/1.75L' -> 6."""
    desc = description or ""
    if category != "Liquor":
        m = re.search(r"\b(\d{1,2})\s*/\s*\d+(?:\.\d+)?\s*oz\b", desc, re.I)   # '12/24OZ' = 12 cans
        if m and 1 <= int(m.group(1)) <= 48:
            return int(m.group(1))
    if category == "Liquor":
        m = re.search(r"\b(\d{1,2})\s*/\s*(\d+(?:\.\d+)?)\s*(ml|l|lt|ltr|oz)\b", desc, re.I)
        return int(m.group(1)) if m and 1 <= int(m.group(1)) <= 60 else profile("Liquor")["default_units"]
    m = re.search(r"\b(\d{1,2})\s*/\s*(\d{1,2})\b", desc)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if b in (4, 6, 8, 12, 15, 18, 24, 30) and 1 <= a * b <= 48:
            return a * b
    return default


def case_cost(net, dep=0.0, include_dep=False):
    net = to_float(net, 0.0)
    return net + (to_float(dep, 0.0) if include_dep else 0.0)


def pack_cost(cost_of_case, case_units, pack_size):
    units = to_float(case_units, 0) or 0
    if pack_size is None:
        return cost_of_case
    if units < pack_size or units <= 0:
        return None          # e.g. a 6-can case cannot be sold as a 12 pk
    return cost_of_case * pack_size / units


def margin(selling_price, cost):
    sp = to_float(selling_price)
    if sp is None or sp <= 0 or cost is None:
        return None
    return (sp - cost) / sp * 100.0


ROUNDING = {
    "none": "No rounding (exact)",
    "x9": "Up to the next price ending in 9  (11.73 -> 11.79)",
    "49_99": "Up to .49 or .99  (11.20 -> 11.49, 11.79 -> 11.99)",
    "99": "Up to .99  (11.20 -> 11.99)",
}


def round_price(v, mode="none"):
    """Rounds UP, so a rounded price never drops below the target margin."""
    if v is None:
        return None
    cents = int(round(v * 100 - 1e-6 + 0.4999))      # ceil to whole cents
    if mode == "x9":
        cents += (9 - cents % 10) % 10
    elif mode == "99":
        cents += (99 - cents % 100) % 100
    elif mode == "49_99":
        r = cents % 100
        cents += (49 - r) if r <= 49 else (99 - r)
    else:
        return round(v, 2)
    return cents / 100


def suggested_price(cost, target_pct, rounding="none"):
    t = to_float(target_pct)
    if cost is None or t is None or t >= 100:
        return None
    return round_price(cost / (1 - t / 100.0), rounding)


def compute(p, include_dep=False, targets=None, rounding="none"):
    """Return all derived numbers for one product dict (pack sizes follow its category)."""
    targets = targets or {}
    packs = tuple((k, size) for k, size, _ in profile(p.get("category"))["packs"])
    qty = to_float(p.get("qty"), 0.0)
    net = to_float(p.get("net"), 0.0)
    dep = to_float(p.get("dep"), 0.0)
    out = {"ext": round(qty * (net + dep), 2)}
    cc = case_cost(net, dep, include_dep)
    low = False
    for key, size in packs:
        cost = pack_cost(cc, p.get("case_units"), size)
        m = margin(p.get(f"{key}_sp"), cost)
        out[f"{key}_cost"] = cost
        out[f"{key}_margin"] = m
        out[f"{key}_suggested"] = suggested_price(cost, targets.get(key), rounding)
        tgt = to_float(targets.get(key))
        if m is not None and tgt is not None and round(m, 1) < tgt:
            low = True
    out["low_margin"] = low
    out["out_of_stock"] = qty <= 0
    return out


# ----------------------------------------------------------------- validation
MAX_MONEY = 100000.0


def validate_target(v):
    """Target margin is a % of selling price, so it must be 0 or more and below 100."""
    if v is None:
        return "Target margin must be a number."
    if v < 0 or v >= 100:
        return "Target margin must be from 0 up to (not including) 100%."
    return None


def validate_product(d):
    """Returns (errors, warnings). Errors block saving; warnings ask the user to confirm."""
    errors, warnings = list(d.get("_bad") or []), []
    if not str(d.get("description") or "").strip():
        errors.append("Description is required.")
    for f, lbl in (("qty", "Qty"), ("price", "Price"), ("net", "Net"), ("dep", "Deposit")):
        v = d.get(f)
        if v is None:
            continue
        if not isinstance(v, (int, float)):
            errors.append(f"{lbl} must be a number.")
        elif v < 0:
            errors.append(f"{lbl} can't be negative.")
        elif v > MAX_MONEY:
            errors.append(f"{lbl} looks too large ({v:,.2f}).")
    cu = d.get("case_units")
    if cu is None or not isinstance(cu, (int, float)) or cu < 1 or cu > 500 or float(cu) != int(cu):
        errors.append("Case size must be a whole number from 1 to 500.")
    cat = d.get("category") if d.get("category") in PROFILES else "Beer"
    lb = labels(cat)
    if not errors:
        comp = compute(d)
    for k in slots(cat):
        v = d.get(f"{k}_sp")
        if v is None:
            continue
        if not isinstance(v, (int, float)):
            errors.append(f"{lb[k]} selling price must be a number.")
        elif v <= 0:
            errors.append(f"{lb[k]} selling price must be more than 0 (leave it blank if you don't sell it).")
        elif v > MAX_MONEY:
            errors.append(f"{lb[k]} selling price looks too large ({v:,.2f}).")
        elif not errors and comp.get(f"{k}_cost") is not None and v < comp[f"{k}_cost"]:
            warnings.append(f"{lb[k]}: selling price ${v:,.2f} is below cost ${comp[k + '_cost']:,.2f} "
                            f"(margin {comp[k + '_margin']:.1f}%).")
    if not errors and (to_float(d.get("net"), 0) or 0) == 0 and any(d.get(f"{k}_sp") for k in slots(cat)):
        warnings.append("Net cost is 0, so every margin will show 100%.")
    return errors, warnings
