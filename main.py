"""Beverage Margin Manager - start here.  python main.py"""
import sys
import traceback


def main():
    from app.db import Database
    from app.ui import App
    try:
        db = Database()
    except Exception as ex:
        import tkinter.messagebox as mb
        mb.showerror("Can't open database", f"{ex}")
        sys.exit(1)
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
