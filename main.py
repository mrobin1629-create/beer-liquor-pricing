"""Beverage Margin Manager - start here.  python main.py"""
import sys
import traceback


def main():
    if "--selftest" in sys.argv:                 # used by the GitHub build to check the finished program
        from app.selftest import run
        i = sys.argv.index("--selftest")
        sys.exit(run(sys.argv[i + 1] if len(sys.argv) > i + 1 else "selftest.json"))
    from app.db import Database
    from app.ui import App
    from app.vault import NeedPassword

    def ask_password(msg=None):
        """Data moved from another computer / Windows account: unlock it once with the backup password."""
        import tkinter as tk
        from tkinter import simpledialog
        root = tk.Tk()
        root.withdraw()
        try:
            return simpledialog.askstring(
                "Unlock your data", (f"{msg}\n\n" if msg else "") +
                "This data folder was copied from another computer or Windows account.\n"
                "Enter the store's BACKUP PASSWORD to unlock it on this computer:", show="•", parent=root)
        finally:
            root.destroy()

    try:
        db = Database(ask_password=ask_password)
    except NeedPassword:
        sys.exit(0)
    except Exception as ex:
        import tkinter.messagebox as mb
        mb.showerror("Can't open database", f"{ex}")
        sys.exit(1)
    if getattr(db, "locked_aside", None):
        import tkinter.messagebox as mb
        mb.showwarning("Data key missing", "The data file's key file was missing, so the old data file couldn't be "
                       f"opened. It was kept as:\n{db.locked_aside}\n\nA new empty data file was started. Sign in and "
                       "use Backup > Restore from file to load your newest backup.")
    while True:                       # loop so Logout returns to the sign-in window
        app = App(db)
        if not app.alive:
            break
        app.mainloop()
        if not getattr(app, "logged_out", False):
            break


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        try:
            import tkinter.messagebox as mb
            mb.showerror("Unexpected error", traceback.format_exc()[-1500:])
        except Exception:
            pass
