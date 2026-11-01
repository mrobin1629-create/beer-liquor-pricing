"""License window: shows the Computer ID, trial / expiry status, and takes a license key."""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import license as lic
from .config import APP_NAME, CREDIT, DEVELOPER
from .config import resource_path

NAVY, PANEL, TEXT, GREY_FG, RED, GREEN = "#0d2f57", "#ffffff", "#1d2733", "#8a8f98", "#c62828", "#2e7d32"
FONT, FONT_B, FONT_H = ("Segoe UI", 10), ("Segoe UI", 10, "bold"), ("Segoe UI", 13, "bold")


def load_image(name):
    try:
        return tk.PhotoImage(file=resource_path("assets", name))
    except Exception:
        return None

CONTACT = DEVELOPER          # add a phone number or email here if customers should see one


class LicenseDialog(tk.Toplevel):
    """mode 'start': shown at start-up when a key is needed or the trial/license is ending.
    mode 'manage': opened from About. self.ok = True when the app may open."""

    def __init__(self, master, db, mode="start", backup_cb=None):
        super().__init__(master)
        self.db, self.mode, self.backup_cb, self.ok = db, mode, backup_cb, False
        self.title(f"{APP_NAME} - License")
        self.configure(bg=PANEL)
        self.resizable(False, False)
        self.logo = load_image("logo.png")
        top = tk.Frame(self, bg=PANEL)
        top.pack(fill="x", padx=22, pady=(16, 6))
        if self.logo:
            self._small = self.logo.subsample(2)
            tk.Label(top, image=self._small, bg=PANEL).pack(side="left")
        tk.Label(top, text=APP_NAME, font=("Segoe UI", 14, "bold"), bg=PANEL, fg=NAVY).pack(side="left", padx=10)
        self.status_lbl = tk.Label(self, font=FONT_H, bg=PANEL, justify="left", wraplength=560)
        self.status_lbl.pack(anchor="w", padx=22)
        self.help_lbl = tk.Label(self, font=FONT, bg=PANEL, fg=TEXT, justify="left", wraplength=560)
        self.help_lbl.pack(anchor="w", padx=22, pady=(4, 10))

        idf = tk.Frame(self, bg="#eef3f9", highlightbackground="#c9d3df", highlightthickness=1)
        idf.pack(fill="x", padx=22, pady=(0, 10))
        tk.Label(idf, text="Your Computer ID", font=FONT_B, bg="#eef3f9", fg=NAVY).pack(anchor="w", padx=12, pady=(8, 0))
        row = tk.Frame(idf, bg="#eef3f9")
        row.pack(fill="x", padx=12, pady=(2, 10))
        self.cid = lic.computer_id()
        e = tk.Entry(row, font=("Consolas", 16, "bold"), width=22, relief="flat", justify="center", fg=NAVY)
        e.insert(0, self.cid)
        e.config(state="readonly")
        e.pack(side="left")
        ttk.Button(row, text="📋 Copy", command=self.copy_id).pack(side="left", padx=8)
        ttk.Button(row, text="✉ Copy request message", command=self.copy_request).pack(side="left")

        tk.Label(self, text="License key", font=FONT_B, bg=PANEL).pack(anchor="w", padx=22)
        self.key = tk.Text(self, height=4, width=64, font=("Consolas", 10), wrap="char", bd=1, relief="solid")
        self.key.pack(fill="x", padx=22, pady=(2, 4))
        self.key.focus_set()
        self.msg = tk.Label(self, text="", font=FONT, bg=PANEL, fg=RED, wraplength=560, justify="left")
        self.msg.pack(anchor="w", padx=22)
        bar = tk.Frame(self, bg=PANEL)
        bar.pack(fill="x", padx=22, pady=12)
        ttk.Button(bar, text="Activate", style="Accent.TButton", command=self.activate).pack(side="left")
        ttk.Button(bar, text="Open key file…", command=self.open_file).pack(side="left", padx=6)
        self.cont_btn = ttk.Button(bar, text="Continue", command=self.cont)
        self.cont_btn.pack(side="right")
        if backup_cb:
            ttk.Button(bar, text="⛁ Back up my data", command=backup_cb).pack(side="right", padx=6)
        tk.Label(self, text=f"License questions: {CONTACT}\n{CREDIT}", font=("Segoe UI", 8), bg=PANEL,
                 fg=GREY_FG, justify="left").pack(anchor="w", padx=22, pady=(0, 14))
        self.protocol("WM_DELETE_WINDOW", self.cont if mode == "manage" else self.quit_app)
        self.refresh()
        self.update_idletasks()
        x = (self.winfo_screenwidth() - self.winfo_width()) // 2
        y = (self.winfo_screenheight() - self.winfo_height()) // 3
        self.geometry(f"+{x}+{y}")
        self.grab_set()

    def refresh(self):
        st = self.st = lic.status(self.db)
        good = lic.can_use(st)
        self.status_lbl.config(text=lic.describe(st), fg=GREEN if st["state"] == "licensed" else
                               ("#b05a00" if good else RED))
        if st["state"] in ("licensed",):
            help_ = "This copy is activated. To renew next year, paste the new key below."
        elif st["state"] == "expiring":
            help_ = (f"Your license ends in {st['days_left']} day(s). Send your Computer ID to get a renewal key and paste it "
                     "below. Your data is kept.")
        elif st["state"] == "trial":
            help_ = ("You can use every feature during the trial. To keep using the app afterwards, send the Computer ID "
                     "below to get a license key (one key per computer, valid for one year).")
        elif st["state"] == "wrong_pc":
            help_ = "Keys work on one computer. Send this computer's ID to get a key for it."
        else:
            help_ = ("Send the Computer ID below to get a license key, then paste it here. Your data is safe and kept; "
                     "you can still back it up.")
        if st.get("key_error"):
            help_ += "\n(The saved key could not be read.)"
        self.help_lbl.config(text=help_)
        self.cont_btn.config(text="Close" if self.mode == "manage" else ("Continue" if good else "Exit"),
                             command=self.cont if (good or self.mode == "manage") else self.quit_app)

    def copy_id(self):
        self.clipboard_clear()
        self.clipboard_append(self.cid)
        self.msg.config(text="Computer ID copied.", fg=GREEN)

    def copy_request(self):
        store = self.db.get_setting("store_name", "") or "my store"
        self.clipboard_clear()
        self.clipboard_append(f"Hello,\n\nPlease send me a license key for {APP_NAME}.\n\nStore: {store}\n"
                              f"Computer ID: {self.cid}\n\nThank you.")
        self.msg.config(text=f"Request message copied - paste it into an email or text to {DEVELOPER}.", fg=GREEN)

    def open_file(self):
        path = filedialog.askopenfilename(parent=self, title="Open license key file",
                                          filetypes=[("License key", "*.lic *.txt"), ("All files", "*.*")])
        if path:
            with open(path, encoding="utf-8", errors="ignore") as f:
                self.key.delete("1.0", "end")
                self.key.insert("1.0", f.read().strip())
            self.activate()

    def activate(self):
        text = self.key.get("1.0", "end").strip()
        if not text:
            self.msg.config(text="Paste the license key first.", fg=RED)
            return
        try:
            k = lic.activate(self.db, text)
        except ValueError as ex:
            self.msg.config(text=str(ex), fg=RED)
            return
        except Exception as ex:                       # e.g. a damaged install
            self.msg.config(text=f"Couldn't check the key: {ex}", fg=RED)
            return
        self.db.log(f"License activated for {k['customer']} until {k['expires']} (serial {k['serial']})", "system", "security")
        self.key.delete("1.0", "end")
        self.refresh()
        self.msg.config(text=f"✔ Activated for {k['customer']} until {k['expires']:%b %d, %Y}. Thank you!", fg=GREEN)
        if self.mode == "start":
            self.after(900, self.cont)

    def cont(self):
        self.ok = lic.can_use(lic.status(self.db))
        self.destroy()

    def quit_app(self):
        self.ok = False
        self.destroy()


def startup_gate(master, db, backup_cb=None):
    """True if the app may open. Shows the license window when needed (trial reminder, expiring soon, or no
    valid license)."""
    try:
        st = lic.status(db)
    except Exception as ex:                           # never lock someone out because of an unexpected error
        messagebox.showwarning("License", f"The license couldn't be checked ({ex}). The app will open.")
        return True
    if st["state"] == "licensed":
        return True
    remind = st["state"] == "trial" and (db.get_setting("lic_last_reminder", "") != str(st["today"]))
    if st["state"] == "trial" and not remind:
        return True
    if st["state"] == "trial":
        db.set_setting("lic_last_reminder", str(st["today"]))
    if st["state"] == "expiring" and db.get_setting("lic_last_reminder", "") == str(st["today"]):
        return True
    if st["state"] == "expiring":
        db.set_setting("lic_last_reminder", str(st["today"]))
    d = LicenseDialog(master, db, "start", backup_cb)
    master.wait_window(d)
    return d.ok
