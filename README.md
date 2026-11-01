# Beer and Liquor Pricing (v1.4.0)

Offline desktop app for tracking supplier-ticket items (Item#, Description, Qty,
Price, Net, Dep, Ext, U.P.C.) and the margins on your selling prices.
Two tabs, each with its own target margins:

| Tab | Selling prices | Default case size |
|---|---|---|
| Beer | Case, 12 Pk, 6 Pk, Single 24oz, Single 14oz | 24 cans ("4/6", "2/12" = 24; "12/24OZ" = 12) |
| Liquor | Case, 6 Btl, 1 Btl | 12 bottles ("12/750ML", "6/1.75L" auto-detected) |

Runs with or without internet. Data is kept in one local SQLite file.

## Columns
| From the supplier ticket | Added |
|---|---|
| Pallet, Item#, Description, Qty, Price, Net, Dep, Ext, U.P.C. | Case Size, Case S.P., 12 Pk S.P., 6 Pk S.P., Case Margin %, 12 Pk Margin %, 6 Pk Margin % |

## How margins are calculated
- Case cost = Net (tick "Deposit in cost" to add Dep)
- Beer: Case = one complete box (cost = Net)
- Beer: 12 Pk cost = Net × 12 ÷ Case Size (a 2/12 case → Net ÷ 2)
- Beer: 6 Pk cost = Net × 6 ÷ Case Size (a 4/6 case → Net ÷ 4)
- Beer: Single 24oz / Single 14oz cost = Net ÷ cans in the case
  (e.g. $36.00 for 12 × 24oz → $3.00 a can; sell at $3.99 → 24.8%)
- Liquor: 6 Btl cost = Net × 6 ÷ Case Size, 1 Btl cost = Net ÷ Case Size
- Margin % = (Selling Price − Cost) ÷ Selling Price × 100
- Suggested price = Cost ÷ (1 − Target %)
- Ext = Qty × (Net + Dep)

Example: Net $33.00, 4/6 CAN (24 cans) → 6 pk cost $8.25. Sell at $10.99 → 24.9% margin.
Example: Net $168.00, 12/750ML → bottle cost $14.00. Sell at $19.99 → 30.0% margin.

To change the liquor pack sizes (for example 3 Btl instead of 6 Btl), edit `PROFILES`
in `app/calc.py`.

## Build the setup file (on a Windows PC, one time)
1. Install Python 3.10+ from python.org (tick "Add python.exe to PATH").
2. Install Inno Setup 6 from jrsoftware.org/isinfo.php.
3. Double-click `build.bat`.
4. You get `Output\BevMargin-Setup-1.0.0.exe` (installer) and
   `Output\BevMargin-Portable.zip` (no install, runs from a USB stick).
   The file name shows the version, e.g. `BevMargin-Setup-1.1.0.exe`.

The setup file works on any Windows 10/11 PC; those PCs do not need Python.
To run from source on any OS: `pip install reportlab openpyxl` then `python main.py`.

