"""
Donation import engine — parse, normalize, match, and commit donor data.

Design goals
------------
* The column-map templates in docs/column-mappings/*.yaml are the SINGLE source of
  truth for how each platform's columns line up to our standard fields. This module
  reads them at runtime; it never hard-codes a vendor's column names.
* Nothing touches the database until a human approves a staged batch. parse_file()
  is pure (read + normalize only); commit_batch() is the only writer.
* Money is integer cents everywhere (matches schema). Dates are ISO YYYY-MM-DD.
* Imports are reviewable and reversible: every gift carries its import_batch_id,
  and a committed batch can be rolled back.

CSV only for Phase 1. Every supported platform (Stripe, PayPal, Zeffy, GiveWP,
Facebook, offline) exports CSV, so we avoid pulling openpyxl into the VPS install.
"""

import csv
import io
import os
import re
import hashlib
from datetime import datetime

import yaml

# ---------------------------------------------------------------------------
# Paths / source catalog
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
MAPPINGS_DIR = os.path.join(_HERE, "docs", "column-mappings")

# The platforms that ship a column-map template (the gateways + the offline sheet).
# Each value is the source `code` in the sources lookup table.
SOURCE_TEMPLATES = {
    "stripe":   "stripe",
    "paypal":   "paypal",
    "zeffy":    "zeffy",
    "givewp":   "givewp",
    "facebook": "facebook",
    "offline":  None,   # offline maps each row's own "Source" column to a source code
}

MAX_UPLOAD_BYTES = 16 * 1024 * 1024  # 16 MB hard cap (also enforced by Flask config)


class ImportError_(Exception):
    """Raised for user-facing import problems (bad file, unknown source, etc.)."""


# ---------------------------------------------------------------------------
# Mapping templates
# ---------------------------------------------------------------------------
def load_mapping(template):
    """Load and parse a docs/column-mappings/<template>.yaml file."""
    path = os.path.join(MAPPINGS_DIR, f"{template}.yaml")
    if not os.path.isfile(path):
        raise ImportError_(f"No column-map template for '{template}'.")
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    col_to_field = {}
    for m in data.get("mappings", []):
        sc = m.get("source_column")
        sf = m.get("standard_field")
        if sc and sf:  # null standard_field means "handled specially / ignore"
            col_to_field[sc] = sf
    return {
        "source": data.get("source"),
        "col_to_field": col_to_field,
        "defaults": data.get("defaults", {}) or {},
    }


# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------
_DATE_FORMATS = (
    "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d",
    "%d/%m/%Y", "%b %d, %Y", "%B %d, %Y", "%m-%d-%Y",
    "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M", "%Y-%m-%dT%H:%M:%S",
)


def norm_date(raw):
    """Best-effort parse to ISO YYYY-MM-DD. Returns None if unparseable."""
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # Trim trailing timezone / fractional seconds Stripe-style.
    s = re.sub(r"\s*(UTC|GMT|[+-]\d{2}:?\d{2})$", "", s).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # ISO prefix fallback (e.g. "2026-02-01T13:04:05.000Z")
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else None


