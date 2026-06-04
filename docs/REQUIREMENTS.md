# Requirements — Always & Furever Donor Database / CRM

Central donor database that combines donations from all sources into one clean
donor profile + reporting tool.

Legend: `[ ]` not started · `[~]` partial / designed · `[x]` done

---

## 1. Donation sources to import

**Online merchant gateways**
- [ ] Stripe exports
- [ ] PayPal exports
- [ ] Zeffy exports
- [ ] GiveWP / WordPress donation exports (if separate from Stripe/PayPal)
- [ ] Any future payment processors (schema supports via `sources` table)

**Other donation sources**
- [ ] Facebook donations
- [ ] Checks
- [ ] Cash
- [ ] In-kind donations
- [ ] Amazon / Chewy / Walmart wishlist gifts
- [ ] Corporate sponsorships
- [ ] Event donations
- [ ] Auction purchases
- [ ] Matching gifts
- [ ] Recurring / monthly gifts
- [ ] Tribute gifts — in memory of · in honor of · pet memorials · special occasion

> All of the above are modeled in `db/schema.sql` via the `sources` lookup +
> `donations` fields (`is_recurring`, `is_in_kind`, `tribute_*`). Seeded in
> `db/seed_lookups.sql`.

---

## 2. Initial data import plan

CSV/XLSX export from each platform → upload → map columns → clean → match → import.

Workflow (detailed in `docs/IMPORT_WORKFLOW.md`):
1. [ ] Export donation data from each platform
2. [ ] Upload the export file
3. [ ] Map each platform's columns to standard fields
4. [ ] Clean and normalize the data
5. [ ] Match donations to existing donor profiles
6. [ ] Create new donor profiles when no match
7. [ ] Store each donation as its own transaction record
8. [ ] Allow review before final import (batch staging + commit)

---

## 3. Core database structure — `[x]` designed in `db/schema.sql`

- [x] **Donor Profile** table (`donors`) — all requested fields incl. household/org,
      multiple emails/phones (`donor_emails`, `donor_phones`), rolling giving totals,
      tags, notes, relationship history.
- [x] **Donation Transaction** table (`donations`) — every requested field incl.
      gross/fee/net, source, campaign, fund, payment method, recurring flag,
      tribute info, receipt status, original platform txn id, import batch id, notes.
- [x] **Donor Notes / Activity** table (`donor_notes`) — date, author, note type,
      text, follow-up needed + follow-up date.

See `docs/DATA_MODEL.md` for the field-by-field walkthrough.

---

## 4. Matching / deduplication — `[x]` designed, `[ ]` implemented

Matching ladder (in `docs/IMPORT_WORKFLOW.md`):
1. Match by email address
2. Else match by full name + address
3. Else match by name + phone
4. Flag possible duplicates for review instead of auto-merging risky matches

- [x] `duplicate_candidates` table to stage flagged pairs
- [x] `merge_log` + `donors.merged_into_id` for manual merge with audit trail
- [ ] Matching engine implementation (Phase 1)
- [ ] Manual merge UI/CLI (Phase 1)

---

## 5. Reporting needed — `[ ]` (intent captured in `docs/REPORTS.md`)

**Donation reports:** total by date range · by month/year · gross vs net ·
by source · by campaign · by fund · recurring revenue · new vs returning donors.

**Donor reports:** top donors · first-time · lapsed · monthly · donors without
mailing addresses · donors over a threshold · donors needing thank-you calls ·
donors who gave through multiple platforms.

**Receipt / acknowledgment:** donations needing receipts · needing thank-you notes ·
annual giving summaries · in-kind receipts · check/cash logs.

---

## 6. Search & profile view — `[ ]`

Search by: name · email · phone · address · donation amount · campaign · source ·
date range · tags. (Indexes for these already in the schema.)

Profile view shows: contact info · total giving · giving history · recurring status ·
notes · tags · related household/company · receipt history · follow-up reminders.

---

## 7. Feature checklist

**Phase 1 — Must-have first version**
- [ ] Import CSV/XLSX
- [x] Standardized donation table (schema)
- [x] Donor profiles (schema)
- [x] Donation history (schema)
- [ ] Search
- [x] Notes (schema)
- [ ] Basic reports
- [x] Duplicate detection (schema) / [ ] engine
- [x] Manual donor merge (schema) / [ ] tooling
- [ ] Export reports to Excel/CSV

**Phase 2 — Strong next-phase**
- [ ] Automated API imports (Stripe / PayPal / Zeffy)
- [ ] Facebook donation import workflow
- [ ] Receipt generation
- [ ] Thank-you email tracking
- [ ] Major-donor tracking
- [ ] Recurring-donor dashboard
- [ ] Household giving
- [ ] Tags / segments for campaigns (schema present; UI pending)
- [ ] Mailchimp / Flodesk / email integration
- [x] Role-based permissions — three roles (admin / staff / readonly), enforced
  server-side via route decorators; admin-only user management at `/users`

---

## Suggested tech direction (not yet decided)

Nothing here is locked in — flagging options so the build conversation is easy:

- **Lightweight / self-hosted:** Python (FastAPI) + SQLite/Postgres + a small web UI,
  with `pandas`/`openpyxl` for CSV/XLSX parsing. Cheap, portable, easy to back up.
- **No-code-ish:** Airtable or NocoDB on top of this schema for the staff-facing views.
- **Off-the-shelf:** evaluate whether a nonprofit CRM (e.g. CiviCRM) covers enough —
  but the multi-source import + custom matching is exactly the part those tools do
  poorly, which is why this central schema exists.

Decision pending Ryan's input on hosting, budget, and who maintains it.