First login: **admin / admin** (you'll be asked to change it).

## Time-savers (v1.4)
- **Barcode scanning**: click the Scan box (or F2) and scan with any USB scanner. Mode *Open* opens the
  product to edit; mode *Select* adds it to the selection so you can scan a shelf, then click Labels or Bulk
  Update. Unknown UPCs offer to add a new product with the UPC filled in. Leading zeros and missing check
  digits are matched; an Item# also works.
- **Shelf labels**: Labels button (Ctrl+L). Avery 5163 large (10/sheet, all prices + barcode) or Avery 5160
  small (30/sheet). Print selected/scanned products, everything whose price changed since a date, or a whole
  tab. "Start at label #" uses up partly used sheets. "Draw outlines" for a plain-paper test print.
- **Bulk update**: Bulk Update button (Ctrl+B). Change by %, by $, to target margin, to a margin you type, or
  an exact price, for any of the price columns. Preview old vs new before saving; backup first; recorded in
  Price History. Offers to print labels afterwards.
- **Rounding rules**: ⚙ Pricing. None, next price ending in 9, .49/.99, or .99. Always rounds up, so the
  margin never drops below target. Used for suggested prices, bulk updates and cost alerts.
- **Cost-change alerts**: after an import changes Net costs, a window lists every affected price with old vs
  new margin. Red rows are below target, with a suggested price; apply them in one click (prices that are
  still OK are never lowered), then print labels. Also under Reports > Cost changes for any number of days.
- **Shortcuts** (Home screen): F2 scan, Ctrl+F search, Ctrl+N new, Ctrl+E edit, Ctrl+B bulk update,
  Ctrl+L labels, Ctrl+P print, F5 refresh, Delete to delete.

## Safety and record-keeping (v1.3)
- **Audit Log** (sidebar, admins): sign-ins, failed sign-ins, sign-outs, product changes, imports,
  exports/PDF/print, backups, restores, health checks, user admin and settings changes.
  Filter, search, export to CSV. Entries can't be edited or deleted in the app.
- **Price History**: every change to Price, Net, Dep, Case Size or any selling price is saved as
  old → new, with who, when and how (edit window, table edit, or which import file).
  See Audit Log > Price History, or Edit a product > Price history.
- **Automatic backups**: when the app closes, before every import, before every restore and before a
  database upgrade. The newest 30 are kept (Backup page lists them; double-click to restore).
- **Health check**: Backup > Run health check (SQLite integrity, version, tables, users, targets,
  product values). A quick integrity check also runs at every start.
- **Validation**: no negative Qty/Price/Net/Dep, selling prices must be above 0, case size must be a whole
  number 1-500, target margins 0 to under 100%. Selling below cost asks you to confirm.
- **Safer import**: every row is checked and a report shows each problem with its row number; rows with
  errors are skipped. Then a backup is made and all rows are saved in one transaction: if anything fails,
  nothing is changed.
- **Restore** checks the backup file's integrity first and refuses a damaged file.
- **Remember me** on the sign-in window remembers the username only (passwords are never stored).

## Where data lives
- Installed: `%APPDATA%\BevMargin\bevmargin.db` (+ `backups\`)
- Portable: `data\` folder next to the exe
Move data to another PC: Backup > Back up now, then on the new PC Backup > Restore.

## Releasing an update without losing data
1. Change `APP_VERSION` in `app/config.py` and `MyAppVersion` in `installer.iss`.
2. If you need a new database column, ADD a new entry at the end of `MIGRATIONS`
   in `app/db.py`, e.g. `(2, "ALTER TABLE products ADD COLUMN supplier TEXT DEFAULT '';")`.
   Never edit or remove an old entry.
3. Run `build.bat` and install the new setup over the old one.

Why it's safe: the installer only replaces program files (same AppId = upgrade);
the database is in a separate folder the installer never touches; before a schema
upgrade the app copies the database to `backups\before-upgrade-...db`; uninstalling
also leaves the data folder in place.

## Artwork
The banner (beer glasses, liquor bottles, bar background) and logo are original
illustrations drawn by `tools/make_art.py`, so no photo licensing is needed.
Run `python tools/make_art.py` to regenerate them. To use your own photo instead,
replace `assets/banner_bg.png` (about 2600×200) and `banner_bg_sm.png` (about 1870×144).
Change the footer store name in About > Change store name.

## Project layout
```
main.py            start the app
app/config.py      version + data paths
app/db.py          SQLite, migrations, users, backup/restore
app/calc.py        all margin math
app/chatbot.py     offline help assistant
app/io_utils.py    CSV/Excel import-export, PDF reports, print
app/pricing.py     bulk price updates and cost-change alerts
app/labels.py      Avery shelf labels with barcodes
app/ui.py          window, banner, Beer/Liquor tabs, pages and dialogs
tools/make_art.py  draws the banner images and logo
tests/test_core.py run: python tests/test_core.py
build.bat          builds exe + setup + portable zip
installer.iss      Inno Setup script
```