def norm_money_cents(raw):
    """Parse a money string to integer cents. '$1,234.56' -> 123456. abs value."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")")  # accounting negatives
    s = s.replace("(", "").replace(")", "")
    s = re.sub(r"[^0-9.\-]", "", s)  # strip $, commas, currency words
    if s in ("", "-", ".", "-."):
        return None
    try:
        val = float(s)
    except ValueError:
        return None
    cents = int(round(abs(val) * 100))
    return cents


def norm_phone(raw):
    if not raw:
        return None
    digits = re.sub(r"[^0-9]", "", str(raw))
    return digits or None


def norm_email(raw):
    if not raw:
        return None
    s = str(raw).strip().lower()
    return s or None


def split_name(full):
    """'Jane Q Public' -> ('Jane', 'Public'). Single token -> last name only."""
    if not full:
        return (None, None)
    parts = str(full).strip().split()
    if not parts:
        return (None, None)
    if len(parts) == 1:
        return (None, parts[0])
    return (parts[0], parts[-1])


_RECURRING_HINT = re.compile(r"subscription|recurring|monthly|weekly|annual", re.I)


# ---------------------------------------------------------------------------
# Parse + stage (NO writes)
# ---------------------------------------------------------------------------
def parse_file(raw_bytes, source_code, lookups):
    """
    Turn an uploaded CSV into a list of normalized, preview-ready donation rows.

    `source_code` is one of SOURCE_TEMPLATES keys.
    `lookups` is a dict of code->id maps: sources, payment_methods, funds, campaigns
        (campaign/fund matched by label OR code, case-insensitive).

    Returns (rows, warnings). Each row is a dict with normalized standard fields
    plus `_source_code`, `_row_num`, and `_issues` (list of per-row warnings).
    NOTHING is written to the database here.
    """
    if source_code not in SOURCE_TEMPLATES:
        raise ImportError_(f"Unsupported source '{source_code}'.")
    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise ImportError_("File exceeds the 16 MB limit.")

    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw_bytes.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ImportError_("That file has no header row.")

    warnings = []
    rows = []

    if source_code == "offline":
        rows, warnings = _parse_offline(reader, lookups)
    else:
        mapping = load_mapping(source_code)
        rows, warnings = _parse_gateway(reader, source_code, mapping, lookups)

    if not rows:
        warnings.append("No data rows found in the file.")
    return rows, warnings


def _label_code_index(table_rows):
    """Build a lookup that resolves by code OR label (lowercased) -> id."""
    idx = {}
    for r in table_rows:
        idx[str(r["code"]).lower()] = r["id"]
        idx[str(r["label"]).lower()] = r["id"]
    return idx


def _parse_gateway(reader, source_code, mapping, lookups):
    warnings = []
    rows = []
    col_to_field = mapping["col_to_field"]
    defaults = mapping["defaults"]
    src_id = lookups["sources"].get(source_code)
    pm_idx = lookups["payment_methods"]
    fund_idx = lookups["funds"]
    camp_idx = lookups["campaigns"]

    # Which raw column (if any) carries a full "First Last" name for this template.
    name_cols = {
        "stripe": "Customer Name", "paypal": "Name",
        "facebook": "Donor Name", "givewp": None, "zeffy": None,
    }
    name_col = name_cols.get(source_code)

    for i, raw in enumerate(reader, start=1):
        rec = {
            "_row_num": i, "_source_code": source_code, "_source_id": src_id,
            "_issues": [], "first_name": None, "last_name": None,
            "organization_name": None, "email": None, "phone": None,
            "address_line1": None, "address_line2": None, "city": None,
            "state": None, "postal_code": None, "country": None,
            "donation_date": None, "amount_cents": None, "fee_cents": 0,
            "net_cents": None, "currency": "USD", "source_txn_id": None,
            "campaign_id": None, "fund_id": None, "is_recurring": 0,
            "tribute_honoree": None, "notes": None,
            "payment_method_id": pm_idx.get(defaults.get("payment_method")),
        }
        recurring_hint_text = ""

        for col, val in raw.items():
            field = col_to_field.get(col)
            if not field:
                # Capture recurring/type hints even when the column isn't mapped.
                if col and re.search(r"type|frequency", col, re.I):
                    recurring_hint_text += f" {val}"
                continue
            val = (val or "").strip()
            if field == "donation_date":
                rec["donation_date"] = norm_date(val)
            elif field == "amount":
                rec["amount_cents"] = norm_money_cents(val)
            elif field == "fee":
                rec["fee_cents"] = norm_money_cents(val) or 0
            elif field == "net":
                rec["net_cents"] = norm_money_cents(val)
            elif field == "currency":
                rec["currency"] = (val or "USD").upper()[:3] or "USD"
            elif field == "source_txn_id":
                rec["source_txn_id"] = val or None
            elif field == "email":
                rec["email"] = norm_email(val)
            elif field == "phone":
                rec["phone"] = norm_phone(val)
            elif field == "first_name":
                rec["first_name"] = val or None
            elif field == "last_name":
                rec["last_name"] = val or None
            elif field == "campaign":
                if val:
                    rec["campaign_id"] = camp_idx.get(val.lower())
                    if rec["campaign_id"] is None:
                        rec["_issues"].append(f"campaign '{val}' not found")
            elif field == "fund":
                if val:
                    rec["fund_id"] = fund_idx.get(val.lower())
                    if rec["fund_id"] is None:
                        rec["_issues"].append(f"fund '{val}' not found")
            elif field in ("address_line1", "address_line2", "city",
                           "state", "postal_code", "country", "notes",
                           "tribute_honoree", "organization_name"):
                rec[field] = val or None

        # Full-name column → split if we didn't get explicit first/last.
        if name_col and not (rec["first_name"] or rec["last_name"]):
            fn, ln = split_name(raw.get(name_col))
            rec["first_name"], rec["last_name"] = fn, ln

        # Recurring detection from a Type/Frequency column.
        if _RECURRING_HINT.search(recurring_hint_text):
            rec["is_recurring"] = 1

        # net = amount - fee when the file didn't give us a net.
        if rec["net_cents"] is None and rec["amount_cents"] is not None:
            rec["net_cents"] = rec["amount_cents"] - (rec["fee_cents"] or 0)

        _validate_row(rec)
        rows.append(rec)
    return rows, warnings


def _parse_offline(reader, lookups):
    """Offline sheet: each row names its own Source / Payment Method / Fund / etc."""
    warnings = []
    rows = []
    src_idx = lookups["sources"]
    pm_idx = lookups["payment_methods"]
    fund_idx = lookups["funds"]
    camp_idx = lookups["campaigns"]

    for i, raw in enumerate(reader, start=1):
        g = lambda k: (raw.get(k) or "").strip()
        src_code = g("Source").lower()
        src_id = src_idx.get(src_code)
        pm_id = pm_idx.get(g("Payment Method").lower())
        amount = norm_money_cents(g("Amount")) or 0
        fund_label = g("Fund").lower()
        camp_label = g("Campaign").lower()
        is_in_kind = "in_kind" in src_code or g("Payment Method").lower() == "in_kind" \
            or src_code.startswith("wishlist")

        rec = {
            "_row_num": i, "_source_code": src_code or "other",
            "_source_id": src_id, "_issues": [],
            "first_name": g("First Name") or None,
            "last_name": g("Last Name") or None,
            "organization_name": g("Organization") or None,
            "email": norm_email(g("Email")),
            "phone": norm_phone(g("Phone")),
            "address_line1": g("Address") or None,
            "address_line2": None,
            "city": g("City") or None, "state": g("State") or None,
            "postal_code": g("Zip") or None, "country": None,
            "donation_date": norm_date(g("Date")),
            "amount_cents": amount, "fee_cents": 0, "net_cents": amount,
            "currency": "USD",
            "source_txn_id": g("Check Number") or None,
            "campaign_id": camp_idx.get(camp_label) if camp_label else None,
            "fund_id": fund_idx.get(fund_label) if fund_label else None,
            "payment_method_id": pm_id,
            "is_recurring": 0,
            "tribute_honoree": g("In Honor/Memory Of") or None,
            "is_in_kind": 1 if is_in_kind else 0,
            "in_kind_description": g("In-Kind Description") or None,
            "notes": g("Notes") or None,
        }
        if src_id is None:
            rec["_issues"].append(f"source '{src_code}' not recognized")
        if fund_label and rec["fund_id"] is None:
            rec["_issues"].append(f"fund '{fund_label}' not found")
        if camp_label and rec["campaign_id"] is None:
            rec["_issues"].append(f"campaign '{camp_label}' not found")
        _validate_row(rec)
        rows.append(rec)
    return rows, warnings


def _validate_row(rec):
    """Append blocking issues. A row with issues still previews but won't commit."""
    if rec["donation_date"] is None:
        rec["_issues"].append("missing/!unparseable date")
    if rec["amount_cents"] is None:
        rec["_issues"].append("missing/unparseable amount")
    has_name = rec.get("first_name") or rec.get("last_name") or rec.get("organization_name")
    if not has_name and not rec.get("email"):
        rec["_issues"].append("no donor name or email")


