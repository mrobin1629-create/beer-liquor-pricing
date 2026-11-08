import datetime
import os
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import calc, io_utils, labels, pricing, security, sounds
from . import license as lic
from . import updater
from . import vault
from .license_ui import LicenseDialog, startup_gate
from .chatbot import ChatBot
from .db import AUDIT_KINDS, BACKUP_KEEP
from .config import APP_NAME, APP_VERSION, CREDIT, backup_dir, data_dir, is_portable, resource_path

NAVY, NAVY_HOVER, BLUE = "#0d2f57", "#16406f", "#1e88e5"
BG, PANEL, LINE, HEAD_BLUE = "#eef3f9", "#ffffff", "#c9d3df", "#e3f0fc"
RED_BG, GREY_FG, TEXT = "#fde4e4", "#8a8f98", "#1d2733"
FONT = ("Segoe UI", 10)
FONT_B = ("Segoe UI", 10, "bold")
FONT_H = ("Segoe UI", 13, "bold")
THEME = {  # header colour + title colour per tab, like the blue/green sections in the reference
    "Beer": {"head": "#e3f0fc", "title": NAVY},
    "Liquor": {"head": "#f8ecd9", "title": "#6b3a0e"},
}

MONEY = {"price", "net", "dep", "ext"} | {f"{k}_sp" for k in calc.ALL_SLOTS}
PCT = {f"{k}_margin" for k in calc.ALL_SLOTS}
INLINE_NUMERIC = {"qty", "price", "net", "dep", "case_units"} | {f"{k}_sp" for k in calc.ALL_SLOTS}


def columns_for(category):
    lb, keys = calc.labels(category), calc.slots(category)
    cols = [
        ("pallet", "Pallet", 62, "w"), ("item_no", "Item#", 58, "w"),
        ("description", "Description", 230, "w"), ("qty", "Qty", 40, "e"),
        ("price", "Price", 66, "e"), ("net", "Net", 66, "e"), ("dep", "Dep", 52, "e"),
        ("ext", "Ext", 72, "e"), ("upc", "U.P.C.", 108, "w"), ("case_units", "Size", 44, "e"),
    ]
    sl = {k: calc.short_label(lb[k]) for k in keys}          # 'Single 24oz' -> '24oz' to keep columns narrow
    cols += [(f"{k}_sp", f"{sl[k]} S.P.", 80, "e") for k in keys]
    cols += [(f"{k}_margin", f"{sl[k]} Mgn %", 92, "e") for k in keys]
    return cols


def fmt(key, v):
    if v is None or v == "":
        return "" if key not in PCT else "—"
    if key in MONEY:
        return f"${float(v):,.2f}"
    if key in PCT:
        return f"{v:.1f}%"
    if key in ("qty", "case_units"):
        return f"{float(v):g}"
    return str(v)


def load_image(name):
    try:
        return tk.PhotoImage(file=resource_path("assets", name))
    except Exception:
        return None


# ----------------------------------------------------------------- login
def ask_new_password(parent, title, username="", intro=""):
    """Asks for a new password twice and checks it is strong enough. Returns it, or None if cancelled."""
    while True:
        p1 = simpledialog.askstring(title, (intro + "\n\n" if intro else "") +
                                    f"New password (at least {security.MIN_PASSWORD} characters):", show="•", parent=parent)
        if p1 is None:
            return None
        problem = security.password_problem(p1, username)
        if problem:
            messagebox.showwarning(title, problem, parent=parent)
            continue
        if simpledialog.askstring(title, "Type it again:", show="•", parent=parent) != p1:
            messagebox.showwarning(title, "The passwords didn't match. Please try again.", parent=parent)
            continue
        return p1


class LoginDialog(tk.Toplevel):
    def __init__(self, master, db):
        super().__init__(master)
        self.db, self.user = db, None
        self.title(f"{APP_NAME} - Sign in")
        self.configure(bg=PANEL)
        self.resizable(False, False)
        self.logo = load_image("logo.png")
        if self.logo:
            tk.Label(self, image=self.logo, bg=PANEL).grid(row=0, column=0, columnspan=2, pady=(20, 0))
        tk.Label(self, text=APP_NAME, font=("Segoe UI", 15, "bold"), bg=PANEL, fg=NAVY).grid(
            row=1, column=0, columnspan=2, padx=30, pady=(6, 2))
        tk.Label(self, text="Sign in to continue", font=FONT, bg=PANEL, fg=GREY_FG).grid(
            row=2, column=0, columnspan=2, pady=(0, 12))
        remembered = db.get_setting("remember_user", "")
        self.u, self.p = tk.StringVar(value=remembered or "admin"), tk.StringVar()
        self.remember = tk.BooleanVar(value=bool(remembered))
        for r, (lbl, var, show) in enumerate((("Username", self.u, ""), ("Password", self.p, "•")), start=3):
            tk.Label(self, text=lbl, font=FONT, bg=PANEL).grid(row=r, column=0, sticky="e", padx=(30, 8), pady=5)
            e = ttk.Entry(self, textvariable=var, show=show, width=26)
            e.grid(row=r, column=1, padx=(0, 30), pady=5)
            if lbl == "Password":
                e.focus_set()
        tk.Checkbutton(self, text="Remember me (username only)", variable=self.remember, bg=PANEL, font=FONT,
                       activebackground=PANEL).grid(row=5, column=1, sticky="w", padx=(0, 30))
        self.msg = tk.Label(self, text="First time? Use admin / admin - you'll then choose your own password.",
                            font=("Segoe UI", 9), bg=PANEL, fg=GREY_FG)
        self.msg.grid(row=6, column=0, columnspan=2)
        ttk.Button(self, text="Sign in", style="Accent.TButton", command=self.ok).grid(
            row=7, column=0, columnspan=2, pady=(10, 24), ipadx=20)
        self.bind("<Return>", lambda e: self.ok())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.update_idletasks()
        x = (self.winfo_screenwidth() - self.winfo_width()) // 2
        y = (self.winfo_screenheight() - self.winfo_height()) // 3
        self.geometry(f"+{x}+{y}")
        self.grab_set()

    def ok(self):
        name = self.u.get().strip()[:60]
        wait = security.locked_for(self.db, name)
        if wait:
            self.msg.config(text=f"Too many wrong passwords. Try again in {security.wait_text(wait)}.", fg="#c62828")
            self.p.set("")
            return
        pw = self.p.get()
        u = self.db.verify_user(name, pw)
        if not u:
            secs = security.record_failure(self.db, name)
            self.db.log(f"Failed sign-in attempt for '{name}'" + (f" - locked for {security.wait_text(secs)}" if secs else ""),
                        name or "?", "security")
            self.msg.config(text=f"Too many wrong passwords. Try again in {security.wait_text(secs)}." if secs
                            else "Wrong username or password.", fg="#c62828")
            self.p.set("")
            return
        security.record_success(self.db, name)
        if security.password_problem(pw, u["username"]):       # default admin/admin or a weak old password
            new = ask_new_password(self, "Set a new password", u["username"],
                                   "For your security, please choose a new password before continuing." +
                                   (" (The default password 'admin' can't be used.)" if pw == "admin" else ""))
            if not new:
                self.msg.config(text="You need to set a new password to sign in.", fg="#c62828")
                self.p.set("")
                return
            self.db.set_password(u["username"], new)
            self.db.log("Changed own password (required at sign-in)", u["username"], "user")
        if u["role"] == "admin" and not self.db.has_backup_password():
            bp = ask_new_password(self, "Set a backup password", "",
                                  "Your data is now encrypted and locked to this Windows user.\n\n"
                                  "Choose a BACKUP PASSWORD. You'll need it to open your backups (or this data folder) "
                                  "on another computer. Write it down and keep it safe - nobody can recover it.")
            if bp:
                self.db.set_backup_password(bp, u["username"])
                messagebox.showinfo("Backup password set", "Backup password saved. Keep it somewhere safe.", parent=self)
            else:
                messagebox.showwarning("No backup password", "Without a backup password your backups only open on this "
                                       "computer. You'll be asked again next time (or set it on the Backup page).",
                                       parent=self)
        self.db.set_setting("remember_user", u["username"] if self.remember.get() else "")
        self.db.log(f"Signed in ({u['role']})", u["username"], "login")
        self.user = u
        self.destroy()


# ----------------------------------------------------------- product form
class ProductDialog(tk.Toplevel):
    FIELDS = [("category", "Tab (category)"), ("pallet", "Pallet #"), ("item_no", "Item #"),
              ("description", "Description"), ("qty", "Qty"), ("price", "Price"), ("net", "Net (case cost)"),
              ("dep", "Deposit"), ("upc", "U.P.C."), ("case_units", "Case size (units)"), ("notes", "Notes")]

    def __init__(self, app, product=None, category="Beer", preset=None):
        super().__init__(app)
        self.app, self.product, self.result = app, product, None
        self.title("Edit product" if product else "Add product")
        self.configure(bg=PANEL)
        self.transient(app)
        self.vars = {}
        p = product or {"category": category, "qty": 1, "dep": 0,
                        "case_units": calc.profile(category)["default_units"], **(preset or {})}
        left = tk.Frame(self, bg=PANEL)
        left.grid(row=0, column=0, sticky="n", padx=(18, 10), pady=16)
        tk.Label(left, text="Supplier ticket", font=FONT_H, bg=PANEL, fg=NAVY).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        for r, (k, lbl) in enumerate(self.FIELDS, start=1):
            v = tk.StringVar(value="" if p.get(k) is None else (f"{p[k]:g}" if isinstance(p.get(k), float) else str(p[k])))
            self.vars[k] = v
            self.unit_lbl = None
            tk.Label(left, text=lbl, font=FONT, bg=PANEL).grid(row=r, column=0, sticky="w", pady=3)
            if k == "category":
                w = ttk.Combobox(left, textvariable=v, values=list(calc.CATEGORIES), state="readonly", width=33)
            else:
                w = ttk.Entry(left, textvariable=v, width=36)
            w.grid(row=r, column=1, sticky="w", padx=(8, 0), pady=3)
            if k == "description":
                w.focus_set()
        self.vars["description"].trace_add("write", self._guess_units)
        self.vars["category"].trace_add("write", self._guess_units)

        self.right = right = tk.Frame(self, highlightbackground=LINE, highlightthickness=1)
        right.grid(row=0, column=1, sticky="n", padx=(10, 18), pady=16)
        self.right_title = tk.Label(right, text="Selling prices and margins", font=FONT_H)
        self.right_title.grid(row=0, column=0, columnspan=5, sticky="w", padx=12, pady=(10, 8))
        self.right_widgets = [right, self.right_title]
        rnd = app.db.rounding()
        sug_h = "Suggested" + ("" if rnd == "none" else {"x9": " (..9)", "49_99": " (.49/.99)", "99": " (.99)"}[rnd])
        for c, h in enumerate(("", "Selling price", "Cost", "Margin", sug_h)):
            lab = tk.Label(right, text=h, font=FONT_B)
            lab.grid(row=1, column=c, padx=8, sticky="w")
            self.right_widgets.append(lab)
        self.out = {}
        self.slot_widgets = {}
        for r, k in enumerate(calc.ALL_SLOTS, start=2):
            v = tk.StringVar(value="" if p.get(k + "_sp") is None else f"{p[k + '_sp']:.2f}")
            self.vars[k + "_sp"] = v
            name = tk.Label(right, font=FONT_B)
            name.grid(row=r, column=0, padx=(12, 8), pady=6, sticky="w")
            ent = ttk.Entry(right, textvariable=v, width=10)
            ent.grid(row=r, column=1, padx=8)
            cost = tk.Label(right, font=FONT, width=9, anchor="e")
            mar = tk.Label(right, font=FONT_B, width=8, anchor="e")
            sug = ttk.Button(right, text="—", width=13, command=lambda k=k: self._use_suggested(k))
            cost.grid(row=r, column=2, padx=8)
            mar.grid(row=r, column=3, padx=8)
            sug.grid(row=r, column=4, padx=(8, 12))
            self.out[k] = (name, cost, mar, sug)
            self.slot_widgets[k] = (name, ent, cost, mar, sug)
            self.right_widgets += [name, cost, mar]
        hint = tk.Label(right, text="Click a suggested price to use it.\nRed = below your target margin.",
                        font=("Segoe UI", 9), fg=GREY_FG, justify="left")
        hint.grid(row=2 + len(calc.ALL_SLOTS), column=0, columnspan=5, sticky="w", padx=12, pady=(6, 12))
        self.right_widgets.append(hint)
        for v in self.vars.values():
            v.trace_add("write", lambda *a: self._recalc())

        bar = tk.Frame(self, bg=PANEL)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=18, pady=(0, 16))
        if product:
            ttk.Button(bar, text="📜 Price history", command=lambda: PriceHistoryWindow(app, product)).pack(side="left")
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(bar, text="Save product", style="Accent.TButton", command=self.save).pack(side="right", padx=4)
        self.bind("<Return>", lambda e: self.save())
        self.bind("<Escape>", lambda e: self.destroy())
        self._recalc()
        self.grab_set()

    def _guess_units(self, *a):
        if not self.product:
            cat = self.vars["category"].get()
            prof = calc.profile(cat)
            self.vars["case_units"].set(str(calc.guess_case_units(self.vars["description"].get(), prof["default_units"], cat)))

    def _data(self):
        d = {k: v.get().strip() for k, v in self.vars.items()}
        for k in ("qty", "price", "net", "dep"):
            d[k] = calc.to_float(d[k], 0.0)
        for k in calc.ALL_SLOTS:
            d[k + "_sp"] = calc.to_float(d[k + "_sp"])
        cu = calc.to_float(d["case_units"], 24)
        d["case_units"] = int(cu) if cu else calc.profile(d["category"])["default_units"]
        return d

    def _recalc(self):
        d = self._data()
        cat = d["category"] if d["category"] in calc.CATEGORIES else "Beer"
        tg = self.app.db.targets(cat)
        for w in self.right_widgets:
            w.config(bg=HEAD_BLUE)
        self.right_title.config(fg=NAVY, text="Selling prices and margins")
        lb = calc.labels(cat)
        used = calc.slots(cat)
        for k, ws in self.slot_widgets.items():          # Liquor has no single-can rows
            for w in ws:
                (w.grid if k in used else w.grid_remove)()
        self.comp = calc.compute(d, self.app.db.include_dep(), tg, self.app.db.rounding())
        for k, (name, cost, mar, sug) in self.out.items():
            if k not in used:
                continue
            name.config(text=lb[k])
            m = self.comp[k + "_margin"]
            cost.config(text=fmt("net", self.comp[k + "_cost"]) if self.comp[k + "_cost"] is not None else "n/a")
            mar.config(text=fmt("case_margin", m), fg="#c62828" if (m is not None and round(m, 1) < tg[k]) else "#2e7d32")
            s = self.comp[k + "_suggested"]
            sug.config(text=f"{fmt('net', s)} @ {tg[k]:g}%" if s else "n/a")

    def _use_suggested(self, k):
        s = self.comp.get(k + "_suggested")
        if s:
            self.vars[k + "_sp"].set(f"{s:.2f}")

    def save(self):
        d = self._data()
        bad = []
        for k, lbl in (("qty", "Qty"), ("price", "Price"), ("net", "Net"), ("dep", "Deposit"), ("case_units", "Case size")):
            if self.vars[k].get().strip() and calc.to_float(self.vars[k].get()) is None:
                bad.append(f"{lbl} must be a number.")
        for k in calc.slots(d["category"]):
            if self.vars[k + "_sp"].get().strip() and d[k + "_sp"] is None:
                bad.append(f"{calc.labels(d['category'])[k]} selling price must be a number, like 10.99.")
        if calc.to_float(self.vars["case_units"].get()) is not None:
            d["case_units"] = calc.to_float(self.vars["case_units"].get())
        d["_bad"] = bad
        errors, warnings = calc.validate_product(d)
        d.pop("_bad")
        if errors:
            messagebox.showwarning("Please fix", "\n".join("• " + e for e in errors), parent=self)
            return
        if warnings and not messagebox.askyesno("Check prices", "\n".join("• " + w for w in warnings)
                                                + "\n\nSave anyway?", parent=self):
            return
        d["case_units"] = int(d["case_units"])
        for k in calc.ALL_SLOTS:                         # don't keep hidden prices if moved to Liquor
            if k not in calc.slots(d["category"]):
                d[k + "_sp"] = None
        self.result = d
        self.destroy()


