"""SQLite storage with versioned migrations.

HOW UPDATES KEEP YOUR DATA
- The database file lives in the user data folder, not the install folder.
- Each schema change is added to MIGRATIONS with a higher number.
- On start, only migrations newer than the file's version run, and an
  automatic backup is taken first. Old rows are never dropped.
"""
import contextlib
import datetime
import os

from . import calc
from .config import db_path
from .vault import BACKUP_KEEP, VaultMixin


SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS products(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pallet TEXT DEFAULT '',
    item_no TEXT DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    category TEXT DEFAULT 'Beer',
    qty REAL DEFAULT 0,
    price REAL DEFAULT 0,
    net REAL DEFAULT 0,
    dep REAL DEFAULT 0,
    upc TEXT DEFAULT '',
    case_units INTEGER DEFAULT 24,
    case_sp REAL,
    pk12_sp REAL,
    pk6_sp REAL,
    notes TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_products_item ON products(item_no);
CREATE INDEX IF NOT EXISTS idx_products_upc ON products(upc);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL COLLATE NOCASE,
    pw TEXT NOT NULL,
    role TEXT DEFAULT 'clerk',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS activity(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, action TEXT, username TEXT
);
"""

# Append future changes here, never edit an old entry. Example:
# (2, "ALTER TABLE products ADD COLUMN supplier TEXT DEFAULT '';"),
MIGRATIONS = [
    (1, SCHEMA_V1),
    # v1.1: two tabs (Beer / Liquor). Old categories are folded into them; no rows removed.
    (2, """UPDATE products SET category='Liquor' WHERE category IN ('Liquor','Wine','Spirits');
           UPDATE products SET category='Beer' WHERE category IS NULL OR category NOT IN ('Liquor');
           CREATE INDEX IF NOT EXISTS idx_products_cat ON products(category);"""),
    # v1.2: single 24oz and 14oz can prices on the Beer tab.
    (3, """ALTER TABLE products ADD COLUMN s24_sp REAL;
           ALTER TABLE products ADD COLUMN s14_sp REAL;"""),
    # v1.3: audit log types, price history.
    (4, """ALTER TABLE activity ADD COLUMN kind TEXT DEFAULT 'other';
           UPDATE activity SET kind='product' WHERE action LIKE 'Added %' OR action LIKE 'Updated %'
                  OR action LIKE 'Deleted %' OR action LIKE '% of % -> %';
           UPDATE activity SET kind='import' WHERE action LIKE 'Imported %';
           UPDATE activity SET kind='export' WHERE action LIKE 'Exported %' OR action LIKE 'PDF:%' OR action LIKE 'Printed %';
           UPDATE activity SET kind='backup' WHERE action LIKE 'Backup %' OR action LIKE 'Restored %';
           UPDATE activity SET kind='user' WHERE action LIKE '%user %' OR action LIKE '%password%';
           UPDATE activity SET kind='login' WHERE action LIKE 'Signed %';
           CREATE INDEX IF NOT EXISTS idx_activity_kind ON activity(kind);
           CREATE TABLE IF NOT EXISTS price_history(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               ts TEXT, product_id INTEGER, item_no TEXT, description TEXT, category TEXT,
               field TEXT, old_value REAL, new_value REAL, username TEXT, source TEXT
           );
           CREATE INDEX IF NOT EXISTS idx_ph_product ON price_history(product_id);"""),
]

# fields whose changes are written to price_history
PRICE_FIELDS = ["price", "net", "dep", "case_units"] + [f"{k}_sp" for k in calc.ALL_SLOTS]
AUDIT_KINDS = {"login": "Sign-in", "security": "Security", "product": "Products", "import": "Import",
               "export": "Export / PDF", "backup": "Backup / Restore", "user": "Users",
               "settings": "Settings", "maintenance": "Health check", "other": "Other"}

PRODUCT_FIELDS = ["pallet", "item_no", "description", "category", "qty", "price",
                  "net", "dep", "upc", "case_units", "case_sp", "pk12_sp", "pk6_sp", "s24_sp", "s14_sp", "notes"]

DEFAULT_SETTINGS = {
    "target_case": "25",          # Beer targets (original v1.0 keys, kept as-is)
    "target_pk12": "25",
    "target_pk6": "30",
    "target_s24": "30",           # Single 24oz / 14oz targets (added in v1.2)
    "target_s14": "30",
    "liquor_target_case": "20",   # Liquor targets (added in v1.1)
    "liquor_target_pk12": "25",
    "liquor_target_pk6": "30",
    "include_dep": "0",
    "auto_backup": "1",
    "store_name": "My Store",
    "remember_user": "",
    "rounding": "none",           # v1.4 price rounding rule for suggested prices
    "scan_mode": "open",          # v1.4 barcode scan: open product or add to selection
    "label_size": "5163",
}

SAMPLE_PRODUCTS = [  # from the supplier ticket, so the first launch isn't empty
    dict(pallet="180816", item_no="56334", description="BOULEVARD SPACE CAMPER 4/6 CAN",
         qty=1, price=33.00, net=33.00, dep=0, upc="726959911074", case_units=24, category="Beer"),
    dict(pallet="180816", item_no="56319", description="BOULEVARD SPACE CAMPER IPA 19.2 CAN",
         qty=0, price=27.60, net=27.60, dep=0, upc="726959913023", case_units=15,
         notes="-1 Out of Stock", category="Beer"),
    dict(pallet="", item_no="L1001", description="SAMPLE VODKA 12/750ML (edit or delete me)",
         qty=1, price=180.00, net=168.00, dep=0, upc="", case_units=12, category="Liquor"),
]


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


from .security import check_pw, hash_pw, needs_rehash  # noqa: E402


def _same(a, b):
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) < 1e-9


class Database(VaultMixin):
    APP_LABEL = "Beer and Liquor Pricing"

    def __init__(self, path=None, ask_password=None):
        self.path = path or db_path()
        self.ask_password = ask_password
        self._depth = 0          # >0 while inside transaction(): commits are held back
        self._open()

    # ---------- setup ----------
    def _after_connect(self):
        self.conn.execute("PRAGMA foreign_keys=ON")

    def _migrate(self, is_new):
        c = self.conn
        c.execute("CREATE TABLE IF NOT EXISTS schema_version(version INTEGER)")
        row = c.execute("SELECT version FROM schema_version").fetchone()
        current = row[0] if row else 0
        pending = [m for m in MIGRATIONS if m[0] > current]
        if pending and current > 0:
            self.safety_backup(f"before-upgrade-v{current}")
        for version, sql in pending:
            c.executescript(sql)
            c.execute("DELETE FROM schema_version")
            c.execute("INSERT INTO schema_version VALUES (?)", (version,))
            c.commit()
        for k, v in DEFAULT_SETTINGS.items():          # new settings get defaults, old ones kept
            c.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (k, v))
        if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            c.execute("INSERT INTO users(username,pw,role,created_at) VALUES (?,?,?,?)",
                      ("admin", hash_pw("admin"), "admin", now()))
        c.commit()
        if pending and current > 0:
            self.log(f"Database upgraded from schema v{current} to v{pending[-1][0]} (backup taken first)",
                     "system", "maintenance")
        if is_new:
            for p in SAMPLE_PRODUCTS:
                self.add_product(p, "system")

    def schema_version(self):
        return self.conn.execute("SELECT version FROM schema_version").fetchone()[0]

    @staticmethod
    def latest_schema():
        return MIGRATIONS[-1][0]

    @staticmethod
    def _stamp():
        return datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]

    # ---------- transactions ----------
    def _commit(self):
        if self._depth == 0:
            self.conn.commit()

    @contextlib.contextmanager
    def transaction(self):
        """All writes inside are saved together, or none are (rolled back on any error)."""
        self.conn.commit()
        self._depth += 1
        try:
            yield
            self._depth -= 1
            if self._depth == 0:
                self.conn.commit()
        except BaseException:
            self._depth -= 1
            self.conn.rollback()
            raise

    # ---------- settings ----------
    def get_setting(self, key, default=None):
        r = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

    def set_setting(self, key, value):
        self.conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, str(value)))
        self._commit()

    @staticmethod
    def _tkey(category, k):
        return f"target_{k}" if category != "Liquor" else f"liquor_target_{k}"

    def targets(self, category="Beer"):
        return {k: float(self.get_setting(self._tkey(category, k), 25)) for k in calc.slots(category)}

    def set_target(self, category, k, value, user="admin"):
        v = calc.to_float(value)
        err = calc.validate_target(v)
        if err:
            raise ValueError(err)
        old = self.targets(category).get(k)
        self.set_setting(self._tkey(category, k), f"{v:g}")
        if old != v:
            self.log(f"{category} {calc.labels(category)[k]} target margin {old:g}% -> {v:g}%", user, "settings")

    def all_targets(self):
        return {c: self.targets(c) for c in ("Beer", "Liquor")}

    def include_dep(self):
        return self.get_setting("include_dep", "0") == "1"

    def rounding(self):
        r = self.get_setting("rounding", "none")
        return r if r in calc.ROUNDING else "none"

    # ---------- products ----------
    def list_products(self, search="", category=None):
        sql = "SELECT * FROM products WHERE 1=1"
        args = []
        if category:
            sql += " AND category=?"
            args.append(category)
        if search:
            like = f"%{search.strip()}%"
            sql += " AND (description LIKE ? OR item_no LIKE ? OR upc LIKE ? OR pallet LIKE ?)"
            args += [like] * 4
        sql += " ORDER BY description COLLATE NOCASE"
        return [dict(r) for r in self.conn.execute(sql, args)]

    def get_product(self, pid):
        r = self.conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        return dict(r) if r else None

    def find_by_item(self, item_no):
        r = self.conn.execute("SELECT * FROM products WHERE item_no=?", (str(item_no),)).fetchone()
        return dict(r) if r else None

    @staticmethod
    def upc_key(code):
        digits = "".join(ch for ch in str(code or "") if ch.isdigit())
        return digits.lstrip("0")

    def find_by_upc(self, code):
        """Matches a scanned code to a product. Handles leading zeros (UPC-A vs EAN-13) and
        UPCs saved with or without the last check digit. Falls back to an exact Item# match."""
        key = self.upc_key(code)
        if not key:
            return None
        rows = [dict(r) for r in self.conn.execute("SELECT * FROM products WHERE upc IS NOT NULL AND upc != ''")]
        for test in (lambda k: k == key, lambda k: k == key[:-1], lambda k: k[:-1] == key):
            for r in rows:
                k = self.upc_key(r["upc"])
                if k and test(k):
                    return r
        return self.find_by_item(str(code).strip())

    def products_with_changes(self, since, fields=None, category=None):
        """Product ids whose given fields (default: selling prices) changed at or after `since`."""
        fields = fields or [f"{k}_sp" for k in calc.ALL_SLOTS]
        q = ("SELECT DISTINCT product_id FROM price_history WHERE ts >= ? AND field IN (%s)" % ",".join("?" * len(fields)))
        ids = [r[0] for r in self.conn.execute(q, [since] + fields)]
        out = [p for p in (self.get_product(i) for i in ids) if p]
        return [p for p in out if not category or p["category"] == category]

    def cost_history(self, since, source=None):
        """Net/Dep/Case size changes since a time, oldest value first per product."""
        q = "SELECT * FROM price_history WHERE ts >= ? AND field IN ('net','dep','case_units')"
        args = [since]
        if source:
            q += " AND source = ?"
            args.append(source)
        return [dict(r) for r in self.conn.execute(q + " ORDER BY id", args)]

    def _clean(self, data):
        d = {k: data.get(k) for k in PRODUCT_FIELDS if k in data}
        if "category" in d and d["category"] not in ("Beer", "Liquor"):
            d["category"] = "Liquor" if str(d["category"]).lower() in ("liquor", "wine", "spirits") else "Beer"
        return d

    def add_product(self, data, user="admin", log=True):
        d = self._clean(data)
        d["created_at"] = d["updated_at"] = now()
        cols = ",".join(d)
        cur = self.conn.execute(f"INSERT INTO products({cols}) VALUES ({','.join('?' * len(d))})",
                                list(d.values()))
        self._commit()
        if log:
            self.log(f"Added {d.get('description', '')} ({d.get('category') or 'Beer'})", user, "product")
        return cur.lastrowid

    def update_product(self, pid, data, user="admin", log=True, source="edit"):
        """Updates a product and writes every price change (old -> new) to price_history."""
        d = self._clean(data)
        old = self.get_product(pid)
        if not d or not old:
            return []
        d["updated_at"] = now()
        sets = ",".join(f"{k}=?" for k in d)
        self.conn.execute(f"UPDATE products SET {sets} WHERE id=?", list(d.values()) + [pid])
        changes = []
        for f in PRICE_FIELDS:
            if f in d and not _same(old.get(f), d[f]):
                changes.append((f, old.get(f), d[f]))
                self.conn.execute(
                    "INSERT INTO price_history(ts,product_id,item_no,description,category,field,old_value,new_value,username,source)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (now(), pid, old.get("item_no"), d.get("description", old.get("description")),
                     d.get("category", old.get("category")), f, old.get(f), d[f], user, source))
        self._commit()
        if log:
            self.log(f"Updated {d.get('description', old.get('description', ''))} "
                     f"({d.get('category', old.get('category', ''))})"
                     + (f": {len(changes)} price change(s)" if changes else ""), user, "product")
        return changes

    def delete_products(self, ids, user="admin"):
        with self.transaction():
            for pid in ids:
                p = self.get_product(pid)
                self.conn.execute("DELETE FROM products WHERE id=?", (pid,))
                if p:
                    self.log(f"Deleted {p['description']} ({p['category']}), Item# {p['item_no'] or '-'}", user, "product")

    def price_history(self, product_id=None, search="", limit=2000):
        sql, args = "SELECT * FROM price_history WHERE 1=1", []
        if product_id is not None:
            sql += " AND product_id=?"
            args.append(product_id)
        if search:
            like = f"%{search.strip()}%"
            sql += " AND (description LIKE ? OR item_no LIKE ? OR username LIKE ?)"
            args += [like] * 3
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.conn.execute(sql, args)]

    # ---------- audit log ----------
    def log(self, action, user="admin", kind="other"):
        self.conn.execute("INSERT INTO activity(ts,action,username,kind) VALUES (?,?,?,?)", (now(), action, user, kind))
        self._commit()

    def recent_activity(self, n=8):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM activity ORDER BY id DESC LIMIT ?", (n,))]

    def audit_log(self, kind=None, search="", limit=2000):
        sql, args = "SELECT * FROM activity WHERE 1=1", []
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        if search:
            like = f"%{search.strip()}%"
            sql += " AND (action LIKE ? OR username LIKE ?)"
            args += [like, like]
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.conn.execute(sql, args)]

    # ---------- users ----------
    def list_users(self):
        return [dict(r) for r in self.conn.execute("SELECT id,username,role,created_at FROM users ORDER BY username")]

    def verify_user(self, username, password):
        r = self.conn.execute("SELECT * FROM users WHERE username=?", ((username or "").strip(),)).fetchone()
        if not r:
            check_pw(password, hash_pw("x"))         # same time taken whether or not the user exists
            return None
        if not check_pw(password, r["pw"]):
            return None
        if needs_rehash(r["pw"]):                     # upgrade older password storage on the next good sign-in
            self.conn.execute("UPDATE users SET pw=? WHERE id=?", (hash_pw(password), r["id"]))
            self._commit()
        u = dict(r)
        u.pop("pw", None)
        return u

    def add_user(self, username, password, role="clerk"):
        self.conn.execute("INSERT INTO users(username,pw,role,created_at) VALUES (?,?,?,?)",
                          (username.strip(), hash_pw(password), role, now()))
        self._commit()

    def set_password(self, username, password):
        self.conn.execute("UPDATE users SET pw=? WHERE username=?", (hash_pw(password), username))
        self._commit()

    def delete_user(self, uid):
        admins = self.conn.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]
        r = self.conn.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
        if r and r["role"] == "admin" and admins <= 1:
            raise ValueError("You can't delete the last admin account.")
        self.conn.execute("DELETE FROM users WHERE id=?", (uid,))
        self._commit()

    # ---------- health check ----------
    def health_check(self):
        """Returns (ok, [lines]). Problems start with 'PROBLEM', notes with 'Note'."""
        lines, ok = [], True
        res = [r[0] for r in self.conn.execute("PRAGMA integrity_check")]
        if res == ["ok"]:
            lines.append("SQLite integrity check: passed")
        else:
            ok = False
            lines.append("PROBLEM: SQLite integrity check failed: " + "; ".join(res[:5]))
        fk = self.conn.execute("PRAGMA foreign_key_check").fetchall()
        lines.append("Foreign key check: passed" if not fk else f"PROBLEM: {len(fk)} foreign key error(s)")
        ok = ok and not fk
        v, latest = self.schema_version(), self.latest_schema()
        if v == latest:
            lines.append(f"Database version: v{v} (up to date)")
        else:
            ok = False
            lines.append(f"PROBLEM: database version v{v}, expected v{latest}")
        for t in ("products", "settings", "users", "activity", "price_history"):
            if not self.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone():
                ok = False
                lines.append(f"PROBLEM: table '{t}' is missing")
        prods = self.list_products()
        bad = []
        for p in prods:
            errs, _ = calc.validate_product(p)
            if errs:
                bad.append(f"{p['item_no'] or '-'} {p['description']}: {errs[0]}")
        lines.append(f"Products: {len(prods)} ({sum(p['category'] == 'Beer' for p in prods)} beer, "
                     f"{sum(p['category'] == 'Liquor' for p in prods)} liquor)")
        if bad:
            lines.append(f"Note: {len(bad)} product(s) have invalid values, fix them with Edit:")
            lines += [f"    {b}" for b in bad[:10]]
        for cat in ("Beer", "Liquor"):
            for k, t in self.targets(cat).items():
                if calc.validate_target(t):
                    ok = False
                    lines.append(f"PROBLEM: {cat} {k} target margin {t} is invalid")
        admins = self.conn.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]
        lines.append(f"Users: {len(self.list_users())} ({admins} admin)" if admins else "PROBLEM: no admin user")
        ok = ok and admins > 0
        lines.append(f"Audit log entries: {self.conn.execute('SELECT COUNT(*) FROM activity').fetchone()[0]},  "
                     f"price changes recorded: {self.conn.execute('SELECT COUNT(*) FROM price_history').fetchone()[0]}")
        backups = self.list_backups()
        if backups:
            lines.append(f"Backups: {len(backups)} kept (max {BACKUP_KEEP}), newest {backups[0][1]}")
        else:
            lines.append("Note: no backups yet. Use Back up now, or close the app once to make one.")
        enc = self.encryption_lines()
        ok = ok and not any(x.startswith("PROBLEM") for x in enc)
        lines += enc
        lines.append(f"Database file: {self.path} ({os.path.getsize(self.path) / 1024:.0f} KB)")
        return ok, lines

    def close(self):
        self.conn.close()
