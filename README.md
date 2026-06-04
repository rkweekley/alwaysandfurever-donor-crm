# Always & Furever — Donor Database / CRM

A central donor database and reporting tool for **Always & Furever Animal Rescue**
(<https://www.alwaysandfurever.org>).

The goal: combine donations from every source — Stripe, PayPal, Zeffy, Facebook,
checks, cash, in-kind gifts, wishlists, sponsorships, events, auctions, matching
gifts, recurring and tribute gifts — into **one clean donor profile** with solid
reporting, search, and deduplication.

> **Status:** Running Phase 1 app. A Flask web application with authentication,
> donor/donation management, reporting, a live CSV import workflow (upload →
> review → commit/rollback), and a modern CRM UI — hardened for public web
> hosting. The design docs below remain the blueprint.

---

## Quick install on a VPS

One command on a fresh Ubuntu/Debian/Fedora/Alpine server. It installs
dependencies, then walks you through setup (admin account, domain, port, and
whether to load demo data or start with a clean production database):

```bash
curl -fsSL https://raw.githubusercontent.com/rkweekley/alwaysandfurever-donor-crm/main/install.sh | bash
```

The installer will:

1. Install system packages (python3, venv, git) for your OS
2. Clone the repo (default `/opt/alwaysandfurever-crm`)
3. Create a virtualenv and install Python dependencies
4. **Walk you through setup** — admin username/password, display name/email,
   domain, app port, gunicorn workers, HTTPS/proxy mode, and demo-vs-real data
5. Generate a strong `SECRET_KEY` and write a locked-down `.env`
6. Initialize the database — either a **clean production DB** (schema + lookups +
   your one admin account, no donors) or **demo data** (10 fake donors to explore)
7. Optionally install a **systemd service** (gunicorn on boot) and a **Caddy**
   site for automatic HTTPS

Re-running is safe: it never overwrites an existing database unless you explicitly
confirm a rebuild.

### Manual install

Prefer to do it by hand? See [`DEPLOY.md`](DEPLOY.md). In short:

```bash
git clone https://github.com/rkweekley/alwaysandfurever-donor-crm.git
cd alwaysandfurever-donor-crm
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"   # paste into SECRET_KEY

# Clean production database (recommended) — creates ONE real admin, no demo data:
ADMIN_USERNAME=you ADMIN_PASSWORD='choose-a-strong-one' python scripts/init_db.py
#   ...or load demo data instead to explore the UI first:
# python seed_demo.py

set -a; . ./.env; set +a
gunicorn -w 3 -b 127.0.0.1:8000 app:app   # put nginx/Caddy in front for HTTPS
```

`scripts/init_db.py` writes only what a real deployment needs — schema, lookup
tables, and your admin account — and refuses to clobber an existing database
unless you pass `--force`.

---

## What's in here

| Path | What it is |
|------|------------|
| `docs/REQUIREMENTS.md` | Full feature spec (the brief, organized and tracked) |
| `docs/DATA_MODEL.md` | Plain-English walkthrough of every table and field |
| `docs/IMPORT_WORKFLOW.md` | Step-by-step the import/match/review pipeline |
| `docs/REPORTS.md` | Every report we need, with the query intent behind it |
| `docs/column-mappings/` | One mapping template per platform (Stripe, PayPal, Zeffy, GiveWP, Facebook, offline) |
| `db/schema.sql` | The full SQLite/Postgres-compatible schema |
| `db/seed_lookups.sql` | Lookup values (sources, payment methods, funds, note types) |
| `importer.py` | The import engine — parses CSVs, maps columns, matches donors, stages batches |
| `samples/` | Sanitized sample export files for testing mappings |
| `reports/` | Saved report definitions / SQL (Phase 1+) |

---

## Core structure at a glance

- **donors** — one master profile per donor (person, household, or organization)
- **donations** — every gift stored as its own transaction record
- **donor_notes** — activity log / notes with follow-up tracking
- **import_batches** — every upload tracked so an import can be reviewed or rolled back
- **duplicate_candidates** — flagged possible-duplicate pairs awaiting human review
- Lookup tables: **sources**, **payment_methods**, **funds**, **campaigns**, **tribute_types**

See `docs/DATA_MODEL.md` for the full field-by-field breakdown.

---

## User roles & access

Every account has one of three roles. Enforcement is **server-side** (route
decorators) — hiding a nav link is never the only thing standing between a user
and an action.

| Role | Can view | Can add/edit donors, donations, notes, imports | Can manage users |
|------|----------|-----------------------------------------------|------------------|
| **admin** | ✔ | ✔ | ✔ |
| **staff** | ✔ | ✔ | — |
| **readonly** | ✔ | — | — |

- **admin** — full access plus user management (`/users`): add accounts, assign
  roles, deactivate people who leave.
- **staff** — full day-to-day CRM work, but no access to user management.
- **readonly** — view and run reports only; every mutating request is rejected
  (HTTP 403), not just hidden.

Guardrails: you can't deactivate your own account, and you can't deactivate the
last active admin (so a deployment can never lock itself out). User management
lives under **Admin → Users** in the sidebar, visible to admins only.

The first admin is created by the installer (or `scripts/init_db.py`). Add the
rest from the Users page.

---

## Importing your data

Bring gifts in from any platform under **Import** in the sidebar. The flow never
writes straight to your live data — every upload is staged and reviewed first.

1. **Export a CSV** from your platform (Stripe, PayPal, Zeffy, GiveWP, Facebook,
   or the offline-gifts sheet for checks/cash/in-kind).
2. **Upload it** (up to 16 MB) and pick the source. Columns are matched
   automatically using the templates in `docs/column-mappings/`.
3. **Review the batch.** Each row is normalized — dates to ISO, money to cents,
   net = amount − fee for gateways — and matched against existing donors by
   email, then name + address, then name + phone (so repeat givers aren't
   duplicated). Rows that can't be parsed are flagged, not silently dropped.
4. **Commit or discard.** Committing recomputes donor totals. Duplicate
   transactions are skipped automatically (matched on source + transaction ID).
5. **Roll back** a committed batch any time (admin only) — it cleanly reverses
   every gift and donor that batch created.

Imports are CSV-only by design (keeps the server install lean). XLSX and direct
API imports are Phase 2. The engine lives in `importer.py`; per-platform column
maps live in `docs/column-mappings/*.yaml` as the single source of truth.

---

## Build phases

**Phase 1 — Must-have first version**
CSV import · column mapping · normalize · donor profiles · donation history ·
search · notes · basic reports · duplicate detection · manual merge · export to Excel/CSV

**Phase 2 — Next up**
Stripe/PayPal/Zeffy API imports · Facebook import workflow · receipt generation ·
thank-you tracking · major-donor tracking · recurring dashboard · household giving ·
tags/segments · Mailchimp/Flodesk integration

Tracked in detail in `docs/REQUIREMENTS.md`.

---

## A note on privacy

This database holds donor PII — names, addresses, emails, phone numbers, and giving
history. **The code is open source, but your data never is:** never commit real
donor exports, API keys, or `.env` files. The `.gitignore` keeps the database and
secrets out of git; the `samples/` directory is for **sanitized / fake** data only.
Run your live instance on a server you control, behind HTTPS, with a strong admin
password and per-person accounts (see User roles above).