# --------------------------------------------------------- table section
class Section:
    """One product table (Beer or Liquor) with its own target margins."""

    def __init__(self, app, parent, category):
        self.app, self.cat = app, category
        prof, th = calc.profile(category), THEME[category]
        self.cols = columns_for(category)
        self.sort_key, self.sort_rev = "description", False
        self.row_data = {}
        self.frame = tk.Frame(parent, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        head = tk.Frame(self.frame, bg=th["head"])
        head.pack(fill="x")
        title = category if app.compact else prof["title"]      # tab button above already shows the sizes
        tk.Label(head, text=f"{prof['icon']}  {title}", font=FONT_H, bg=th["head"], fg=th["title"]).pack(
            side="left", padx=12, pady=3 if app.compact else 7)
        ttk.Button(head, text="?", width=2, command=lambda: app.show("help")).pack(side="right", padx=(4, 10))
        self.target_vars = {}
        lb = calc.labels(category)
        for k in reversed(calc.slots(category)):
            v = tk.StringVar(value=f"{app.db.targets(category)[k]:g}")
            cb = ttk.Combobox(head, textvariable=v, values=[str(x) for x in range(5, 65, 5)], width=3)
            cb.pack(side="right", padx=(2, 10))
            for ev in ("<<ComboboxSelected>>", "<Return>", "<FocusOut>"):
                cb.bind(ev, lambda e, k=k: self._set_target(k))
            tk.Label(head, text=f"{calc.short_label(lb[k])} %", font=FONT_B, bg=th["head"]).pack(side="right")
            self.target_vars[k] = v
        tk.Label(head, text="Target margin:", font=FONT, bg=th["head"]).pack(side="right", padx=(0, 6))

        body = tk.Frame(self.frame, bg=PANEL)
        body.pack(fill="both", expand=True, padx=8, pady=4 if app.compact else 8)
        self.tree = ttk.Treeview(body, columns=[c[0] for c in self.cols], show="headings", selectmode="extended", height=8)
        for key, h, w, anchor in self.cols:
            self.tree.heading(key, text=h, command=lambda k=key: self._sort(k))
            self.tree.column(key, width=w, minwidth=40, anchor=anchor, stretch=(key == "description"))
        ys = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(body, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        tk.Label(self.frame, text="Double-click a price or quantity to type a new value.  Red rows are below target margin.  "
                 "Grey rows are out of stock.", font=("Segoe UI", 9), bg=PANEL, fg=GREY_FG).pack(anchor="w", padx=10, pady=(0, 6))
        self.empty = tk.Label(body, text=f"No {category.lower()} products yet. Click '+ Add Product' or Import.",
                              font=FONT, bg=PANEL, fg=GREY_FG)
        self.tree.tag_configure("low", background=RED_BG)
        self.tree.tag_configure("oos", foreground=GREY_FG)
        self.tree.tag_configure("odd", background="#f7f9fc")
        self.tree.bind("<Double-1>", self._on_double)
        self.tree.bind("<Delete>", lambda e: app.delete_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.tree.selection() and app.set_active(category, from_table=True))
        self.tree.bind("<Button-1>", lambda e: app.set_active(category, from_table=True), add="+")

    def set_highlight(self, on):
        self.frame.config(highlightbackground=BLUE if on else LINE)

    def _set_target(self, k):
        v = calc.to_float(self.target_vars[k].get())
        cur = self.app.db.targets(self.cat)[k]
        err = calc.validate_target(v)
        if err:
            self.target_vars[k].set(f"{cur:g}")
            messagebox.showwarning("Target margin", err)
            return
        if v != cur:
            self.app.db.set_target(self.cat, k, v, self.app.user["username"])
            self.app.refresh()

    def reload_targets(self):
        for k, v in self.target_vars.items():
            v.set(f"{self.app.db.targets(self.cat)[k]:g}")

    def _sort(self, key):
        self.sort_rev = not self.sort_rev if self.sort_key == key else False
        self.sort_key = key
        self.refresh(self.app.search_var.get())

    def refresh(self, search=""):
        tg, inc = self.app.db.targets(self.cat), self.app.db.include_dep()
        rows = []
        for p in self.app.db.list_products(search, self.cat):
            d = dict(p)
            d.update(calc.compute(p, inc, tg))
            rows.append(d)

        def sk(d):
            v = d.get(self.sort_key)
            if v is None or v == "":
                return (1, 0)
            return (0, v.lower() if isinstance(v, str) else v)
        rows.sort(key=sk, reverse=self.sort_rev)
        for key, h, *_ in self.cols:
            arrow = (" ▼" if self.sort_rev else " ▲") if key == self.sort_key else ""
            self.tree.heading(key, text=h + arrow)
        sel = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        self.row_data = {}
        for i, d in enumerate(rows):
            tags = ["low"] if d["low_margin"] else (["odd"] if i % 2 else [])
            if d["out_of_stock"]:
                tags.append("oos")
            iid = str(d["id"])
            self.tree.insert("", "end", iid=iid, values=[fmt(k, d.get(k)) for k, *_ in self.cols], tags=tags)
            self.row_data[iid] = d
        keep = [i for i in sel if self.tree.exists(i)]
        if keep:
            self.tree.selection_set(keep)
        if rows:
            self.empty.place_forget()
        else:
            self.empty.place(relx=.5, rely=.5, anchor="center")

    def selected_ids(self):
        return [int(i) for i in self.tree.selection()]

    def _on_double(self, event):
        if self.tree.identify("region", event.x, event.y) != "cell":
            return
        iid = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        key = self.cols[int(col[1:]) - 1][0]
        if key in INLINE_NUMERIC:
            self._inline_edit(iid, col, key)
        else:
            self.tree.selection_set(iid)
            self.app.edit_selected()

    def _inline_edit(self, iid, col, key):
        bbox = self.tree.bbox(iid, col)
        if not bbox:
            return
        x, y, w, h = bbox
        raw = self.row_data[iid].get(key)
        e = ttk.Entry(self.tree, justify="right")
        e.insert(0, "" if raw is None else (f"{raw:.2f}" if key in MONEY else f"{raw:g}"))
        e.select_range(0, "end")
        e.place(x=x, y=y, width=max(w, 80), height=h)
        e.focus_set()
        done = {"v": False}

        def save(_=None):
            if done["v"]:
                return
            done["v"] = True
            txt = e.get().strip()
            e.destroy()
            v = calc.to_float(txt)
            if txt and v is None:
                messagebox.showwarning("Not a number", f"'{txt}' isn't a number.")
                return
            if key in ("qty", "price", "net", "dep") and v is None:
                v = 0.0
            if v == raw:
                return
            p = self.app.db.get_product(int(iid))
            trial = {**p, key: v}
            errors, warnings = calc.validate_product(trial)
            if errors:
                messagebox.showwarning("Not saved", "\n".join("• " + x for x in errors))
                return
            if warnings and not messagebox.askyesno("Check price", "\n".join("• " + x for x in warnings) + "\n\nSave anyway?"):
                return
            if key == "case_units":
                v = int(v)
            self.app.db.update_product(int(iid), {key: v}, self.app.user["username"], log=False, source="table edit")
            label = dict((c[0], c[1]) for c in self.cols)[key]
            self.app.db.log(f"{label} of {p['description']} ({self.cat}): {fmt(key, raw) or 'blank'} -> {fmt(key, v) or 'blank'}",
                            self.app.user["username"], "product")
            self.app.refresh()

        def cancel(_=None):
            done["v"] = True
            e.destroy()
        e.bind("<Return>", save)
        e.bind("<KP_Enter>", save)
        e.bind("<FocusOut>", save)
        e.bind("<Escape>", cancel)



# ------------------------------------------------------------ pricing rules
class PricingRulesDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Pricing rules")
        self.configure(bg=PANEL)
        self.transient(app)
        self.resizable(False, False)
        tk.Label(self, text="⚙  Pricing rules", font=FONT_H, bg=PANEL, fg=NAVY).pack(anchor="w", padx=18, pady=(14, 8))
        tk.Label(self, text="Rounding for suggested prices and bulk updates", font=FONT_B, bg=PANEL).pack(anchor="w", padx=18)
        self.rnd = tk.StringVar(value=app.db.rounding())
        for k, txt in calc.ROUNDING.items():
            tk.Radiobutton(self, text=txt, value=k, variable=self.rnd, bg=PANEL, font=FONT, activebackground=PANEL,
                           anchor="w").pack(fill="x", padx=28)
        tk.Label(self, text="Prices always round UP, so they never fall below your target margin.",
                 font=("Segoe UI", 9), bg=PANEL, fg=GREY_FG).pack(anchor="w", padx=28, pady=(2, 10))
        self.dep = tk.BooleanVar(value=app.db.include_dep())
        tk.Checkbutton(self, text="Include deposit (Dep) in cost when calculating margins", variable=self.dep, bg=PANEL,
                       font=FONT, activebackground=PANEL).pack(anchor="w", padx=18)
        tk.Label(self, text="Target margins are set above each table.", font=("Segoe UI", 9), bg=PANEL,
                 fg=GREY_FG).pack(anchor="w", padx=18, pady=(10, 0))
        bar = tk.Frame(self, bg=PANEL)
        bar.pack(fill="x", padx=18, pady=14)
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(bar, text="Save", style="Accent.TButton", command=self.save).pack(side="right", padx=4)
        self.grab_set()

    def save(self):
        db, user = self.app.db, self.app.user["username"]
        if self.rnd.get() != db.rounding():
            db.set_setting("rounding", self.rnd.get())
            db.log(f"Price rounding set to: {calc.ROUNDING[self.rnd.get()]}", user, "settings")
        if self.dep.get() != db.include_dep():
            self.app.dep_var.set(self.dep.get())
            self.app._toggle_dep()
        self.app.refresh()
        self.destroy()


# -------------------------------------------------------------- bulk update
class BulkUpdateDialog(tk.Toplevel):
    def __init__(self, app, products, category):
        super().__init__(app)
        self.app, self.products, self.cat = app, products, category
        self.title(f"Bulk price update - {category}")
        self.configure(bg=PANEL)
        self.geometry("1080x640")
        self.transient(app)
        self.changes = []
        top = tk.Frame(self, bg=PANEL)
        top.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(top, text=f"💲  Bulk update {len(products)} {category.lower()} product(s)", font=FONT_H, bg=PANEL,
                 fg=NAVY).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 8))
        tk.Label(top, text="Prices to change:", font=FONT_B, bg=PANEL).grid(row=1, column=0, sticky="w")
        self.slot_vars = {}
        sf = tk.Frame(top, bg=PANEL)
        sf.grid(row=1, column=1, columnspan=5, sticky="w")
        for k, lbl in calc.labels(category).items():
            v = tk.BooleanVar(value=True)
            tk.Checkbutton(sf, text=lbl, variable=v, bg=PANEL, font=FONT, activebackground=PANEL,
                           command=self.preview).pack(side="left", padx=(0, 10))
            self.slot_vars[k] = v
        tk.Label(top, text="Change:", font=FONT_B, bg=PANEL).grid(row=2, column=0, sticky="w", pady=6)
        self.action = tk.StringVar(value=pricing.BULK_ACTIONS["target"])
        cb = ttk.Combobox(top, textvariable=self.action, values=list(pricing.BULK_ACTIONS.values()), state="readonly", width=36)
        cb.grid(row=2, column=1, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda e: self.preview())
        self.value = tk.StringVar()
        self.value_lbl = tk.Label(top, text="Amount:", font=FONT, bg=PANEL)
        self.value_lbl.grid(row=2, column=2, sticky="e", padx=(12, 4))
        self.value_entry = ttk.Entry(top, textvariable=self.value, width=10)
        self.value_entry.grid(row=2, column=3, sticky="w")
        self.value.trace_add("write", lambda *a: self.preview())
        tk.Label(top, text="Rounding:", font=FONT_B, bg=PANEL).grid(row=3, column=0, sticky="w")
        self.rnd = tk.StringVar(value=calc.ROUNDING[app.db.rounding()])
        rb = ttk.Combobox(top, textvariable=self.rnd, values=list(calc.ROUNDING.values()), state="readonly", width=46)
        rb.grid(row=3, column=1, columnspan=3, sticky="w")
        rb.bind("<<ComboboxSelected>>", lambda e: self.preview())
        self.only_filled = tk.BooleanVar(value=True)
        tk.Checkbutton(top, text="Only change prices that already have a value", variable=self.only_filled, bg=PANEL,
                       font=FONT, activebackground=PANEL, command=self.preview).grid(row=4, column=1, columnspan=3, sticky="w", pady=4)

        f = tk.Frame(self, bg=PANEL)
        f.pack(fill="both", expand=True, padx=16)
        cols = (("item", "Item#", 70), ("desc", "Description", 250), ("size", "Price", 95), ("old", "Old price", 90),
                ("new", "New price", 95), ("cost", "Cost", 80), ("om", "Old margin", 100), ("nm", "New margin", 100), ("tg", "Target", 65))
        self.tree = ttk.Treeview(f, columns=[c[0] for c in cols], show="headings")
        for k, h, w in cols:
            self.tree.heading(k, text=h)
            self.tree.column(k, width=w, anchor="w" if k in ("item", "desc", "size") else "e", stretch=(k == "desc"))
        ys = ttk.Scrollbar(f, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ys.pack(side="left", fill="y")
        self.tree.tag_configure("low", foreground="#c62828")
        self.info = tk.Label(self, text="", font=("Segoe UI", 9), bg=PANEL, fg=GREY_FG, justify="left", anchor="w")
        self.info.pack(fill="x", padx=16, pady=4)
        bar = tk.Frame(self, bg=PANEL)
        bar.pack(fill="x", padx=16, pady=(0, 14))
        tk.Label(bar, text="Nothing is saved until you click Apply. A backup is made first.", font=("Segoe UI", 9),
                 bg=PANEL, fg=GREY_FG).pack(side="left")
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        self.apply_btn = ttk.Button(bar, text="Apply", style="Accent.TButton", command=self.apply)
        self.apply_btn.pack(side="right", padx=4)
        self.preview()
        self.grab_set()

    def _action_key(self):
        return {v: k for k, v in pricing.BULK_ACTIONS.items()}[self.action.get()]

    def preview(self):
        act = self._action_key()
        needs = act in ("pct", "amt", "margin", "set")
        self.value_lbl.config(text={"pct": "Percent:", "amt": "Dollars:", "margin": "Margin %:", "set": "Price $:"}.get(act, ""))
        self.value_entry.config(state="normal" if needs else "disabled")
        rnd = {v: k for k, v in calc.ROUNDING.items()}[self.rnd.get()]
        keys = [k for k, v in self.slot_vars.items() if v.get()]
        self.changes, skipped = ([], ["Enter an amount."]) if needs and not self.value.get().strip() else \
            pricing.bulk_plan(self.app.db, self.products, keys, act, self.value.get(), rnd, self.only_filled.get())
        self.tree.delete(*self.tree.get_children())
        for c in self.changes:
            low = c["new_margin"] is not None and round(c["new_margin"], 1) < c["target"]
            self.tree.insert("", "end", values=(c["product"].get("item_no") or "", c["product"]["description"], c["label"],
                                                fmt("net", c["old"]) or "blank", fmt("net", c["new"]),
                                                fmt("net", c["cost"]) if c["cost"] is not None else "",
                                                fmt("case_margin", c["old_margin"]), fmt("case_margin", c["new_margin"]),
                                                f"{c['target']:g}%"), tags=("low",) if low else ())
        msg = f"{len(self.changes)} price(s) will change."
        if skipped:
            msg += f"  {len(skipped)} skipped: " + "; ".join(skipped[:3]) + ("…" if len(skipped) > 3 else "")
        if any(c["new_margin"] is not None and round(c["new_margin"], 1) < c["target"] for c in self.changes):
            msg += "  Red = still below target."
        self.info.config(text=msg)
        self.apply_btn.config(text=f"Apply {len(self.changes)} change(s)", state="normal" if self.changes else "disabled")

    def apply(self):
        if not self.changes:
            return
        try:
            pricing.apply_changes(self.app.db, self.changes, self.app.user["username"], "bulk update")
        except Exception as ex:
            messagebox.showerror("Bulk update failed", f"{ex}\n\nNothing was changed.", parent=self)
            return
        changed = list({c["product"]["id"]: c["product"] for c in self.changes}.values())
        self.destroy()
        self.app.refresh()
        if messagebox.askyesno("Prices updated", f"{len(self.changes)} price(s) updated.\n\nPrint shelf labels for these "
                                                 f"{len(changed)} product(s) now?"):
            self.app.open_labels([self.app.db.get_product(p["id"]) for p in changed])


# --------------------------------------------------------------- labels
class LabelDialog(tk.Toplevel):
    def __init__(self, app, selected, category):
        super().__init__(app)
        self.app, self.selected, self.cat = app, [p for p in selected if p], category
        self.title("Shelf labels")
        self.configure(bg=PANEL)
        self.transient(app)
        self.resizable(False, False)
        tk.Label(self, text="🏷  Shelf labels / price tags", font=FONT_H, bg=PANEL, fg=NAVY).pack(anchor="w", padx=18, pady=(14, 8))
        tk.Label(self, text="Which products", font=FONT_B, bg=PANEL).pack(anchor="w", padx=18)
        self.which = tk.StringVar(value="selected" if self.selected else "changed")
        row = tk.Frame(self, bg=PANEL)
        row.pack(fill="x", padx=28)
        tk.Radiobutton(row, text=f"Selected / scanned products ({len(self.selected)})", value="selected", variable=self.which,
                       bg=PANEL, font=FONT, activebackground=PANEL, command=self.update_count,
                       state="normal" if self.selected else "disabled").pack(anchor="w")
        r2 = tk.Frame(row, bg=PANEL)
        r2.pack(anchor="w")
        tk.Radiobutton(r2, text="Selling price changed since", value="changed", variable=self.which, bg=PANEL, font=FONT,
                       activebackground=PANEL, command=self.update_count).pack(side="left")
        self.since = tk.StringVar(value=str(datetime.date.today()))
        e = ttk.Entry(r2, textvariable=self.since, width=12)
        e.pack(side="left", padx=4)
        self.since.trace_add("write", lambda *a: self.update_count())
        tk.Label(r2, text="(YYYY-MM-DD)", font=("Segoe UI", 9), bg=PANEL, fg=GREY_FG).pack(side="left")
        tk.Radiobutton(row, text=f"All products in the {category} tab", value="all", variable=self.which, bg=PANEL,
                       font=FONT, activebackground=PANEL, command=self.update_count).pack(anchor="w")
        tk.Label(self, text="Label sheet", font=FONT_B, bg=PANEL).pack(anchor="w", padx=18, pady=(10, 0))
        self.size = tk.StringVar(value=app.db.get_setting("label_size", "5163"))
        for k, sh in labels.SHEETS.items():
            tk.Radiobutton(self, text=sh["title"], value=k, variable=self.size, bg=PANEL, font=FONT, activebackground=PANEL,
                           command=self.update_count).pack(anchor="w", padx=28)
        opt = tk.Frame(self, bg=PANEL)
        opt.pack(fill="x", padx=18, pady=(10, 0))
        tk.Label(opt, text="Start at label #", font=FONT, bg=PANEL).pack(side="left")
        self.start = tk.StringVar(value="1")
        self.start_box = ttk.Spinbox(opt, from_=1, to=30, textvariable=self.start, width=4, command=self.update_count)
        self.start_box.pack(side="left", padx=4)
        tk.Label(opt, text="(skip labels already used on a sheet)", font=("Segoe UI", 9), bg=PANEL, fg=GREY_FG).pack(side="left")
        self.barcode = tk.BooleanVar(value=True)
        self.outlines = tk.BooleanVar(value=False)
        tk.Checkbutton(self, text="Barcode on large labels", variable=self.barcode, bg=PANEL, font=FONT,
                       activebackground=PANEL).pack(anchor="w", padx=18)
        tk.Checkbutton(self, text="Draw label outlines (for a test print on plain paper)", variable=self.outlines, bg=PANEL,
                       font=FONT, activebackground=PANEL).pack(anchor="w", padx=18)
        self.count = tk.Label(self, text="", font=FONT_B, bg=PANEL, fg=NAVY)
        self.count.pack(anchor="w", padx=18, pady=(10, 0))
        bar = tk.Frame(self, bg=PANEL)
        bar.pack(fill="x", padx=18, pady=14)
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(bar, text="⎙ Print", command=lambda: self.make(True)).pack(side="right", padx=4)
        ttk.Button(bar, text="Save PDF…", style="Accent.TButton", command=lambda: self.make(False)).pack(side="right", padx=4)
        self.update_count()
        self.grab_set()

    def products(self):
        w = self.which.get()
        if w == "selected":
            ps = self.selected
        elif w == "all":
            ps = self.app.db.list_products(category=self.cat)
        else:
            try:
                datetime.datetime.strptime(self.since.get().strip(), "%Y-%m-%d")
            except ValueError:
                return None
            ps = sorted(self.app.db.products_with_changes(self.since.get().strip() + " 00:00"), key=lambda p: p["description"])
        return [p for p in ps if any(p.get(f"{k}_sp") for k in calc.slots(p["category"]))]

    def update_count(self):
        ps = self.products()
        sh = labels.SHEETS[self.size.get()]
        per = sh["cols"] * sh["rows"]
        self.start_box.config(to=per)
        if ps is None:
            self.count.config(text="Enter the date as YYYY-MM-DD.", fg="#c62828")
            return
        start = max(1, min(per, int(calc.to_float(self.start.get(), 1) or 1)))
        sheets = -(-(len(ps) + start - 1) // per) if ps else 0
        self.count.config(text=f"{len(ps)} label(s) on {sheets} sheet(s)" if ps else
                          "No products with selling prices match.", fg=NAVY if ps else "#c62828")

    def make(self, print_it):
        ps = self.products()
        if not ps:
            messagebox.showinfo("Shelf labels", "No products with selling prices to print.", parent=self)
            return
        size = self.size.get()
        self.app.db.set_setting("label_size", size)
        if print_it:
            path = os.path.join(tempfile.gettempdir(), "bevmargin-labels.pdf")
        else:
            path = filedialog.asksaveasfilename(parent=self, defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
                                                initialfile=f"shelf-labels-{datetime.date.today()}")
            if not path:
                return
        try:
            labels.make_labels(path, ps, size, int(calc.to_float(self.start.get(), 1) or 1), self.outlines.get(),
                               self.barcode.get(), self.app.db.get_setting("store_name", ""))
            io_utils.open_file(path, "print" if print_it else None)
        except Exception as ex:
            messagebox.showerror("Labels failed", str(ex), parent=self)
            return
        self.app.db.log(f"{'Printed' if print_it else 'Saved'} {len(ps)} shelf label(s) (Avery {size})",
                        self.app.user["username"], "export")
        self.destroy()


# ------------------------------------------------------------- cost alerts
class CostChangeWindow(tk.Toplevel):
    def __init__(self, app, rows, heading):
        super().__init__(app)
        self.app, self.rows = app, rows
        self.title("Cost changes")
        self.configure(bg=PANEL)
        self.geometry("1240x560")
        self.transient(app)
        below = sum(r["below"] for r in rows)
        prods = len({r["product"]["id"] for r in rows})
        tk.Label(self, text=f"⚠  {heading}", font=FONT_H, bg=PANEL, fg="#c62828" if below else NAVY).pack(anchor="w", padx=16, pady=(14, 2))
        tk.Label(self, text=f"{prods} product(s) had a cost change. {below} selling price(s) are now below target margin "
                            "(red, selected). Suggested prices use your rounding rule.", font=FONT, bg=PANEL).pack(anchor="w", padx=16)
        f = tk.Frame(self, bg=PANEL)
        f.pack(fill="both", expand=True, padx=16, pady=8)
        cols = (("item", "Item#", 65), ("desc", "Description", 250), ("tab", "Tab", 55), ("size", "Price", 85),
                ("net", "Net old → new", 140), ("sp", "Selling", 75), ("om", "Old margin", 100), ("nm", "New margin", 100),
                ("tg", "Target", 65), ("sug", "Suggested", 95))
        self.tree = ttk.Treeview(f, columns=[c[0] for c in cols], show="headings")
        for k, h, w in cols:
            self.tree.heading(k, text=h)
            self.tree.column(k, width=w, anchor="w" if k in ("item", "desc", "tab", "size") else "e", stretch=(k == "desc"))
        ys = ttk.Scrollbar(f, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ys.pack(side="left", fill="y")
        self.tree.tag_configure("low", foreground="#c62828")
        for i, r in enumerate(rows):
            self.tree.insert("", "end", iid=str(i), values=(
                r["product"].get("item_no") or "", r["product"]["description"], r["product"]["category"], r["label"],
                f"{fmt('net', r['old_net'])} → {fmt('net', r['new_net'])}", fmt("net", r["sp"]),
                fmt("case_margin", r["old_margin"]), fmt("case_margin", r["new_margin"]), f"{r['target']:g}%",
                fmt("net", r["suggested"]) if (r["suggested"] and r["below"]) else "OK"), tags=("low",) if r["below"] else ())
        self.tree.selection_set([str(i) for i, r in enumerate(rows) if r["below"]])
        bar = tk.Frame(self, bg=PANEL)
        bar.pack(fill="x", padx=16, pady=(0, 14))
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(bar, text="Export CSV", command=self.export).pack(side="right", padx=4)
        ttk.Button(bar, text="🏷 Labels for selected", command=self.labels).pack(side="right", padx=4)
        ttk.Button(bar, text="💲 Apply suggested price to selected rows", style="Accent.TButton",
                   command=self.apply).pack(side="right", padx=4)

    def _sel(self):
        return [self.rows[int(i)] for i in self.tree.selection()]

    def apply(self):
        sel = [r for r in self._sel() if r["suggested"] and r["below"]]      # never lowers a price that's still OK
        if not sel:
            messagebox.showinfo("Cost changes", "Select one or more red (below target) rows first.", parent=self)
            return
        changes = [dict(product=r["product"], key=r["key"], label=r["label"], old=r["sp"], new=r["suggested"])
                   for r in sel if abs(r["suggested"] - r["sp"]) >= 0.005]
        if not changes or not messagebox.askyesno("Apply prices", f"Change {len(changes)} selling price(s) to the suggested "
                                                                  "price?\nA backup is made first.", parent=self):
            return
        try:
            pricing.apply_changes(self.app.db, changes, self.app.user["username"], "cost change update")
        except Exception as ex:
            messagebox.showerror("Failed", f"{ex}\n\nNothing was changed.", parent=self)
            return
        prods = list({c["product"]["id"] for c in changes})
        self.destroy()
        self.app.refresh()
        if messagebox.askyesno("Prices updated", f"{len(changes)} price(s) updated.\n\nPrint shelf labels for these "
                                                 f"{len(prods)} product(s) now?"):
            self.app.open_labels([self.app.db.get_product(i) for i in prods])

    def labels(self):
        prods = {r["product"]["id"] for r in self._sel()}
        if not prods:
            messagebox.showinfo("Cost changes", "Select one or more rows first.", parent=self)
            return
        self.destroy()
        self.app.open_labels([self.app.db.get_product(i) for i in prods])

    def export(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                            initialfile=f"cost-changes-{datetime.date.today()}")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = security.csv_writer(f)
            w.writerow(["Item#", "Description", "Tab", "Price", "Old net", "New net", "Selling", "Old margin %",
                        "New margin %", "Target %", "Suggested", "Below target"])
            for r in self.rows:
                w.writerow([r["product"].get("item_no"), r["product"]["description"], r["product"]["category"], r["label"],
                            r["old_net"], r["new_net"], r["sp"], None if r["old_margin"] is None else round(r["old_margin"], 1),
                            None if r["new_margin"] is None else round(r["new_margin"], 1), r["target"], r["suggested"],
                            "yes" if r["below"] else ""])


# ----------------------------------------------------------- price history
FIELD_NAMES = {"price": "Price", "net": "Net", "dep": "Deposit", "case_units": "Case size"}


def field_label(field, category):
    if field.endswith("_sp"):
        return f"{calc.labels(category).get(field[:-3], field)} S.P."
    return FIELD_NAMES.get(field, field)


def history_value(field, v):
    if v is None:
        return "blank"
    return f"{v:g}" if field == "case_units" else f"${v:,.2f}"


def history_change(field, old, new):
    if old is None or new is None or field == "case_units":
        return ""
    d = new - old
    pct = f" ({d / old * 100:+.1f}%)" if old else ""
    return f"{'+' if d >= 0 else '-'}${abs(d):,.2f}{pct}"


def fill_history_tree(tree, rows):
    tree.delete(*tree.get_children())
    for r in rows:
        tree.insert("", "end", values=(r["ts"], r["item_no"] or "", r["description"] or "", r["category"] or "",
                                       field_label(r["field"], r["category"]), history_value(r["field"], r["old_value"]),
                                       history_value(r["field"], r["new_value"]),
                                       history_change(r["field"], r["old_value"], r["new_value"]),
                                       r["username"] or "", r["source"] or ""))


def make_history_tree(parent, height=12):
    cols = (("ts", "When", 140), ("item", "Item#", 70), ("desc", "Description", 230), ("cat", "Tab", 55),
            ("field", "What changed", 130), ("old", "Old", 80), ("new", "New", 80), ("chg", "Change", 135),
            ("user", "By", 80), ("src", "How", 190))
    frame = tk.Frame(parent, bg=PANEL)
    tree = ttk.Treeview(frame, columns=[c[0] for c in cols], show="headings", height=height)
    for k, h, w in cols:
        tree.heading(k, text=h)
        tree.column(k, width=w, anchor="e" if k in ("old", "new", "chg") else "w", stretch=(k == "desc"))
    ys = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=ys.set)
    tree.pack(side="left", fill="both", expand=True)
    ys.pack(side="left", fill="y")
    return frame, tree


class PriceHistoryWindow(tk.Toplevel):
    def __init__(self, app, product):
        super().__init__(app)
        self.title(f"Price history - {product['description']}")
        self.configure(bg=PANEL)
        self.geometry("1260x420")
        self.transient(app)
        tk.Label(self, text=f"📜  {product['description']}  (Item# {product['item_no'] or '-'})", font=FONT_H,
                 bg=PANEL, fg=NAVY).pack(anchor="w", padx=14, pady=(12, 6))
        frame, tree = make_history_tree(self)
        frame.pack(fill="both", expand=True, padx=14)
        rows = app.db.price_history(product_id=product["id"])
        fill_history_tree(tree, rows)
        tk.Label(self, text=f"{len(rows)} change(s) recorded." if rows else "No price changes recorded yet for this product.",
                 font=("Segoe UI", 9), bg=PANEL, fg=GREY_FG).pack(anchor="w", padx=14, pady=8)
        ttk.Button(self, text="Close", command=self.destroy).pack(anchor="e", padx=14, pady=(0, 12))


# ----------------------------------------------------------- import review
class ImportReport(tk.Toplevel):
    """Shows what an import will do and every problem found, before anything is written."""

    def __init__(self, app, name, adds, updates, problems, can_import=True):
        super().__init__(app)
        self.go = False
        self.title(f"Import check - {name}")
        self.configure(bg=PANEL)
        self.geometry("880x500")
        self.transient(app)
        skipped = sum(1 for x in problems if ": skipped" in x)
        warns = len(problems) - skipped
        tk.Label(self, text=f"Checked {name}", font=FONT_H, bg=PANEL, fg=NAVY).pack(anchor="w", padx=16, pady=(14, 4))
        summary = (f"✔ {len(adds)} new product(s) will be added\n✔ {len(updates)} existing product(s) will be updated "
                   f"(matched by Item#)\n" + (f"✖ {skipped} row(s) have errors and will be skipped\n" if skipped else "")
                   + (f"⚠ {warns} warning(s) to review\n" if warns else ""))
        tk.Label(self, text=summary, font=FONT, bg=PANEL, justify="left").pack(anchor="w", padx=16)
        if problems:
            box = tk.Text(self, font=("Segoe UI", 9), height=12, wrap="word", bd=1, relief="solid")
            box.pack(fill="both", expand=True, padx=16, pady=6)
            for line in problems:
                box.insert("end", ("✖ " if ": skipped" in line else "⚠ ") + line + "\n")
            box.config(state="disabled")
        else:
            tk.Label(self, text="No problems found.", font=FONT, bg=PANEL, fg="#2e7d32").pack(anchor="w", padx=16, pady=6)
        bar = tk.Frame(self, bg=PANEL)
        bar.pack(fill="x", padx=16, pady=(4, 14))
        if can_import:
            tk.Label(bar, text="A backup is made first, and all rows are saved together,\nso if anything fails nothing is changed.",
                     font=("Segoe UI", 9), bg=PANEL, fg=GREY_FG, justify="left").pack(side="left")
            ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="right", padx=4)
            ttk.Button(bar, text=f"Import {len(adds) + len(updates)} row(s)", style="Accent.TButton",
                       command=self._ok).pack(side="right", padx=4)
        else:
            tk.Label(bar, text="Nothing to import. Fix the rows above and try again.", font=FONT, bg=PANEL,
                     fg="#c62828").pack(side="left")
            ttk.Button(bar, text="Close", command=self.destroy).pack(side="right")
        self.grab_set()

    def _ok(self):
        self.go = True
        self.destroy()


# ------------------------------------------------------------------- app
class App(tk.Tk):
    def __init__(self, db):
        super().__init__()
        self.db = db
        sounds.set_enabled(db.get_setting("sounds", "1") == "1")
        db.on_change = lambda changes: sounds.play(sounds.for_changes(changes))      # up / down / saved
        self.bot = ChatBot(db)
        self.logged_out = False
        self.withdraw()
        self.title(f"{APP_NAME} v{APP_VERSION}")
        try:
            self.iconbitmap(resource_path("assets", "app.ico"))
        except Exception:
            pass
        self._styles()
        if not startup_gate(self, db, backup_cb=self._backup_now):       # license / trial check
            self.alive = False
            self.destroy()
            return
        login = LoginDialog(self, db)
        self.wait_window(login)
        self.alive = bool(login.user)
        if not login.user:
            self.destroy()
            return
        self.user = login.user
        self.is_admin = self.user["role"] == "admin"
        self.compact = self.winfo_screenheight() < 900          # laptops like 1366x768
        self.geometry("1440x900" if not self.compact else "1340x700")
        self.minsize(1100, 640)
        self.configure(bg=BG)
        self.active_cat = "Beer"
        self._build()
        self._bind_shortcuts()
        self.show("home")
        self.after(300, lambda: self.scan_entry.focus_set())
        self.after(4000, self._quiet_update_check)
        self.deiconify()
        try:
            self.state("zoomed")
        except tk.TclError:
            pass
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        if not db.startup_ok:
            db.log("Startup check found database damage", self.user["username"], "maintenance")
            self.after(400, lambda: messagebox.showwarning(
                "Database check", "The quick database check found a problem.\n\nGo to Backup > Run health check, "
                "and restore your newest backup if it fails."))

    # ---------- look ----------
    def _styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", font=FONT)
        s.configure("TButton", padding=(8, 3), background=PANEL, bordercolor=NAVY, relief="solid")
        s.map("TButton", background=[("active", "#e3f0fc")])
        s.configure("Accent.TButton", background=BLUE, foreground="white", bordercolor=BLUE)
        s.map("Accent.TButton", background=[("active", "#1565c0")])
        s.configure("Danger.TButton", foreground="#b71c1c", bordercolor="#b71c1c")
        s.configure("Treeview", rowheight=26, font=FONT, background=PANEL, fieldbackground=PANEL, bordercolor=LINE)
        s.configure("Treeview.Heading", font=FONT_B, background="#f5f8fc", relief="raised", padding=(4, 6))
        s.map("Treeview", background=[("selected", "#4a6585")], foreground=[("selected", "white")])

    def _panel(self, parent, title, bg=PANEL, icon="", fg=NAVY):
        f = tk.Frame(parent, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        head = tk.Frame(f, bg=bg)
        head.pack(fill="x")
        compact = getattr(self, "compact", False)
        tk.Label(head, text=f"{icon}  {title}" if icon else title, font=("Segoe UI", 12, "bold") if compact else FONT_H,
                 bg=bg, fg=fg).pack(side="left", padx=12, pady=3 if compact else 7)
        body = tk.Frame(f, bg=PANEL)
        body.pack(fill="both", expand=True, padx=12, pady=4 if compact else 8)
        return f, head, body

    # ---------- layout ----------
    def _build(self):
        side = tk.Frame(self, bg=NAVY, width=230)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        self.logo_img = load_image("logo.png")
        if self.logo_img and self.compact:
            self.logo_img = self.logo_img.subsample(2)
        if self.logo_img:
            tk.Label(side, image=self.logo_img, bg=NAVY).pack(pady=(14, 0))
        tk.Label(side, text="Beer and Liquor\nPricing", font=("Segoe UI", 15, "bold"), bg=NAVY, fg="white").pack(pady=(2, 14))
        self.nav = {}
        self.current = None
        for key, label in (("home", "⌂   Home"), ("beer", "🍺  Beer"), ("liquor", "🥃  Liquor"),
                           ("reports", "▤   Reports (PDF)"), ("io", "⇅   Import / Export"),
                           ("users", "👤  Users"), ("audit", "🔐  Audit Log"), ("backup", "⛁   Backup"), ("help", "💬  Help / Chatbot"),
                           ("about", "ⓘ   About")):
            b = tk.Label(side, text=label, font=("Segoe UI", 11, "bold" if key in ("beer", "liquor") else "normal"),
                         bg=NAVY, fg="white", anchor="w", padx=24, pady=7 if self.compact else 10, cursor="hand2")
            b.pack(fill="x")
            b.bind("<Button-1>", lambda e, k=key: self.show(k))
            b.bind("<Enter>", lambda e, b=b, k=key: b.config(bg=BLUE if self.current == k else NAVY_HOVER))
            b.bind("<Leave>", lambda e, b=b, k=key: b.config(bg=BLUE if self.current == k else NAVY))
            self.nav[key] = b

        right = tk.Frame(self, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        self._build_banner(right)
        foot = tk.Frame(right, bg=NAVY, height=30)
        foot.pack(side="bottom", fill="x")
        self.footer_left = tk.Label(foot, font=("Segoe UI", 10, "bold"), bg=NAVY, fg="white")
        self.footer_left.pack(side="left", padx=18, pady=5)
        tk.Label(foot, text=CREDIT, font=("Segoe UI", 10), bg=NAVY, fg="white").pack(side="right", padx=18)
        self.update_lbl = tk.Label(foot, text="", font=("Segoe UI", 10, "bold"), bg="#ffc247", fg=NAVY, padx=10,
                                   cursor="hand2")
        self.update_lbl.bind("<Button-1>", lambda e: self._check_updates(manual=True))
        self._update_footer()
        self.content = tk.Frame(right, bg=BG)
        self.content.pack(fill="both", expand=True)
        self.pages = {k: getattr(self, f"_page_{k}")() for k in ("home", "reports", "io", "users", "audit", "backup", "help", "about")}

    def _update_footer(self):
        try:
            lic_txt = lic.describe(lic.status(self.db))
        except Exception:
            lic_txt = ""
        self.footer_left.config(text=f"© {datetime.date.today().year} {self.db.get_setting('store_name', 'My Store')}   |   "
                                     f"{APP_NAME}   v{APP_VERSION}" + (f"   |   {lic_txt}" if lic_txt else ""))

    def _build_banner(self, parent):
        sm = "_sm" if self.compact else ""
        self.banner_imgs = {k: load_image(f) for k, f in (("bg", f"banner_bg{sm}.png"), ("beer", f"banner_beer{sm}.png"),
                                                           ("liquor", f"banner_liquor{sm}.png"), ("badge", "badge_bg.png"))}
        c = self.banner = tk.Canvas(parent, height=138 if self.compact else 190, bg="#1d1006", highlightthickness=0)
        c.pack(side="top", fill="x")
        if self.banner_imgs["bg"]:
            c.create_image(0, 0, image=self.banner_imgs["bg"], anchor="n", tags="bg")
        if self.banner_imgs["beer"]:
            c.create_image(0, -6, image=self.banner_imgs["beer"], anchor="nw", tags="beer")
        if self.banner_imgs["liquor"]:
            c.create_image(0, -6, image=self.banner_imgs["liquor"], anchor="ne", tags="liquor")
        for dx, col, tag in ((2, "#000000", "tshadow"), (0, "white", "title")):
            c.create_text(0, 0, text=APP_NAME, fill=col, font=("Segoe UI", 38, "bold"), tags=tag)
        for dx, col, tag in ((1, "#000000", "sshadow"), (0, "#ffe2a8", "sub")):
            c.create_text(0, 0, text="Simple  •  Accurate  •  Professional", fill=col, font=("Segoe UI", 17), tags=tag)
        if self.banner_imgs["badge"]:
            c.create_image(0, 10, image=self.banner_imgs["badge"], anchor="ne", tags="badge")
        c.create_oval(0, 0, 0, 0, fill="#5b8fd1", outline="white", width=2, tags="avatar")
        c.create_text(0, 0, text="👤", fill="white", font=("Segoe UI", 13), tags="avatar_t")
        c.create_text(0, 0, text=f"{self.user['username']}\n{self.user['role'].title()}", fill="white",
                      font=("Segoe UI", 10, "bold"), anchor="w", tags="who")
        btn = tk.Button(c, text="Logout", font=("Segoe UI", 10, "bold"), bg=NAVY, fg="white", activebackground=BLUE,
                        activeforeground="white", relief="flat", padx=14, pady=4, cursor="hand2", command=self.logout)
        c.create_window(0, 0, window=btn, anchor="ne", tags="logout")
        c.bind("<Configure>", self._layout_banner)

    def _layout_banner(self, e=None):
        c = self.banner
        w, h = c.winfo_width(), int(c["height"])
        k = 0.72 if self.compact else 1.0
        c.coords("bg", w / 2, -5 * k)
        size = int((38 if w > 1500 else 32 if w > 1250 else 28) * k)
        for tag, dx in (("tshadow", 2), ("title", 0)):
            c.itemconfig(tag, font=("Segoe UI", size, "bold"))
            c.coords(tag, w / 2 + dx, h * .42 + dx)
        for tag, dx in (("sshadow", 1), ("sub", 0)):
            c.itemconfig(tag, font=("Segoe UI", int((17 if w > 1250 else 14) * k)))
            c.coords(tag, w / 2 + dx, h * .68 + dx)
        # keep the artwork clear of the title: slide it off the edges on narrow windows
        x0, _, x1, _ = c.bbox("title") or (w / 2 - 300, 0, w / 2 + 300, 0)
        art_w = (self.banner_imgs["beer"].width() if self.banner_imgs["beer"] else 400)
        c.coords("beer", min(6, x0 - art_w - 12), -8 * k)
        c.coords("liquor", max(w - 6, x1 + art_w + 12), -8 * k)
        bx = w - 12
        c.coords("badge", bx, 8)
        c.coords("avatar", bx - 286, 16, bx - 246, 56)
        c.coords("avatar_t", bx - 266, 36)
        c.coords("who", bx - 236, 36)
        c.coords("logout", bx - 10, 20)
        c.tag_raise("badge")
        for t in ("avatar", "avatar_t", "who", "logout"):
            c.tag_raise(t)

    def logout(self):
        if not messagebox.askyesno("Logout", "Sign out of this account?"):
            return
        self.logged_out = True
        self.db.log("Signed out", self.user["username"], "login")
        self.destroy()

    def show(self, key):
        for k, b in self.nav.items():
            b.config(bg=BLUE if k == key else NAVY)
        for p in self.pages.values():
            p.pack_forget()
        page = "home" if key in ("home", "beer", "liquor") else key
        pad = 6 if self.compact else 10
        self.pages[page].pack(fill="both", expand=True, padx=12, pady=pad)
        self.current = key
        if page == "home":
            if key in ("beer", "liquor"):
                self.set_active(key.title())
            else:
                self._arrange_sections()
            for k, b in self.nav.items():          # Home stays lit together with the open tab
                b.config(bg=BLUE if k == key or (k == "home" and key in ("beer", "liquor")) else NAVY)
            self.refresh()
        elif key == "users":
            self._page_users_body_refresh()
        elif key == "backup":
            self._refresh_backups()
        elif key == "audit":
            self._refresh_audit()

    # ---------- home ----------
    def _page_home(self):
        page = tk.Frame(self.content, bg=BG)
        tabs = tk.Frame(page, bg=BG)
        tabs.pack(fill="x", pady=(0, 6))
        self.tab_btns = {}
        for cat in calc.CATEGORIES:
            prof = calc.profile(cat)
            b = tk.Label(tabs, text=f"{prof['icon']}  {prof['title']}", font=("Segoe UI", 11, "bold"), fg=NAVY,
                         padx=22, pady=4 if self.compact else 8, cursor="hand2", highlightthickness=2)
            b.pack(side="left", padx=(0, 4))
            b.bind("<Button-1>", lambda e, c=cat: self._tab_click(c))
            self.tab_btns[cat] = b

        tb = tk.Frame(page, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        tb.pack(fill="x")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self.refresh())
        if self.compact:                               # laptop screens: scan/search get their own row
            tb2 = tk.Frame(page, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
            tb2.pack(fill="x")
            sf = tk.Frame(tb2, bg=PANEL)
            sf.pack(side="left", padx=8, pady=3)
        else:
            sf = tk.Frame(tb, bg=PANEL)
            sf.pack(side="right", padx=8)
        self.dep_var = tk.BooleanVar(value=self.db.include_dep())
        ttk.Button(sf, text="⚙ Pricing", command=self.open_pricing_rules, width=0).pack(side="left", padx=(0, 10))
        tk.Label(sf, text="▥ Scan", font=FONT_B, bg=PANEL, fg=NAVY).pack(side="left", padx=(0, 4))
        self.scan_var = tk.StringVar()
        self.scan_entry = ttk.Entry(sf, textvariable=self.scan_var, width=20 if self.compact else 16)
        self.scan_entry.pack(side="left")
        self.scan_entry.bind("<Return>", self._on_scan)
        self.scan_entry.bind("<KP_Enter>", self._on_scan)
        self.scan_mode = tk.StringVar(value="Open" if self.db.get_setting("scan_mode", "open") == "open" else "Select")
        sm = ttk.Combobox(sf, textvariable=self.scan_mode, values=["Open", "Select"], state="readonly", width=6)
        sm.pack(side="left", padx=(2, 10))
        sm.bind("<<ComboboxSelected>>", lambda e: self.db.set_setting("scan_mode", self.scan_mode.get().lower()))
        tk.Label(sf, text="Search", font=FONT, bg=PANEL, fg=GREY_FG).pack(side="left", padx=(0, 4))
        self.search_entry = ttk.Entry(sf, textvariable=self.search_var, width=24 if self.compact else 20)
        self.search_entry.pack(side="left")
        for text, cmd, style in (("+ Add Product", self.add_product, "Accent.TButton"), ("✎ Edit", self.edit_selected, "TButton"),
                                 ("🗑 Delete", self.delete_selected, "Danger.TButton"),
                                 ("💲 Bulk Update", self.open_bulk_update, "TButton"),
                                 ("🏷 Labels", self.open_labels, "TButton"),
                                 ("⇩ Import", self.do_import, "TButton"), ("⇧ Export", self.do_export, "TButton"),
                                 ("▤ PDF", lambda: self.make_pdf("all"), "TButton"),
                                 ("⎙ Print", lambda: self.make_pdf("all", print_it=True), "TButton"),
                                 ("⟳", self.refresh, "TButton")):
            ttk.Button(tb, text=text, command=cmd, style=style, width=0).pack(side="left", padx=(6, 0), pady=4 if self.compact else 7)
        self.scan_status = tk.Label(page, text="", font=FONT_B, bg=BG, anchor="e")

        bottom = tk.Frame(page, bg=BG)
        bottom.pack(side="bottom", fill="x")          # packed first so it always keeps its space
        self.sec_area = tk.Frame(page, bg=BG)
        self.sec_area.pack(fill="both", expand=True, pady=(6, 6))
        self.sections = {cat: Section(self, self.sec_area, cat) for cat in calc.CATEGORIES}
        bottom.columnconfigure((0, 1, 2), weight=1, uniform="b")
        qs, _, qb = self._panel(bottom, "Quick Stats")
        qs.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.stat_labels = {}
        for i, (k, lbl) in enumerate((("beer", "🍺 Beer items"), ("liquor", "🥃 Liquor items"), ("total", "Total products"),
                                      ("low", "Below target"), ("oos", "Out of stock"), ("value", "Inventory value"))):
            f = tk.Frame(qb, bg=PANEL)
            f.grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 22), pady=1)
            tk.Label(f, text=lbl, font=("Segoe UI", 9), bg=PANEL, fg=GREY_FG).pack(anchor="w")
            self.stat_labels[k] = tk.Label(f, text="0", font=("Segoe UI", 12, "bold"), bg=PANEL, fg=NAVY)
            self.stat_labels[k].pack(anchor="w")
        ra, _, rb = self._panel(bottom, "Recent Activity")
        ra.grid(row=0, column=1, sticky="nsew", padx=6)
        self.activity_box = tk.Text(rb, height=3 if self.compact else 4, font=("Segoe UI", 9), bd=0, bg=PANEL, wrap="none")
        self.activity_box.pack(fill="both", expand=True)
        hc, _, hb = self._panel(bottom, "Help / Chatbot")
        hc.grid(row=0, column=2, sticky="nsew", padx=(6, 0))
        self.mini_answer = tk.Label(hb, text="Ask how to add products, calculate prices, import, PDF, users, backup or updates.",
                                    font=("Segoe UI", 9), bg=PANEL, fg=TEXT, wraplength=380, justify="left", anchor="nw")
        self.mini_answer.pack(fill="both", expand=True)
        row = tk.Frame(hb, bg=PANEL)
        row.pack(fill="x", pady=(4, 0))
        self.mini_q = tk.StringVar()
        me = ttk.Entry(row, textvariable=self.mini_q)
        me.pack(side="left", fill="x", expand=True)
        me.bind("<Return>", lambda e: self._mini_ask())
        ttk.Button(row, text="Send", style="Accent.TButton", command=self._mini_ask).pack(side="left", padx=(6, 0))
        self._paint_tabs()
        return page

    def _arrange_sections(self):
        """Show only the selected tab's table, full size, like the original single-table layout."""
        for s in self.sections.values():
            s.frame.pack_forget()
        self.sections[self.active_cat].frame.pack(fill="both", expand=True)

    def _tab_click(self, cat):
        self.show(cat.lower())

    def set_active(self, cat, from_table=False):
        if from_table:
            return
        self.active_cat = cat
        self._paint_tabs()
        if hasattr(self, "sections"):
            self._arrange_sections()

    def _paint_tabs(self):
        for cat, b in self.tab_btns.items():
            on = cat == self.active_cat
            b.config(bg=PANEL if on else "#dfe6ef", highlightbackground=NAVY if on else LINE,
                     fg=THEME[cat]["title"])

    def _mini_ask(self):
        q = self.mini_q.get().strip()
        if not q:
            return
        ans = self.bot.respond(q)
        short = ans if len(ans) < 220 else ans[:217] + "…  (open Help / Chatbot for the full answer)"
        self.mini_answer.config(text=short)
        self.mini_q.set("")
        self._chat_add("You", q)
        self._chat_add("Assistant", ans)

    def _toggle_dep(self):
        self.db.set_setting("include_dep", "1" if self.dep_var.get() else "0")
        self.db.log(f"Deposit in cost turned {'on' if self.dep_var.get() else 'off'}", self.user["username"], "settings")
        self.refresh()

    def refresh(self):
        if not hasattr(self, "sections"):
            return
        search = self.search_var.get()
        for s in self.sections.values():
            s.refresh(search)
        inc = self.db.include_dep()
        tgs = self.db.all_targets()
        allp = self.db.list_products()
        stats = [calc.compute(p, inc, tgs.get(p["category"], tgs["Beer"])) for p in allp]
        beer = sum(1 for p in allp if p["category"] == "Beer")
        low = sum(s["low_margin"] for s in stats)
        self.stat_labels["beer"].config(text=str(beer))
        self.stat_labels["liquor"].config(text=str(len(allp) - beer))
        self.stat_labels["total"].config(text=str(len(allp)))
        self.stat_labels["oos"].config(text=str(sum(s["out_of_stock"] for s in stats)))
        self.stat_labels["low"].config(text=str(low), fg="#c62828" if low else NAVY)
        self.stat_labels["value"].config(text=f"${sum(s['ext'] for s in stats):,.2f}")
        self.activity_box.config(state="normal")
        self.activity_box.delete("1.0", "end")
        for a in self.db.recent_activity(5):
            self.activity_box.insert("end", f"{a['ts']}   {a['action']}   {a['username']}\n")
        self.activity_box.config(state="disabled")

    # ---------- time-savers ----------
    def open_pricing_rules(self):
        if self._need_admin("change pricing rules"):
            PricingRulesDialog(self)

    def _flash(self, text, ok=True):
        self.scan_status.config(text=text, fg="#2e7d32" if ok else "#c62828")
        if self.compact:
            self.scan_status.place(in_=self.scan_entry.master, relx=1.0, rely=0.5, x=12, anchor="w")
        else:
            self.scan_status.place(in_=self.scan_entry, relx=1.0, rely=1.0, x=0, y=4, anchor="ne")
        self.scan_status.lift()
        if getattr(self, "_flash_job", None):
            self.after_cancel(self._flash_job)
        self._flash_job = self.after(3500, self.scan_status.place_forget)

    def _on_scan(self, e=None):
        code = self.scan_var.get().strip()
        self.scan_var.set("")
        if not code:
            return
        p = self.db.find_by_upc(code)
        if not p:
            self._flash(f"✖ {code} not found", ok=False)
            sounds.play("error")
            if messagebox.askyesno("Not found", f"No product has UPC or Item# {code}.\n\nAdd it as a new product?"):
                dlg = ProductDialog(self, category=self.active_cat, preset={"upc": code})
                self.wait_window(dlg)
                if dlg.result:
                    pid = self.db.add_product(dlg.result, self.user["username"])
                    if dlg.result["category"] != self.active_cat:
                        self.show(dlg.result["category"].lower())
                    self.refresh()
                    tree = self.sections[dlg.result["category"]].tree
                    if tree.exists(str(pid)):
                        tree.selection_set(str(pid))
                        tree.see(str(pid))
            self.scan_entry.focus_set()
            return
        if self.search_var.get():
            self.search_var.set("")
        if p["category"] != self.active_cat:
            self.show(p["category"].lower())
        tree, iid = self.sections[p["category"]].tree, str(p["id"])
        if not tree.exists(iid):
            self.refresh()
        if self.scan_mode.get() == "Select":
            tree.selection_add(iid)
            self._flash(f"✔ Added: {p['description'][:28]}  ({len(tree.selection())} selected)")
        else:
            tree.selection_set(iid)
            tree.see(iid)
            self._flash(f"✔ {p['description'][:34]}")
            dlg = ProductDialog(self, p)
            self.wait_window(dlg)
            if dlg.result:
                self.db.update_product(p["id"], dlg.result, self.user["username"], source="scan + edit window")
                self.refresh()
        tree.see(iid)
        self.scan_entry.focus_set()

    def _products_for_action(self, what):
        sec, ids = self._selected()
        if ids:
            return sec.cat, [self.db.get_product(i) for i in ids]
        cat = self.active_cat
        shown = self.db.list_products(self.search_var.get(), cat)
        if not shown:
            messagebox.showinfo(what, f"There are no {cat.lower()} products to work on.")
            return None, None
        scope = "matching your search" if self.search_var.get().strip() else "in the tab"
        if not messagebox.askyesno(what, f"No products are selected.\n\nUse all {len(shown)} {cat.lower()} products {scope}?"):
            return None, None
        return cat, shown

    def open_bulk_update(self):
        cat, prods = self._products_for_action("Bulk update")
        if prods:
            BulkUpdateDialog(self, prods, cat)

    def open_labels(self, products=None):
        if products is None:
            sec, ids = self._selected()
            products = [self.db.get_product(i) for i in ids]
        LabelDialog(self, products, self.active_cat)

    def show_cost_changes(self, days=None):
        if days is None:
            days = simpledialog.askinteger("Cost changes", "Show cost changes from the last how many days?",
                                           initialvalue=7, minvalue=1, maxvalue=3650, parent=self)
            if not days:
                return
        since = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
        rows = pricing.cost_changes(self.db, since)
        if not rows:
            messagebox.showinfo("Cost changes", f"No cost (Net, Dep or Case size) changes in the last {days} day(s).")
            return
        CostChangeWindow(self, rows, f"Cost changes in the last {days} day(s)")

    def _bind_shortcuts(self):
        def home_only(fn):
            def h(e):
                if self.current in ("home", "beer", "liquor"):
                    fn()
                    return "break"
            return h
        for seq, fn in (("<Control-n>", self.add_product), ("<Control-e>", self.edit_selected),
                        ("<Control-f>", lambda: self.search_entry.focus_set()), ("<F2>", lambda: self.scan_entry.focus_set()),
                        ("<Control-b>", self.open_bulk_update), ("<Control-l>", self.open_labels),
                        ("<F5>", self.refresh), ("<Control-p>", lambda: self.make_pdf("all", print_it=True))):
            self.bind(seq, home_only(fn))

    # ---------- product actions ----------
    def _selected(self):
        """(section, ids) of the table that has a selection, preferring the active tab."""
        order = [self.active_cat] + [c for c in self.sections if c != self.active_cat]
        for c in order:
            ids = self.sections[c].selected_ids()
            if ids:
                return self.sections[c], ids
        return None, []

    def add_product(self):
        dlg = ProductDialog(self, category=self.active_cat)
        self.wait_window(dlg)
        if dlg.result:
            pid = self.db.add_product(dlg.result, self.user["username"])
            cat = dlg.result["category"]
            if cat != self.active_cat:
                self.show(cat.lower())
            self.refresh()
            tree = self.sections[cat].tree
            if tree.exists(str(pid)):
                tree.selection_set(str(pid))
                tree.see(str(pid))

    def edit_selected(self):
        sec, ids = self._selected()
        if not ids:
            messagebox.showinfo("Edit", "Select a product first.")
            return
        dlg = ProductDialog(self, self.db.get_product(ids[0]))
        self.wait_window(dlg)
        if dlg.result:
            self.db.update_product(ids[0], dlg.result, self.user["username"], source="edit window")
            self.refresh()

    def delete_selected(self):
        if not self.is_admin:
            messagebox.showwarning("Not allowed", "Only admin users can delete products.")
            return
        sec, ids = self._selected()
        if not ids:
            messagebox.showinfo("Delete", "Select one or more products first.")
            return
        if messagebox.askyesno("Delete products", f"Delete {len(ids)} {sec.cat.lower()} product(s)? This can't be undone (use Backup > Restore if needed)."):
            self.db.delete_products(ids, self.user["username"])
            self.refresh()

    # ---------- files ----------
    def do_import(self):
        """Safer import: read -> check every row -> show problems -> backup -> one transaction."""
        path = filedialog.askopenfilename(title="Import products or a supplier invoice",
                                          filetypes=[("Excel, CSV or PDF invoice", "*.xlsx *.xlsm *.csv *.pdf"),
                                                     ("Supplier invoice PDF", "*.pdf"), ("All files", "*.*")])
        if not path:
            return
        name = os.path.basename(path)
        try:
            if path.lower().endswith(".pdf"):
                items, pdf, notes = io_utils.read_pdf_invoice(path)
                adds, updates, problems = io_utils.plan_import(self.db, items)
                problems = notes + problems
                name = f"{name} ({pdf['supplier']} invoice {pdf['invoice_no']}, {pdf['date']})"
                if not pdf["ok"]:
                    sounds.play("warning")
                    messagebox.showwarning("Check this invoice", "The lines read from this PDF don't add up to the "
                                           "invoice's printed total. Look over the lines on the next screen before importing.")
            else:
                items = io_utils.read_file(path, default_category=self.active_cat)
                adds, updates, problems = io_utils.plan_import(self.db, items)
        except Exception as ex:
            self.db.log(f"Import of {name} failed to read: {ex}", self.user["username"], "import")
            sounds.play("error")
            messagebox.showerror("Import failed", f"Couldn't read {name}:\n{ex}\n\nNothing was changed.")
            return
        if not adds and not updates:
            ImportReport(self, name, adds, updates, problems, can_import=False)
            return
        rep = ImportReport(self, name, adds, updates, problems, can_import=True)
        self.wait_window(rep)
        if not rep.go:
            self.db.log(f"Import of {name} cancelled after review", self.user["username"], "import")
            return
        start_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        try:
            backup = io_utils.apply_import(self.db, adds, updates, self.user["username"], name)
        except Exception as ex:
            self.db.log(f"Import of {name} FAILED and was rolled back: {ex}", self.user["username"], "import")
            sounds.play("error")
            messagebox.showerror("Import failed", f"Something went wrong:\n{ex}\n\nNothing was changed "
                                                   "(the import was rolled back).")
            return
        self.refresh()
        skipped = sum(1 for x in problems if ": skipped" in x)
        cost_rows = pricing.cost_changes(self.db, start_ts, source=f"import {name}")
        below = sum(r["below"] for r in cost_rows)
        sounds.play("success")
        messagebox.showinfo("Import finished", f"{len(adds)} added, {len(updates)} updated, {skipped} skipped.\n\n"
                                               f"A backup was saved first:\n{os.path.basename(backup)}"
                                               + (f"\n\n⚠ Costs changed on {len({r['product']['id'] for r in cost_rows})} "
                                                  f"product(s); {below} price(s) are now below target." if cost_rows else ""))
        if cost_rows:
            CostChangeWindow(self, cost_rows, f"Cost changes from {name}")

    def do_export(self, kind=None):
        ft = [("Excel workbook", "*.xlsx"), ("CSV file", "*.csv")]
        if kind == "csv":
            ft = ft[::-1]
        path = filedialog.asksaveasfilename(title="Export products", defaultextension=".xlsx" if kind != "csv" else ".csv",
                                            initialfile="products", filetypes=ft)
        if not path:
            return
        prods = self.db.list_products()
        try:
            if path.lower().endswith(".csv"):
                io_utils.export_csv(path, prods, self.db.include_dep(), self.db.all_targets())
            else:
                io_utils.export_xlsx(path, prods, self.db.include_dep(), self.db.all_targets())
        except Exception as ex:
            messagebox.showerror("Export failed", str(ex))
            return
        self.db.log(f"Exported {len(prods)} products to {os.path.basename(path)}", self.user["username"], "export")
        self.refresh()
        if messagebox.askyesno("Export finished", f"Saved {len(prods)} products.\nOpen the file now?"):
            io_utils.open_file(path)

    def make_pdf(self, which, print_it=False, category=None):
        tgs, inc = self.db.all_targets(), self.db.include_dep()
        prods = self.db.list_products(category=category)

        def comp(p):
            return calc.compute(p, inc, tgs.get(p["category"], tgs["Beer"]))
        if which == "low":
            prods = [p for p in prods if comp(p)["low_margin"]]
            title = "Products Below Target Margin"
        elif which == "oos":
            prods = [p for p in prods if comp(p)["out_of_stock"]]
            title = "Out of Stock Products"
        else:
            title = f"{category + ' ' if category else ''}Price and Margin Report"
        if not prods:
            messagebox.showinfo("Nothing to report", "No products match this report.")
            return
        if print_it:
            path = os.path.join(tempfile.gettempdir(), f"bevmargin-{which}.pdf")
        else:
            path = filedialog.asksaveasfilename(title="Save PDF", defaultextension=".pdf",
                                                initialfile=title.lower().replace(" ", "-"), filetypes=[("PDF", "*.pdf")])
            if not path:
                return
        try:
            io_utils.export_pdf(path, prods, title, inc, tgs)
            io_utils.open_file(path, "print" if print_it else None)
        except Exception as ex:
            messagebox.showerror("PDF failed", str(ex))
            return
        self.db.log(("Printed " if print_it else "PDF: ") + title, self.user["username"], "export")
        self.refresh()

    # ---------- other pages ----------
    def _simple_page(self, title, icon=""):
        page = tk.Frame(self.content, bg=BG)
        f, head, body = self._panel(page, title, HEAD_BLUE, icon)
        f.pack(fill="both", expand=True)
        return page, head, body

    def _action_row(self, body, title, desc, btns):
        row = tk.Frame(body, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        row.pack(fill="x", pady=6)
        txt = tk.Frame(row, bg=PANEL)
        txt.pack(side="left", fill="x", expand=True, padx=14, pady=10)
        tk.Label(txt, text=title, font=FONT_B, bg=PANEL, fg=NAVY).pack(anchor="w")
        tk.Label(txt, text=desc, font=("Segoe UI", 9), bg=PANEL, fg=GREY_FG, justify="left").pack(anchor="w")
        made = []
        for text, cmd, style in reversed(btns):
            b = ttk.Button(row, text=text, command=cmd, style=style)
            b.pack(side="right", padx=(0, 12))
            made.insert(0, b)
        self._last_action_buttons = made

    def _page_reports(self):
        page, _, body = self._simple_page("Reports (PDF)", "▤")
        self._action_row(body, "Shelf labels / price tags", "Avery 5163 (large, 10 per sheet) or 5160 (small, 30 per sheet). "
                         "Selected products, everything changed since a date, or a whole tab.",
                         [("Make labels…", lambda: self.open_labels([]), "Accent.TButton")])
        self._action_row(body, "Cost changes", "Products whose Net cost went up or down, old vs new margin, and suggested new prices.",
                         [("Show cost changes…", self.show_cost_changes, "Accent.TButton")])
        self._action_row(body, "Beer only", "Beer tab: Case, 12 Pk, 6 Pk and single-can prices and margins.",
                         [("Save as PDF", lambda: self.make_pdf("all", category="Beer"), "Accent.TButton"),
                          ("Print", lambda: self.make_pdf("all", True, "Beer"), "TButton")])
        self._action_row(body, "Liquor only", "Liquor tab: Case, 6 Btl and 1 Btl prices and margins.",
                         [("Save as PDF", lambda: self.make_pdf("all", category="Liquor"), "Accent.TButton"),
                          ("Print", lambda: self.make_pdf("all", True, "Liquor"), "TButton")])
        for which, t, d in (("all", "All products", "Beer and Liquor, each in its own section with its own column names."),
                            ("low", "Below target margin", "Only products where Case, 12 Pk or 6 Pk margin is under your target."),
                            ("oos", "Out of stock", "Products with Qty 0, for reordering.")):
            self._action_row(body, t, d, [("Save as PDF", lambda w=which: self.make_pdf(w), "Accent.TButton"),
                                          ("Print", lambda w=which: self.make_pdf(w, True), "TButton")])
        return page

    def _page_io(self):
        page, _, body = self._simple_page("Import / Export", "⇅")
        self._action_row(body, "Import products", "Excel (.xlsx) or CSV. Existing Item# rows are updated, new ones are added.\nColumns are matched by name. A 'Category' column (Beer/Liquor) or Excel sheets named Beer and Liquor pick the tab;\notherwise rows go to the tab that's selected on Home.",
                         [("Import file…", self.do_import, "Accent.TButton")])
        self._action_row(body, "Export products", "Excel: one sheet per tab (Beer, Liquor) with margins. CSV: one file with a Category column.",
                         [("Export to Excel", lambda: self.do_export("xlsx"), "Accent.TButton"), ("Export to CSV", lambda: self.do_export("csv"), "TButton")])
        self._action_row(body, "Import template", "A sample CSV with the right column names to fill in.",
                         [("Save import template", self._save_template, "TButton")])
        return page

    def _save_template(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="import-template", filetypes=[("CSV", "*.csv")])
        if path:
            io_utils.write_template(path)
            messagebox.showinfo("Template saved", f"Saved to\n{path}")

    def _page_users(self):
        page, _, body = self._simple_page("Users", "👤")
        self.users_body = body
        return page

    def _page_users_body_refresh(self):
        body = self.users_body
        for w in body.winfo_children():
            w.destroy()
        bar = tk.Frame(body, bg=PANEL)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="Change my password", command=self._change_my_pw).pack(side="left")
        if not self.is_admin:
            tk.Label(body, text="Only admins can manage other users.", font=FONT, bg=PANEL, fg=GREY_FG).pack(anchor="w")
            return
        ttk.Button(bar, text="+ Add user", style="Accent.TButton", command=self._add_user).pack(side="left", padx=6)
        ttk.Button(bar, text="Reset password", command=self._reset_pw).pack(side="left")
        ttk.Button(bar, text="Delete user", style="Danger.TButton", command=self._del_user).pack(side="left", padx=6)
        self.user_tree = ttk.Treeview(body, columns=("u", "r", "c"), show="headings", height=10)
        for k, h, w in (("u", "Username", 200), ("r", "Role", 120), ("c", "Created", 160)):
            self.user_tree.heading(k, text=h)
            self.user_tree.column(k, width=w, anchor="w")
        for u in self.db.list_users():
            self.user_tree.insert("", "end", iid=str(u["id"]), values=(u["username"], u["role"], u["created_at"]))
        self.user_tree.pack(fill="both", expand=True)
        tk.Label(body, text="Admin: everything.   Clerk: add and edit products, reports, import/export. Can't delete products or manage users.",
                 font=("Segoe UI", 9), bg=PANEL, fg=GREY_FG).pack(anchor="w", pady=(6, 0))

    def _need_admin(self, what):
        """Permission check inside the action itself (not only by hiding buttons)."""
        if getattr(self, "is_admin", False):
            return True
        messagebox.showwarning("Not allowed", f"Only admin users can {what}.")
        self.db.log(f"Blocked: clerk tried to {what}", self.user["username"], "security")
        return False

    def _ask_pw(self, title, username=""):
        return ask_new_password(self, title, username)

    def _change_my_pw(self):
        cur = simpledialog.askstring("Change my password", "Current password:", show="•", parent=self)
        if cur is None:
            return
        if not self.db.verify_user(self.user["username"], cur):
            self.db.log("Change password refused: wrong current password", self.user["username"], "security")
            messagebox.showwarning("Change my password", "That isn't your current password.")
            return
        pw = self._ask_pw("Change my password", self.user["username"])
        if pw:
            self.db.set_password(self.user["username"], pw)
            self.db.log("Changed own password", self.user["username"], "user")
            messagebox.showinfo("Password changed", "Your password was changed.")

    def _add_user(self):
        if not self._need_admin("add users"):
            return
        name = simpledialog.askstring("Add user", "Username:", parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        if len(name) > 40 or not all(c.isalnum() or c in " ._-@" for c in name):
            messagebox.showwarning("Add user", "Usernames can use letters, numbers, spaces and . _ - @ (up to 40).")
            return
        pw = self._ask_pw("Add user", name)
        if not pw:
            return
        role = "admin" if messagebox.askyesno("Role", f"Make {name} an admin?\n\nYes = admin, No = clerk") else "clerk"
        try:
            self.db.add_user(name, pw, role)
        except Exception:
            messagebox.showerror("Add user", f"A user called '{name}' already exists.")
            return
        self.db.log(f"Added user {name} ({role})", self.user["username"], "user")
        self._page_users_body_refresh()

    def _sel_user(self):
        s = self.user_tree.selection()
        if not s:
            messagebox.showinfo("Users", "Select a user first.")
            return None
        return int(s[0]), self.user_tree.item(s[0])["values"][0]

    def _reset_pw(self):
        if not self._need_admin("reset passwords"):
            return
        sel = self._sel_user()
        if sel:
            pw = self._ask_pw(f"Reset password for {sel[1]}", str(sel[1]))
            if pw:
                self.db.set_password(sel[1], pw)
                self.db.log(f"Reset password for {sel[1]}", self.user["username"], "user")
                messagebox.showinfo("Password reset", f"Password for {sel[1]} was changed.")

    def _del_user(self):
        if not self._need_admin("delete users"):
            return
        sel = self._sel_user()
        if not sel:
            return
        if str(sel[1]).lower() == self.user["username"].lower():
            messagebox.showwarning("Delete user", "You can't delete the account you're signed in with.")
            return
        if messagebox.askyesno("Delete user", f"Delete user {sel[1]}?"):
            try:
                self.db.delete_user(sel[0])
            except ValueError as ex:
                messagebox.showwarning("Delete user", str(ex))
                return
            self.db.log(f"Deleted user {sel[1]}", self.user["username"], "user")
            self._page_users_body_refresh()

    def _page_audit(self):
        page, _, body = self._simple_page("Audit Log and Price History", "🔐")
        self.audit_body = body
        self.audit_locked = tk.Label(body, text="Only admins can view the audit log.", font=FONT, bg=PANEL, fg=GREY_FG)
        nb = ttk.Notebook(body)
        self.audit_nb = nb
        # audit tab
        a = tk.Frame(nb, bg=PANEL)
        nb.add(a, text="  Audit Log  ")
        bar = tk.Frame(a, bg=PANEL)
        bar.pack(fill="x", pady=6)
        tk.Label(bar, text="Show", font=FONT, bg=PANEL).pack(side="left")
        self.audit_kind = tk.StringVar(value="All")
        cb = ttk.Combobox(bar, textvariable=self.audit_kind, state="readonly", width=18,
                          values=["All"] + list(AUDIT_KINDS.values()))
        cb.pack(side="left", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda e: self._refresh_audit())
        tk.Label(bar, text="Search", font=FONT, bg=PANEL, fg=GREY_FG).pack(side="left", padx=(12, 4))
        self.audit_q = tk.StringVar()
        self.audit_q.trace_add("write", lambda *x: self._refresh_audit())
        ttk.Entry(bar, textvariable=self.audit_q, width=26).pack(side="left")
        ttk.Button(bar, text="Export to CSV", command=self._export_audit).pack(side="right")
        f = tk.Frame(a, bg=PANEL)
        f.pack(fill="both", expand=True)
        self.audit_tree = ttk.Treeview(f, columns=("ts", "user", "kind", "action"), show="headings")
        for k, h, w in (("ts", "When", 140), ("user", "User", 110), ("kind", "Type", 130), ("action", "What happened", 700)):
            self.audit_tree.heading(k, text=h)
            self.audit_tree.column(k, width=w, anchor="w", stretch=(k == "action"))
        ys = ttk.Scrollbar(f, orient="vertical", command=self.audit_tree.yview)
        self.audit_tree.configure(yscrollcommand=ys.set)
        self.audit_tree.pack(side="left", fill="both", expand=True)
        ys.pack(side="left", fill="y")
        self.audit_tree.tag_configure("security", foreground="#c62828")
        # price history tab
        h = tk.Frame(nb, bg=PANEL)
        nb.add(h, text="  Price History  ")
        hb = tk.Frame(h, bg=PANEL)
        hb.pack(fill="x", pady=6)
        tk.Label(hb, text="Search product, Item# or user", font=FONT, bg=PANEL, fg=GREY_FG).pack(side="left", padx=(0, 4))
        self.ph_q = tk.StringVar()
        self.ph_q.trace_add("write", lambda *x: self._refresh_audit())
        ttk.Entry(hb, textvariable=self.ph_q, width=26).pack(side="left")
        ttk.Button(hb, text="Export to CSV", command=self._export_history).pack(side="right")
        frame, self.ph_tree = make_history_tree(h, height=14)
        frame.pack(fill="both", expand=True)
        self.audit_count = tk.Label(body, font=("Segoe UI", 9), bg=PANEL, fg=GREY_FG)
        return page

    def _refresh_audit(self):
        if not self.is_admin:
            self.audit_nb.pack_forget()
            self.audit_count.pack_forget()
            self.audit_locked.pack(anchor="w")
            return
        self.audit_nb.pack(fill="both", expand=True)
        self.audit_count.pack(anchor="w", pady=(4, 0))
        rev = {v: k for k, v in AUDIT_KINDS.items()}
        kind = rev.get(self.audit_kind.get())
        rows = self.db.audit_log(kind, self.audit_q.get())
        self.audit_tree.delete(*self.audit_tree.get_children())
        for r in rows:
            self.audit_tree.insert("", "end", values=(r["ts"], r["username"], AUDIT_KINDS.get(r["kind"] or "other", r["kind"]),
                                                      r["action"]), tags=(r["kind"] or "",))
        ph = self.db.price_history(search=self.ph_q.get())
        fill_history_tree(self.ph_tree, ph)
        self.audit_count.config(text=f"Showing {len(rows)} audit entries and {len(ph)} price changes (newest first, up to 2000). "
                                     "Entries can't be edited or deleted from the app.")

    def _export_audit(self):
        if not self._need_admin("export the audit log"):
            return
        self._export_rows("audit-log", ["When", "User", "Type", "What happened"],
                          [(r["ts"], r["username"], AUDIT_KINDS.get(r["kind"] or "other", r["kind"]), r["action"])
                           for r in self.db.audit_log(limit=1000000)])

    def _export_history(self):
        self._export_rows("price-history", ["When", "Item#", "Description", "Tab", "What changed", "Old", "New", "By", "How"],
                          [(r["ts"], r["item_no"], r["description"], r["category"], field_label(r["field"], r["category"]),
                            r["old_value"], r["new_value"], r["username"], r["source"])
                           for r in self.db.price_history(limit=1000000)])

    def _export_rows(self, name, header, rows):
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile=f"{name}-{datetime.date.today()}",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = security.csv_writer(f)
            w.writerow(header)
            w.writerows(rows)
        self.db.log(f"Exported {name} ({len(rows)} rows)", self.user["username"], "export")
        messagebox.showinfo("Exported", f"Saved {len(rows)} rows to\n{path}")

    def _page_backup(self):
        page, _, body = self._simple_page("Backup", "⛁")
        self._action_row(body, "Back up now", "Saves everything (products, prices, users, settings, audit log and price history) "
                         "into one .db file.\nCopy it to a USB stick or cloud folder to carry your data to another computer.",
                         [("Back up now…", self._backup_now, "Accent.TButton")])
        self._action_row(body, "Backup password", "Your data and backups are encrypted. The backup password is needed to "
                                                  "open a backup (or this data folder) on another computer.",
                         [("Set backup password…", self._set_backup_password, "TButton")])
        self.bp_status = tk.Label(body, text="", font=FONT_B, bg=PANEL, anchor="w")
        self.bp_status.pack(anchor="w", pady=(0, 4))
        self._action_row(body, "Restore from a backup", "Replaces the current data with a backup file. The file is checked first, "
                         "and a safety backup of the current data is saved.\nBackups from older versions are upgraded automatically.",
                         [("Restore from file…", self._restore, "Danger.TButton")])
        self._action_row(body, "Database health check", "Checks SQLite integrity, database version, users, target margins "
                         "and product values.", [("Run health check", self._health_check, "TButton")])
        self._action_row(body, "Data folder", f"{data_dir()}" + ("\n(portable mode)" if is_portable() else ""),
                         [("Open folder", lambda: io_utils.open_file(data_dir()), "TButton")])
        self.auto_var = tk.BooleanVar(value=self.db.get_setting("auto_backup", "1") == "1")
        tk.Checkbutton(body, text="Make an automatic backup every time the app closes", variable=self.auto_var,
                       bg=PANEL, font=FONT, activebackground=PANEL, command=self._toggle_auto).pack(anchor="w", pady=(8, 2))
        tk.Label(body, text=f"Backups in the data folder (newest {BACKUP_KEEP} kept). Made automatically when the app closes, "
                            "before every import, before every restore and before a database upgrade.",
                 font=("Segoe UI", 9), bg=PANEL, fg=GREY_FG).pack(anchor="w", pady=(6, 2))
        f = tk.Frame(body, bg=PANEL)
        f.pack(fill="both", expand=True)
        self.backup_tree = ttk.Treeview(f, columns=("name", "when", "why", "size"), show="headings", height=7)
        for k, h, w in (("name", "File", 330), ("when", "Saved", 140), ("why", "Reason", 200), ("size", "Size", 80)):
            self.backup_tree.heading(k, text=h)
            self.backup_tree.column(k, width=w, anchor="e" if k == "size" else "w", stretch=(k == "name"))
        ys = ttk.Scrollbar(f, orient="vertical", command=self.backup_tree.yview)
        self.backup_tree.configure(yscrollcommand=ys.set)
        self.backup_tree.pack(side="left", fill="both", expand=True)
        ys.pack(side="left", fill="y")
        self.backup_tree.bind("<Double-1>", lambda e: self._restore_selected())
        tk.Label(body, text="Double-click a backup to restore it.", font=("Segoe UI", 9), bg=PANEL, fg=GREY_FG).pack(anchor="w")
        return page

    def _toggle_auto(self):
        if not self._need_admin("change backup settings"):
            self.auto_var.set(self.db.get_setting("auto_backup", "1") == "1")
            return
        self.db.set_setting("auto_backup", "1" if self.auto_var.get() else "0")
        self.db.log(f"Automatic backup on close turned {'on' if self.auto_var.get() else 'off'}", self.user["username"], "settings")

    @staticmethod
    def _backup_reason(name):
        for prefix, why in (("auto-", "App closed"), ("before-import", "Before import"), ("before-restore", "Before restore"),
                            ("before-upgrade", "Before database upgrade")):
            if name.startswith(prefix):
                return why
        return "Other"

    def _refresh_backups(self):
        if hasattr(self, "bp_status"):
            has = self.db.has_backup_password()
            self.bp_status.config(text="🔒 Encrypted.  Backup password: " + ("set" if has else "NOT SET - please set one"),
                                  fg="#2e7d32" if has else "#c62828")
        self.backup_tree.delete(*self.backup_tree.get_children())
        for name, when, size in self.db.list_backups():
            self.backup_tree.insert("", "end", iid=name, values=(name, when, self._backup_reason(name), f"{size / 1024:.0f} KB"))

    def _backup_now(self):
        path = filedialog.asksaveasfilename(title="Save backup", defaultextension=".db",
                                            initialfile=f"beer-liquor-backup-{datetime.date.today()}", filetypes=[("Backup", "*.db")])
        if path:
            self.db.backup(path)
            who = getattr(self, "user", None) or {"username": "license screen"}
            self.db.log(f"Backup created: {path}", who["username"], "backup")
            messagebox.showinfo("Backup saved", f"Backup saved to\n{path}")

    def _ask_backup_password(self, msg=None):
        return simpledialog.askstring("Backup password", (f"{msg}\n\n" if msg else "") +
                                      "This backup was made on another computer.\nEnter its backup password:",
                                      show="•", parent=self)

    def _set_backup_password(self):
        if not self._need_admin("set the backup password"):
            return
        pw = ask_new_password(self, "Backup password", "", "Needed to open your backups on another computer. "
                              "Write it down - nobody can recover it.\nBackups made before this change still use "
                              "the old backup password.")
        if pw:
            self.db.set_backup_password(pw, self.user["username"])
            messagebox.showinfo("Backup password", "Backup password saved. Keep it somewhere safe.")
            self._refresh_backups()

    def _restore_selected(self):
        sel = self.backup_tree.selection()
        if sel:
            self._restore(os.path.join(backup_dir(), sel[0]))

    def _restore(self, path=None):
        if not self.is_admin:
            messagebox.showwarning("Not allowed", "Only admin users can restore backups.")
            return
        path = path or filedialog.askopenfilename(title="Choose backup", filetypes=[("Backup", "*.db"), ("All files", "*.*")])
        if not path or not messagebox.askyesno("Restore", f"Replace all current data with\n{os.path.basename(path)}?\n\n"
                                                         "A safety backup of the current data is saved first."):
            return
        user = self.user["username"]
        try:
            safety = self.db.restore(path, ask_password=self._ask_backup_password)
        except vault.NeedPassword:
            return
        except Exception as ex:
            self.db.log(f"Restore from {os.path.basename(path)} refused: {ex}", user, "backup")
            messagebox.showerror("Restore failed", str(ex))
            return
        self.db.log(f"Restored from {os.path.basename(path)} (safety backup: {os.path.basename(safety)})", user, "backup")
        for sec in self.sections.values():
            sec.reload_targets()
        self.dep_var.set(self.db.include_dep())
        self._update_footer()
        self._refresh_backups()
        self.refresh()
        messagebox.showinfo("Restored", f"Backup restored.\nYour previous data was saved as {os.path.basename(safety)}.")

    def _health_check(self):
        ok, lines = self.db.health_check()
        self.db.log(f"Health check: {'passed' if ok else 'PROBLEMS FOUND'}", self.user["username"], "maintenance")
        win = tk.Toplevel(self)
        win.title("Database health check")
        win.configure(bg=PANEL)
        win.transient(self)
        win.geometry(f"+{self.winfo_rootx() + 300}+{self.winfo_rooty() + 180}")
        tk.Label(win, text="✔  Database is healthy" if ok else "✖  Problems found", font=FONT_H, bg=PANEL,
                 fg="#2e7d32" if ok else "#c62828").pack(anchor="w", padx=16, pady=(14, 6))
        box = tk.Text(win, font=("Consolas", 10), width=95, height=16, bd=1, relief="solid", wrap="word")
        box.pack(fill="both", expand=True, padx=16)
        box.insert("end", "\n".join(lines))
        if not ok:
            box.insert("end", "\n\nWhat to do: restore the newest backup from the Backup page (double-click it).")
        box.config(state="disabled")
        ttk.Button(win, text="Close", command=win.destroy).pack(anchor="e", padx=16, pady=12)

    def _page_help(self):
        page, _, body = self._simple_page("Help / Chatbot", "💬")
        tk.Label(body, text="Works offline. Ask how to do something, or ask about your data: 'low margin', 'out of stock', 'stats', 'margin for 56334', 'price for cost 8.25 at 30%'.",
                 font=("Segoe UI", 9), bg=PANEL, fg=GREY_FG, wraplength=900, justify="left").pack(anchor="w", pady=(0, 8))
        wrap = tk.Frame(body, bg=PANEL)
        wrap.pack(fill="both", expand=True)
        self.chat = tk.Text(wrap, font=FONT, wrap="word", bd=1, relief="solid", padx=10, pady=8, state="disabled")
        sb = ttk.Scrollbar(wrap, command=self.chat.yview)
        self.chat.configure(yscrollcommand=sb.set)
        self.chat.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.chat.tag_configure("you", foreground=BLUE, font=FONT_B)
        self.chat.tag_configure("bot", foreground=NAVY, font=FONT_B)
        row = tk.Frame(body, bg=PANEL)
        row.pack(fill="x", pady=(8, 0))
        self.chat_q = tk.StringVar()
        e = ttk.Entry(row, textvariable=self.chat_q)
        e.pack(side="left", fill="x", expand=True, ipady=3)
        e.bind("<Return>", lambda ev: self._chat_send())
        ttk.Button(row, text="Send", style="Accent.TButton", command=self._chat_send).pack(side="left", padx=(6, 0))
        quick = tk.Frame(body, bg=PANEL)
        quick.pack(fill="x", pady=(6, 0))
        for q in ("How is margin calculated?", "low margin", "out of stock", "stats", "How do the Beer and Liquor tabs work?", "How do I update?"):
            ttk.Button(quick, text=q, command=lambda q=q: (self.chat_q.set(q), self._chat_send())).pack(side="left", padx=(0, 6))
        self._chat_add("Assistant", "Hi! I can explain any feature and look up your products. What do you need?")
        return page

    def _chat_add(self, who, text):
        if not hasattr(self, "chat"):
            return
        self.chat.config(state="normal")
        self.chat.insert("end", f"{who}: ", "you" if who == "You" else "bot")
        self.chat.insert("end", text + "\n\n")
        self.chat.config(state="disabled")
        self.chat.see("end")

    def _chat_send(self):
        q = self.chat_q.get().strip()
        if q:
            self._chat_add("You", q)
            self._chat_add("Assistant", self.bot.respond(q))
            self.chat_q.set("")

    def _page_about(self):
        page, _, body = self._simple_page("About", "ⓘ")
        info = (f"{APP_NAME}\nVersion {APP_VERSION}   |   Database schema v{self.db.schema_version()}\n"
                f"{CREDIT}\n\n"
                f"Your data is stored in:\n{self.db.path}\n\n"
                "Updating: run the new setup file over this version. The installer only replaces program files; "
                "your data folder is never touched. If the new version needs to change the database, it backs it up first, "
                "then upgrades it in place, keeping every product, user and setting.\n\n"
                "Tabs: Beer (Case / 12 Pk / 6 Pk) and Liquor (Case / 6 Btl / 1 Btl), each with its own target margins.\n\n"
                "Works fully offline. No internet connection is needed for any feature, including the chatbot.")
        tk.Label(body, text=info, font=FONT, bg=PANEL, justify="left", wraplength=850).pack(anchor="w")
        self._action_row(body, "Store name", "Shown in the footer and on reports.",
                         [("Change store name…", self._set_store_name, "TButton")])
        self._action_row(body, "License", "Computer ID, trial / license status, and where to enter or renew a key.",
                         [("🔑 License…", self._open_license, "Accent.TButton")])
        self._action_row(body, "Updates", "Downloads and installs the newest version (needs internet). Your data, "
                                          "license and settings are kept; a backup is made first.",
                         [("⬆ Check for updates", lambda: self._check_updates(manual=True), "Accent.TButton")])
        self._action_row(body, "Sound effects", "A buzz when a scan finds nothing, a chime when an import finishes, a "
                                                "rising tone when a price or cost goes up, a falling tone when it goes "
                                                "down, and a click when something is saved.",
                         [("🔊 Turn sounds off" if sounds.enabled() else "🔇 Turn sounds on", None, "TButton"),
                          ("▶ Test sounds", self._test_sounds, "TButton")])
        self.sound_btn = self._last_action_buttons[0]
        self.sound_btn.config(command=self._toggle_sounds)
        return page

    def _toggle_sounds(self):
        on = not sounds.enabled()
        sounds.set_enabled(on)
        self.db.set_setting("sounds", "1" if on else "0")
        self.sound_btn.config(text="🔊 Turn sounds off" if on else "🔇 Turn sounds on")
        if on:
            sounds.play("success")

    def _test_sounds(self):
        if not sounds.enabled():
            messagebox.showinfo("Sound effects", "Sounds are off. Click 'Turn sounds on' first.")
            return
        for i, name in enumerate(("error", "success", "up", "down", "saved")):
            self.after(i * 700, lambda n=name: (sounds.play(n), self._flash(f"♪ {n}")))

    # ---------- updates ----------
    def _bg(self, fn, done):
        """Run fn in the background; call done(result, error) on the main thread when finished."""
        box = {}

        def work():
            try:
                box["r"] = fn()
            except Exception as ex:                    # no internet etc.
                box["e"] = ex

        t = threading.Thread(target=work, daemon=True)
        t.start()

        def poll():
            if t.is_alive():
                self.after(300, poll)
            else:
                done(box.get("r"), box.get("e"))
        self.after(300, poll)

    def _quiet_update_check(self):
        def done(info, err):
            if info and self.winfo_exists():
                self.update_lbl.config(text=f"⬆ Update {info['text']} available - click to install")
                self.update_lbl.pack(side="right", padx=(0, 10), pady=3)
        self._bg(lambda: updater.newer_available(4), done)

    def _check_updates(self, manual=True):
        win = tk.Toplevel(self)
        win.title("Check for updates")
        win.configure(bg=PANEL)
        win.transient(self)
        win.resizable(False, False)
        lbl = tk.Label(win, text="Checking for a newer version…", font=FONT, bg=PANEL, fg=TEXT, wraplength=440,
                       justify="left")
        lbl.pack(anchor="w", padx=20, pady=(18, 8))
        bar = ttk.Progressbar(win, length=440, mode="indeterminate")
        bar.pack(padx=20, pady=(0, 10))
        bar.start(12)
        btns = tk.Frame(win, bg=PANEL)
        btns.pack(fill="x", padx=20, pady=(0, 16))
        win.geometry(f"+{self.winfo_rootx() + 400}+{self.winfo_rooty() + 220}")

        def close():
            if win.winfo_exists():
                win.destroy()

        def found(info, err):
            if not win.winfo_exists():
                return
            bar.stop()
            for w in btns.winfo_children():
                w.destroy()
            if err:
                lbl.config(text=f"Couldn't check for updates (no internet connection?).\n\n{err}")
                ttk.Button(btns, text="Close", command=close).pack(side="right")
                return
            if not info:
                lbl.config(text=f"You have the newest version ({APP_VERSION}).")
                ttk.Button(btns, text="Close", command=close).pack(side="right")
                return
            notes = info["notes"][:600] if info.get("notes") else ""
            lbl.config(text=f"Version {info['text']} is available (you have {APP_VERSION}).\n\n{notes}\n\n"
                            "Install it now? A backup is made, the app closes, and the installer starts. "
                            "Your data, license and settings are kept.")
            ttk.Button(btns, text="Later", command=close).pack(side="right")
            ttk.Button(btns, text="⬆ Install now", style="Accent.TButton",
                       command=lambda: install(info)).pack(side="right", padx=6)

        def install(info):
            for w in btns.winfo_children():
                w.destroy()
            bar.config(mode="determinate", maximum=100, value=0)
            lbl.config(text=f"Downloading {info['name']}…")
            prog = {"done": 0, "total": info.get("size") or 0}

            def tick():
                if win.winfo_exists() and prog["total"]:
                    bar.config(value=100 * prog["done"] / prog["total"])
                    if prog["done"] < prog["total"]:
                        win.after(200, tick)
            tick()

            def got(path, err):
                if not win.winfo_exists():
                    return
                if err:
                    lbl.config(text=f"Download failed: {err}\n\nYou can also download it from:\n{updater.PAGE}")
                    ttk.Button(btns, text="Close", command=close).pack(side="right")
                    return
                try:
                    self.db.safety_backup("before-update")
                    self.db.log(f"Updating to {info['text']}", getattr(self, "user", {}).get("username", "?"), "maintenance")
                    updater.run_installer(path)
                except Exception as ex:
                    lbl.config(text=f"Couldn't start the installer: {ex}\n\nThe file is at:\n{path}")
                    ttk.Button(btns, text="Close", command=close).pack(side="right")
                    return
                self.on_close()
            self._bg(lambda: updater.download(info, lambda d, t: prog.update(done=d, total=t or prog["total"])), got)

        self._bg(lambda: updater.newer_available(8), found)

    def _open_license(self):
        d = LicenseDialog(self, self.db, "manage")
        self.wait_window(d)
        self._update_footer()

    def _set_store_name(self):
        if not self._need_admin("change the store name"):
            return
        name = simpledialog.askstring("Store name", "Store name:", initialvalue=self.db.get_setting("store_name", ""), parent=self)
        if name is not None and name.strip():
            self.db.set_setting("store_name", name.strip())
            self.db.log(f"Store name set to '{name.strip()}'", self.user["username"], "settings")
            self._update_footer()

    def on_close(self):
        try:
            if self.db.get_setting("auto_backup", "1") == "1":
                self.db.auto_backup()
        finally:
            self.db.close()
            self.destroy()
