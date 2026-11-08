# Beer and Liquor Pricing - Version 1.5.3

- Import supplier invoice PDFs with Import: Southern Glazer's (to Liquor - item, size, cases, price, net, UPC, bottles
  per case) and Wil Fischer (to Beer - item, cases, price, net after discount, deposit, cans per case). Every line is
  checked against the invoice's printed totals before anything is saved.
- Sound effects: buzz when a scan finds nothing or something fails, chime when an import finishes, rising tone when a
  price or cost goes up, falling tone when it goes down, click when something is saved. On/off and Test on About.

## Version 1.5.2 (data protection update)

- Your data file and backups are now encrypted (AES-256). The key is locked to your Windows user, so nothing
  extra to type each day, and a copied or stolen data file can't be read.
- New BACKUP PASSWORD (asked once, at the next admin sign-in): needed to open backups or this data folder on
  another computer. Write it down - nobody can recover it.
- Your existing data and backups are encrypted automatically the first time this version opens. Old backup
  files on a USB stick can still be restored.
- The program is now compiled to machine code, which makes it much harder to take apart.
- Backups made in the same instant no longer overwrite each other.

## Version 1.5.1 (security update)

- Stronger password protection. Passwords must be at least 8 characters; the default admin/admin must be changed at first sign-in.
- After 5 wrong passwords, sign-in pauses for 1 minute (longer if it keeps happening).
- Changing your own password asks for your current one. Only admins can change pricing rules, store name, users and backup settings.
- Safer imports, restores and exports (oversized or fake files refused; spreadsheet formulas can't sneak in through product names).
- Updates are only downloaded from GitHub and must pass a fingerprint check.

## Version 1.5.0

- License key and 14-day free trial (About > License). One key per computer, valid for one year.
  Your data is never deleted when a trial or license ends.
- Check for updates (About > Check for updates, or the yellow link in the footer): downloads and installs
  the newest version. A backup is made first; data, license and settings are kept.
- "Developed by Robin Mishra - Copyright 2026" on the About page, footer and license screen.
