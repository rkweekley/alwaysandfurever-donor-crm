# Import & Matching Workflow

How a platform export becomes clean donor + donation records.

```
Export file (CSV/XLSX)
   │
   ▼
[1] Upload  ──────────►  create import_batch (status=pending, store file hash)
   │
   ▼
[2] Map columns  ─────►  pick a saved mapping template (docs/column-mappings/*)
   │                     or map manually; mapping_json saved on the batch
   ▼
[3] Normalize  ──────►  trim, lowercase emails, format phones to E.164-ish,
   │                     parse dates to ISO, money → integer cents, fee/net split
   ▼
[4] Match each row to a donor (ladder below)
   │
   ▼
[5] Stage for review  ►  batch status=reviewed; show new donors, matched donors,
   │                     and flagged possible-duplicates
   ▼
[6] Commit  ─────────►  write donations, create donors as needed,
                         recompute giving totals, batch status=committed
```

A batch can be **rolled back** before/after commit because every donation carries
`import_batch_id`. Re-uploading the same file is caught by `file_hash`, and the same
platform transaction is caught by the unique `(source_id, source_txn_id)` index.

---

## The matching ladder

For each incoming row, try in order. First confident hit wins:

1. **Email match** — normalized email equals any `donor_emails.email`.
   High confidence → attach to that donor.
2. **Name + address** — `last_name` + `first_name` + `postal_code` (+ street line)
   match. High confidence when address is present.
3. **Name + phone** — when no address, `last_name` + `first_name` + `phone` match.
4. **No confident match** → either:
   - create a **new donor**, OR
   - if there's a *weak/partial* match (same name, different/empty contact info),
     create the donor **and** record a row in `duplicate_candidates` for a human to
     review. Never auto-merge a risky match.

Confidence is stored on `duplicate_candidates.confidence` (0..1) so review can be
sorted worst-first.

---

## Manual merge

When staff confirm two profiles are the same person:

1. Choose the **surviving** donor.
2. Re-point the merged donor's `donations`, `donor_notes`, `donor_emails`,
   `donor_phones`, `donor_tags` to the survivor.
3. Set the merged donor's `is_merged=1` and `merged_into_id=<survivor>`.
4. Recompute the survivor's giving totals (via `vw_donor_giving`).
5. Write a `merge_log` row with a JSON snapshot of what moved.

Merged profiles are kept (not deleted) so the history is auditable and a bad merge
can be understood/undone.

---

## Normalization rules (Phase 1 target)

| Field | Rule |
|-------|------|
| Email | lowercase, trim, strip surrounding quotes |
| Phone | strip non-digits; keep leading country code if present |
| Name | trim, collapse internal whitespace; preserve original casing |
| Money | parse to integer **cents**; strip `$` and commas |
| Fee/Net | if only gross given, fee=0/net=gross; if net given, fee = gross − net |
| Date | parse many formats → ISO `YYYY-MM-DD` |
| State | uppercase 2-letter where US |
