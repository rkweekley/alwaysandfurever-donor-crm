# Always & Furever — Donor Database / CRM

A central donor database and reporting tool for **Always & Furever Animal Rescue**
(<https://www.alwaysandfurever.org>).

The goal: combine donations from every source — Stripe, PayPal, Zeffy, Facebook,
checks, cash, in-kind gifts, wishlists, sponsorships, events, auctions, matching
gifts, recurring and tribute gifts — into **one clean donor profile** with solid
reporting, search, and deduplication.

> **Status:** Design / Phase 0. This repo currently contains the requirements
> spec, the database schema, and per-platform column-mapping templates. It is the
> blueprint the application is built against — not yet a running app.

---

## What's in here

| Path | What it is |
|------|------------|
| `docs/REQUIREMENTS.md` | Full feature spec (the brief, organized and tracked) |
| `docs/DATA_MODEL.md` | Plain-English walkthrough of every table and field |
| `docs/IMPORT_WORKFLOW.md` | Step-by-step the import/match/review pipeline |
| `docs/REPORTS.md` | Every report we need, with the query intent behind it |
| `docs/column-mappings/` | One mapping template per platform (Stripe, PayPal, Zeffy, …) |
| `db/schema.sql` | The full SQLite/Postgres-compatible schema |
| `db/seed_lookups.sql` | Lookup values (sources, payment methods, funds, note types) |
| `importers/` | Where import scripts will live (Phase 1) |
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

## Build phases

**Phase 1 — Must-have first version**
CSV/XLSX import · column mapping · normalize · donor profiles · donation history ·
search · notes · basic reports · duplicate detection · manual merge · export to Excel/CSV

**Phase 2 — Next up**
Stripe/PayPal/Zeffy API imports · Facebook import workflow · receipt generation ·
thank-you tracking · major-donor tracking · recurring dashboard · household giving ·
tags/segments · Mailchimp/Flodesk integration · role-based permissions

Tracked in detail in `docs/REQUIREMENTS.md`.

---

## A note on privacy

This database holds donor PII — names, addresses, emails, phone numbers, and giving
history. The repository is **private**. Never commit real donor exports, API keys, or
`.env` files. The `samples/` directory is for **sanitized / fake** data only.
