# Data Model — field by field

Money is stored in **integer cents** everywhere (`*_cents`) to avoid floating-point
rounding. Dates are ISO `YYYY-MM-DD` text. See `db/schema.sql` for the authoritative
definitions.

---

## donors — one master profile per donor

| Field | Meaning |
|-------|---------|
| `id` | Donor ID (primary key) |
| `donor_type` | `individual` / `household` / `organization` |
| `first_name`, `last_name` | Person name |
| `household_name` | e.g. "The Smith Family" |
| `organization_name` | Company / foundation |
| `primary_email`, `primary_phone` | Main contact (more in `donor_emails`/`donor_phones`) |
| `preferred_contact` | `email` / `phone` / `mail` / `none` |
| `address_line1/2`, `city`, `state`, `postal_code`, `country` | Mailing address |
| `related_donor_id`, `relationship_label` | Link to household/org (relationship history) |
| `donation_total_cents` | Rolling lifetime giving |
| `gift_count` | Number of gifts |
| `first_gift_date`, `last_gift_date` | Giving span |
| `largest_gift_cents` | Biggest single gift |
| `is_recurring_donor` | Has any active recurring gift |
| `notes` | Free-form profile note |
| `is_merged`, `merged_into_id` | Set when this profile was merged into another |

Supporting: `donor_emails`, `donor_phones` (many per donor — drives matching),
`tags` + `donor_tags` (segments).

---

## donations — every gift, stored separately

| Field | Meaning |
|-------|---------|
| `id` | Transaction ID |
| `donor_id` | Owning donor |
| `donation_date` | Date of gift |
| `amount_cents` | Gross amount |
| `fee_cents` | Processor fee |
| `net_cents` | Net after fees |
| `currency` | Default USD |
| `source_id` | Stripe / PayPal / Zeffy / Facebook / check / cash / … |
| `payment_method_id` | Card / ACH / check / cash / in-kind / … |
| `campaign_id` | Fundraising campaign/appeal |
| `fund_id` | Fund / designation |
| `is_recurring`, `recurring_group_id` | Recurring vs one-time; ties a plan's gifts together |
| `tribute_type_id`, `tribute_honoree`, `tribute_notify_*` | In memory/honor/pet memorial info |
| `receipt_status`, `receipt_sent_date` | Receipting state |
| `thank_you_status`, `thank_you_sent_date` | Acknowledgment state |
| `source_txn_id` | Original platform transaction ID |
| `import_batch_id` | Which upload created it (enables rollback) |
| `is_in_kind`, `in_kind_description` | Non-cash gift details |
| `notes` | Per-gift note |

---

## donor_notes — activity log

| Field | Meaning |
|-------|---------|
| `donor_id` | Whose profile |
| `note_date` | When |
| `author_id` | Staff/user who added it |
| `note_type` | `call` / `email` / `meeting` / `prospect` / `preference` / `general` |
| `note_text` | The note ("Called to thank donor", "Donated in memory of their dog Max") |
| `follow_up_needed`, `follow_up_date`, `follow_up_done` | Follow-up tracking |

---

## Supporting tables

- **import_batches** — every upload; status pending → mapped → reviewed → committed
  (or rolled_back); stores file hash + the column mapping used.
- **duplicate_candidates** — flagged possible-duplicate donor pairs awaiting review.
- **merge_log** — audit trail of completed merges.
- **sources / payment_methods / funds / campaigns / tribute_types** — lookups.
- **users** — staff accounts; `role` is one of `admin` / `staff` / `readonly`,
  enforced server-side (see User roles in the README). `is_active` soft-disables
  an account without deleting its history.
- **vw_donor_giving** — view that recomputes giving summary from raw donations
  (use it to repair/reconcile the rolling columns on `donors`).