# ---------------------------------------------------------------------------
# Donor matching ladder
# ---------------------------------------------------------------------------
def match_donor(db, rec):
    """
    Find an existing donor for a staged row.
    Ladder: email  ->  last_name + postal_code  ->  last_name + phone.
    Returns (donor_id or None, reason or None).
    """
    email = rec.get("email")
    if email:
        row = db.execute(
            "SELECT id FROM donors WHERE is_merged=0 AND lower(primary_email)=? LIMIT 1",
            (email,)).fetchone()
        if row:
            return row["id"], "email"
        row = db.execute(
            """SELECT donor_id AS id FROM donor_emails
               WHERE lower(email)=? LIMIT 1""", (email,)).fetchone()
        if row:
            return row["id"], "email"

    last = (rec.get("last_name") or "").strip().lower()
    org = (rec.get("organization_name") or "").strip().lower()
    postal = (rec.get("postal_code") or "").strip()
    phone = rec.get("phone")

    if last and postal:
        row = db.execute(
            """SELECT id FROM donors WHERE is_merged=0
               AND lower(last_name)=? AND postal_code=? LIMIT 1""",
            (last, postal)).fetchone()
        if row:
            return row["id"], "name_address"

    if last and phone:
        row = db.execute(
            """SELECT id FROM donors WHERE is_merged=0
               AND lower(last_name)=? AND primary_phone=? LIMIT 1""",
            (last, phone)).fetchone()
        if row:
            return row["id"], "name_phone"

    if org:
        row = db.execute(
            """SELECT id FROM donors WHERE is_merged=0
               AND lower(organization_name)=? LIMIT 1""", (org,)).fetchone()
        if row:
            return row["id"], "organization"

    return None, None


