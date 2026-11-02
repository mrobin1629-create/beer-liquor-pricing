# Beer and Liquor Pricing - Version 1.5.1 (security update)

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
