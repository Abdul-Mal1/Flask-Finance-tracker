# Flask Finance Tracker

A Flask-based personal finance tracker with:

- Income & expense logging
- Custom categories + sub-categories
- Date range + type + category + search filters
- Dashboard totals (income / expenses / net)
- Charts (monthly cashflow + expense breakdown)
- Monthly budgets per category (warnings + over-budget alerts)
- CSV export (respects current filters)
- Dark mode toggle (client-side)

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then open the URL shown in your terminal.

## Notes about the included database

This project ships with an example SQLite database at `instance/finance.db`.

If you already have an older `finance.db`, the app includes a small SQLite schema upgrader that **adds missing columns/tables automatically** on startup.
If you ever see unexpected DB errors after big changes, the simplest fix is to back up and delete the old DB file and let the app recreate it.