# ---------------------------------------------------------------------------
# Commit / rollback (THE ONLY WRITERS)
# ---------------------------------------------------------------------------
def commit_batch(db, batch_id, rows, user_id):
    """
    Write the approved rows. Skips rows with blocking issues and exact-duplicate
    transactions (same source_id + source_txn_id). Recomputes donor rollups.

    Runs in a single transaction; raises on error so the caller can roll back.
    Returns dict(imported, skipped, new_donors, matched_donors, dup_skipped).
    """
    imported = skipped = new_donors = matched_donors = dup_skipped = 0
    touched_donors = set()

    for rec in rows:
        if rec.get("_issues"):
            skipped += 1
            continue

        # Dedupe: same platform txn already present?
        if rec.get("source_txn_id") and rec.get("_source_id") is not None:
            dup = db.execute(
                """SELECT 1 FROM donations
                   WHERE source_id=? AND source_txn_id=? LIMIT 1""",
                (rec["_source_id"], rec["source_txn_id"])).fetchone()
            if dup:
                dup_skipped += 1
                skipped += 1
                continue

        donor_id, reason = match_donor(db, rec)
        if donor_id is None:
            donor_id = _insert_donor(db, rec)
            new_donors += 1
        else:
            matched_donors += 1
            _enrich_donor(db, donor_id, rec)
        touched_donors.add(donor_id)

        db.execute(
            """INSERT INTO donations
               (donor_id, donation_date, amount_cents, fee_cents, net_cents,
                currency, source_id, payment_method_id, campaign_id, fund_id,
                is_recurring, tribute_honoree, source_txn_id, import_batch_id,
                is_in_kind, in_kind_description, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (donor_id, rec["donation_date"], rec["amount_cents"],
             rec.get("fee_cents") or 0,
             rec.get("net_cents") if rec.get("net_cents") is not None
             else rec["amount_cents"],
             rec.get("currency") or "USD", rec.get("_source_id"),
             rec.get("payment_method_id"), rec.get("campaign_id"),
             rec.get("fund_id"), rec.get("is_recurring") or 0,
             rec.get("tribute_honoree"), rec.get("source_txn_id"), batch_id,
             rec.get("is_in_kind") or 0, rec.get("in_kind_description"),
             rec.get("notes")))
        imported += 1

    for donor_id in touched_donors:
        _recompute_donor(db, donor_id)

    db.execute(
        """UPDATE import_batches
           SET status='committed', imported_count=?, skipped_count=?,
               committed_at=datetime('now') WHERE id=?""",
        (imported, skipped, batch_id))

    return {"imported": imported, "skipped": skipped, "new_donors": new_donors,
            "matched_donors": matched_donors, "dup_skipped": dup_skipped}


def _insert_donor(db, rec):
    donor_type = "organization" if rec.get("organization_name") and not (
        rec.get("first_name") or rec.get("last_name")) else "individual"
    cur = db.execute(
        """INSERT INTO donors
           (donor_type, first_name, last_name, organization_name,
            primary_email, primary_phone, address_line1, address_line2,
            city, state, postal_code, country)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (donor_type, rec.get("first_name"), rec.get("last_name"),
         rec.get("organization_name"), rec.get("email"), rec.get("phone"),
         rec.get("address_line1"), rec.get("address_line2"), rec.get("city"),
         rec.get("state"), rec.get("postal_code"), rec.get("country")))
    donor_id = cur.lastrowid
    if rec.get("email"):
        db.execute(
            "INSERT OR IGNORE INTO donor_emails (donor_id, email, is_primary) "
            "VALUES (?,?,1)", (donor_id, rec["email"]))
    if rec.get("phone"):
        db.execute(
            "INSERT OR IGNORE INTO donor_phones (donor_id, phone, is_primary) "
            "VALUES (?,?,1)", (donor_id, rec["phone"]))
    return donor_id


