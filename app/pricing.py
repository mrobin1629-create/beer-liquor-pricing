"""Bulk price updates and cost-change alerts. Nothing here touches the screen."""
from . import calc

BULK_ACTIONS = {
    "pct": "Change by percent (%)",
    "amt": "Change by dollar amount ($)",
    "target": "Set to target margin (suggested price)",
    "margin": "Set to a margin of (%)",
    "set": "Set to an exact price ($)",
}


def bulk_plan(db, products, slot_keys, action, value=None, round_mode="none", only_filled=True):
    """Works out new selling prices without saving anything.
    Returns (changes, skipped): changes = [dict(product, key, label, old, new, cost, old_margin, new_margin)]."""
    inc = db.include_dep()
    changes, skipped = [], []
    v = calc.to_float(value)
    if action in ("pct", "amt", "margin", "set") and v is None:
        return [], ["Enter a number for the change."]
    if action == "margin" and calc.validate_target(v):
        return [], [calc.validate_target(v)]
    for p in products:
        cat = p.get("category")
        tg = db.targets(cat)
        comp = calc.compute(p, inc, tg)
        lb = calc.labels(cat)
        for key in slot_keys:
            if key not in calc.slots(cat):
                continue
            old = p.get(f"{key}_sp")
            cost = comp.get(f"{key}_cost")
            name = f"{p.get('item_no') or '-'} {p['description']} ({lb[key]})"
            if old is None and (only_filled or action in ("pct", "amt")):
                continue
            if action == "pct":
                new = old * (1 + v / 100)
            elif action == "amt":
                new = old + v
            elif action in ("target", "margin"):
                if cost is None:
                    skipped.append(f"{name}: no cost for this size")
                    continue
                t = tg[key] if action == "target" else v
                new = cost / (1 - t / 100)
            else:
                new = v
            if action != "set":
                new = calc.round_price(new, round_mode)
            new = round(new, 2)
            if new <= 0 or new > calc.MAX_MONEY:
                skipped.append(f"{name}: new price ${new:,.2f} is not valid")
                continue
            if old is not None and abs(new - old) < 0.005:
                continue
            changes.append(dict(product=p, key=key, label=lb[key], old=old, new=new, cost=cost,
                                old_margin=calc.margin(old, cost), new_margin=calc.margin(new, cost),
                                target=tg[key]))
    return changes, skipped


def apply_changes(db, changes, user, source):
    """Saves price changes together (one transaction) after a safety backup; history is recorded."""
    if not changes:
        return None
    backup = db.safety_backup(f"before-{source.replace(' ', '-')}")
    by_product = {}
    for c in changes:
        by_product.setdefault(c["product"]["id"], {})[f"{c['key']}_sp"] = c["new"]
    with db.transaction():
        for pid, data in by_product.items():
            db.update_product(pid, data, user, log=False, source=source)
        db.log(f"{source.capitalize()}: {len(changes)} price(s) on {len(by_product)} product(s) changed", user, "product")
    return backup


def cost_changes(db, since, source=None, only_below=False):
    """Products whose Net/Dep/Case size changed since `since`, with old vs new margin per selling price.
    Returns a list of rows (one per product and price size that has a selling price)."""
    inc, rnd = db.include_dep(), db.rounding()
    first_old = {}
    for h in db.cost_history(since, source):
        first_old.setdefault(h["product_id"], {}).setdefault(h["field"], h["old_value"])
    rows = []
    for pid, olds in first_old.items():
        p = db.get_product(pid)
        if not p:
            continue
        before = {**p, **{f: olds[f] for f in olds}}
        if before.get("case_units") is None or before.get("case_units") < 1:
            before["case_units"] = p["case_units"]
        tg = db.targets(p["category"])
        now_c = calc.compute(p, inc, tg, rnd)
        old_c = calc.compute(before, inc, tg, rnd)
        lb = calc.labels(p["category"])
        for key in calc.slots(p["category"]):
            sp = p.get(f"{key}_sp")
            if sp is None:
                continue
            new_m = now_c[f"{key}_margin"]
            below = new_m is not None and round(new_m, 1) < tg[key]
            if only_below and not below:
                continue
            rows.append(dict(product=p, key=key, label=lb[key], sp=sp,
                             old_net=before.get("net"), new_net=p.get("net"),
                             old_cost=old_c[f"{key}_cost"], new_cost=now_c[f"{key}_cost"],
                             old_margin=old_c[f"{key}_margin"], new_margin=new_m, target=tg[key],
                             suggested=now_c[f"{key}_suggested"], below=below))
    rows.sort(key=lambda r: (not r["below"], r["product"]["description"]))
    return rows