def _enrich_donor(db, donor_id, rec):
    """Fill blank contact fields on an existing donor; never overwrite real data."""
    if rec.get("email"):
        db.execute(
            "INSERT OR IGNORE INTO donor_emails (donor_id, email) VALUES (?,?)",
            (donor_id, rec["email"]))
        db.execute(
            "UPDATE donors SET primary_email=? WHERE id=? AND "
            "(primary_email IS NULL OR primary_email='')",
            (rec["email"], donor_id))
    if rec.get("phone"):
        db.execute(
            "INSERT OR IGNORE INTO donor_phones (donor_id, phone) VALUES (?,?)",
            (donor_id, rec["phone"]))
        db.execute(
            "UPDATE donors SET primary_phone=? WHERE id=? AND "
            "(primary_phone IS NULL OR primary_phone='')",
            (rec["phone"], donor_id))
    for col in ("address_line1", "city", "state", "postal_code"):
        if rec.get(col):
            db.execute(
                f"UPDATE donors SET {col}=? WHERE id=? AND ({col} IS NULL OR {col}='')",
                (rec[col], donor_id))


def _recompute_donor(db, donor_id):
    """Refresh the rolling giving summary from raw donations (schema vw_donor_giving)."""
    db.execute(
        """UPDATE donors SET
             donation_total_cents = COALESCE((SELECT SUM(amount_cents) FROM donations WHERE donor_id=?),0),
             gift_count           = COALESCE((SELECT COUNT(*)          FROM donations WHERE donor_id=?),0),
             first_gift_date      = (SELECT MIN(donation_date) FROM donations WHERE donor_id=?),
             last_gift_date       = (SELECT MAX(donation_date) FROM donations WHERE donor_id=?),
             largest_gift_cents   = COALESCE((SELECT MAX(amount_cents) FROM donations WHERE donor_id=?),0),
             is_recurring_donor   = COALESCE((SELECT MAX(is_recurring) FROM donations WHERE donor_id=?),0),
             updated_at           = datetime('now')
           WHERE id=?""",
        (donor_id, donor_id, donor_id, donor_id, donor_id, donor_id, donor_id))


def rollback_batch(db, batch_id):
    """
    Reverse a committed batch: delete its donations, drop donors that came in with
    this batch and have no other gifts, recompute the rest, mark batch rolled_back.
    Returns dict(removed_donations, removed_donors).
    """
    donor_ids = [r["donor_id"] for r in db.execute(
        "SELECT DISTINCT donor_id FROM donations WHERE import_batch_id=?",
        (batch_id,)).fetchall()]

    cur = db.execute("DELETE FROM donations WHERE import_batch_id=?", (batch_id,))
    removed_donations = cur.rowcount

    removed_donors = 0
    for donor_id in donor_ids:
        remaining = db.execute(
            "SELECT COUNT(*) AS c FROM donations WHERE donor_id=?",
            (donor_id,)).fetchone()["c"]
        if remaining == 0:
            # Only delete a donor we created and that nothing else references.
            has_notes = db.execute(
                "SELECT 1 FROM donor_notes WHERE donor_id=? LIMIT 1",
                (donor_id,)).fetchone()
            if not has_notes:
                db.execute("DELETE FROM donor_emails WHERE donor_id=?", (donor_id,))
                db.execute("DELETE FROM donor_phones WHERE donor_id=?", (donor_id,))
                db.execute("DELETE FROM donor_tags WHERE donor_id=?", (donor_id,))
                db.execute("DELETE FROM donors WHERE id=?", (donor_id,))
                removed_donors += 1
            else:
                _recompute_donor(db, donor_id)
        else:
            _recompute_donor(db, donor_id)

    db.execute(
        "UPDATE import_batches SET status='rolled_back' WHERE id=?", (batch_id,))
    return {"removed_donations": removed_donations, "removed_donors": removed_donors}


def file_sha256(raw_bytes):
    return hashlib.sha256(raw_bytes).hexdigest()
