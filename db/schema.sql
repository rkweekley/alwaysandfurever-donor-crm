-- =============================================================================
-- Always & Furever — Donor Database Schema
-- =============================================================================
-- Target: SQLite 3.35+ (works as-is). Notes inline for PostgreSQL.
--   - SQLite: leave as written.
--   - Postgres: replace `INTEGER PRIMARY KEY AUTOINCREMENT` with `SERIAL PRIMARY KEY`
--               (or `GENERATED ALWAYS AS IDENTITY`), and `TEXT`/`REAL` map cleanly.
--               Money is stored in CENTS as INTEGER to avoid float rounding.
-- =============================================================================

PRAGMA foreign_keys = ON;

-- -----------------------------------------------------------------------------
-- LOOKUP TABLES
-- -----------------------------------------------------------------------------

-- Where a gift came from: stripe, paypal, zeffy, givewp, facebook, check, cash,
-- in_kind, wishlist_amazon, wishlist_chewy, wishlist_walmart, corporate, event,
-- auction, matching_gift, other.
CREATE TABLE sources (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code          TEXT NOT NULL UNIQUE,          -- machine key, e.g. 'stripe'
    label         TEXT NOT NULL,                 -- display, e.g. 'Stripe'
    category      TEXT NOT NULL,                 -- 'gateway' | 'offline' | 'in_kind' | 'wishlist' | 'other'
    is_active     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE payment_methods (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code          TEXT NOT NULL UNIQUE,          -- 'card','ach','paypal','check','cash','in_kind','other'
    label         TEXT NOT NULL
);

-- Designation of where the money goes (general fund, medical fund, etc.)
CREATE TABLE funds (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code          TEXT NOT NULL UNIQUE,
    label         TEXT NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1
);

-- A fundraising campaign/appeal (Giving Tuesday 2026, Spring Appeal, etc.)
CREATE TABLE campaigns (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code          TEXT NOT NULL UNIQUE,
    label         TEXT NOT NULL,
    start_date    TEXT,                          -- ISO 8601 'YYYY-MM-DD'
    end_date      TEXT,
    goal_cents    INTEGER,
    is_active     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE tribute_types (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code          TEXT NOT NULL UNIQUE,          -- 'in_memory','in_honor','pet_memorial','special_occasion'
    label         TEXT NOT NULL
);

-- App users / staff who add notes, run imports, merge donors.
CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    display_name  TEXT NOT NULL,
    email         TEXT,
    role          TEXT NOT NULL DEFAULT 'staff', -- 'admin' | 'staff' | 'readonly'  (Phase 2 enforcement)
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- -----------------------------------------------------------------------------
-- DONOR PROFILE
-- -----------------------------------------------------------------------------
-- One master profile per donor. A donor can be a person, a household, or an org.
-- Rolling totals (donation_total, first/last gift, largest) are MAINTAINED by the
-- app (or the recompute view below) so profile reads stay fast.

CREATE TABLE donors (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    donor_type            TEXT NOT NULL DEFAULT 'individual', -- 'individual'|'household'|'organization'
    first_name            TEXT,
    last_name             TEXT,
    household_name        TEXT,                  -- "The Smith Family"
    organization_name     TEXT,                  -- company / foundation name

    -- Primary contact (additional emails/phones live in donor_emails/donor_phones)
    primary_email         TEXT,
    primary_phone         TEXT,
    preferred_contact     TEXT,                  -- 'email'|'phone'|'mail'|'none'

    -- Mailing address
    address_line1         TEXT,
    address_line2         TEXT,
    city                  TEXT,
    state                 TEXT,
    postal_code           TEXT,
    country               TEXT DEFAULT 'USA',

    -- Relationship to a parent donor (e.g. individual -> household/org)
    related_donor_id      INTEGER REFERENCES donors(id) ON DELETE SET NULL,
    relationship_label    TEXT,                  -- 'member of household', 'employee of', etc.

    -- Rolling giving summary (maintained by app; see vw_donor_giving to recompute)
    donation_total_cents  INTEGER NOT NULL DEFAULT 0,
    gift_count            INTEGER NOT NULL DEFAULT 0,
    first_gift_date       TEXT,
    last_gift_date        TEXT,
    largest_gift_cents    INTEGER NOT NULL DEFAULT 0,
    is_recurring_donor    INTEGER NOT NULL DEFAULT 0,

    notes                 TEXT,                  -- free-form profile note (activity log is donor_notes)
    is_merged             INTEGER NOT NULL DEFAULT 0,  -- 1 if this profile was merged AWAY
    merged_into_id        INTEGER REFERENCES donors(id) ON DELETE SET NULL,

    created_at            TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_donors_last_first   ON donors(last_name, first_name);
CREATE INDEX idx_donors_email        ON donors(primary_email);
CREATE INDEX idx_donors_phone        ON donors(primary_phone);
CREATE INDEX idx_donors_postal       ON donors(postal_code);
CREATE INDEX idx_donors_org          ON donors(organization_name);
CREATE INDEX idx_donors_merged_into  ON donors(merged_into_id);

-- A donor may have several emails / phones (used heavily by dedup matching).
CREATE TABLE donor_emails (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    donor_id    INTEGER NOT NULL REFERENCES donors(id) ON DELETE CASCADE,
    email       TEXT NOT NULL,
    is_primary  INTEGER NOT NULL DEFAULT 0,
    UNIQUE(donor_id, email)
);
CREATE INDEX idx_donor_emails_email ON donor_emails(email);

CREATE TABLE donor_phones (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    donor_id    INTEGER NOT NULL REFERENCES donors(id) ON DELETE CASCADE,
    phone       TEXT NOT NULL,
    is_primary  INTEGER NOT NULL DEFAULT 0,
    UNIQUE(donor_id, phone)
);
CREATE INDEX idx_donor_phones_phone ON donor_phones(phone);

-- Free-form tags / segments (campaign segments, "major prospect", "volunteer", …)
CREATE TABLE tags (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name   TEXT NOT NULL UNIQUE
);
CREATE TABLE donor_tags (
    donor_id  INTEGER NOT NULL REFERENCES donors(id) ON DELETE CASCADE,
    tag_id    INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (donor_id, tag_id)
);

-- -----------------------------------------------------------------------------
-- IMPORT BATCHES
-- -----------------------------------------------------------------------------
-- Every uploaded file becomes a batch so imports are reviewable and reversible.

CREATE TABLE import_batches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       INTEGER REFERENCES sources(id),
    filename        TEXT NOT NULL,
    file_hash       TEXT,                        -- sha256 to detect re-uploading the same file
    uploaded_by     INTEGER REFERENCES users(id),
    status          TEXT NOT NULL DEFAULT 'pending', -- 'pending'|'mapped'|'reviewed'|'committed'|'rolled_back'
    row_count       INTEGER NOT NULL DEFAULT 0,
    imported_count  INTEGER NOT NULL DEFAULT 0,
    skipped_count   INTEGER NOT NULL DEFAULT 0,
    mapping_json    TEXT,                        -- the column map used, stored for audit
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    committed_at    TEXT
);

-- -----------------------------------------------------------------------------
-- DONATION TRANSACTIONS
-- -----------------------------------------------------------------------------
-- Each gift is its own row. Money in CENTS (INTEGER) to avoid float errors.

CREATE TABLE donations (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    donor_id                INTEGER NOT NULL REFERENCES donors(id) ON DELETE RESTRICT,

    donation_date           TEXT NOT NULL,       -- ISO 'YYYY-MM-DD'
    amount_cents            INTEGER NOT NULL,     -- gross
    fee_cents               INTEGER NOT NULL DEFAULT 0,
    net_cents               INTEGER NOT NULL DEFAULT 0,  -- amount - fee
    currency                TEXT NOT NULL DEFAULT 'USD',

    source_id               INTEGER REFERENCES sources(id),
    payment_method_id       INTEGER REFERENCES payment_methods(id),
    campaign_id             INTEGER REFERENCES campaigns(id),
    fund_id                 INTEGER REFERENCES funds(id),

    is_recurring            INTEGER NOT NULL DEFAULT 0,  -- one-time vs recurring instance
    recurring_group_id      TEXT,                -- ties instances of one recurring plan together

    -- Tribute / memorial info
    tribute_type_id         INTEGER REFERENCES tribute_types(id),
    tribute_honoree         TEXT,                -- "in memory of Max"
    tribute_notify_name     TEXT,                -- who to notify of the tribute gift
    tribute_notify_address  TEXT,

    -- Receipting / acknowledgment
    receipt_status          TEXT NOT NULL DEFAULT 'unsent', -- 'unsent'|'sent'|'not_required'
    receipt_sent_date       TEXT,
    thank_you_status        TEXT NOT NULL DEFAULT 'pending', -- 'pending'|'sent'|'not_required'
    thank_you_sent_date     TEXT,

    -- Provenance
    source_txn_id           TEXT,                -- original platform transaction id
    import_batch_id         INTEGER REFERENCES import_batches(id) ON DELETE SET NULL,

    -- In-kind specifics (when source category = in_kind/wishlist; amount may be est. value)
    is_in_kind              INTEGER NOT NULL DEFAULT 0,
    in_kind_description     TEXT,

    notes                   TEXT,
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_donations_donor    ON donations(donor_id);
CREATE INDEX idx_donations_date     ON donations(donation_date);
CREATE INDEX idx_donations_source   ON donations(source_id);
CREATE INDEX idx_donations_campaign ON donations(campaign_id);
CREATE INDEX idx_donations_fund     ON donations(fund_id);
CREATE INDEX idx_donations_batch    ON donations(import_batch_id);

-- Prevent importing the exact same platform transaction twice.
-- (Partial unique: only enforced when source_txn_id is present.)
CREATE UNIQUE INDEX uq_donations_source_txn
    ON donations(source_id, source_txn_id)
    WHERE source_txn_id IS NOT NULL;

-- -----------------------------------------------------------------------------
-- DONOR NOTES / ACTIVITY
-- -----------------------------------------------------------------------------

CREATE TABLE donor_notes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    donor_id         INTEGER NOT NULL REFERENCES donors(id) ON DELETE CASCADE,
    note_date        TEXT NOT NULL DEFAULT (date('now')),
    author_id        INTEGER REFERENCES users(id),
    note_type        TEXT,                       -- 'call'|'email'|'meeting'|'prospect'|'preference'|'general'
    note_text        TEXT NOT NULL,
    follow_up_needed INTEGER NOT NULL DEFAULT 0,
    follow_up_date   TEXT,
    follow_up_done   INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_notes_donor      ON donor_notes(donor_id);
CREATE INDEX idx_notes_followup   ON donor_notes(follow_up_needed, follow_up_date);

-- -----------------------------------------------------------------------------
-- DEDUPLICATION
-- -----------------------------------------------------------------------------
-- Risky matches are flagged here for a human to confirm or reject rather than
-- auto-merging. See docs/IMPORT_WORKFLOW.md for the matching ladder.

CREATE TABLE duplicate_candidates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    donor_a_id      INTEGER NOT NULL REFERENCES donors(id) ON DELETE CASCADE,
    donor_b_id      INTEGER NOT NULL REFERENCES donors(id) ON DELETE CASCADE,
    match_reason    TEXT NOT NULL,               -- 'email'|'name_address'|'name_phone'|'fuzzy_name'
    confidence      REAL NOT NULL DEFAULT 0,      -- 0..1
    status          TEXT NOT NULL DEFAULT 'open', -- 'open'|'merged'|'rejected'
    reviewed_by     INTEGER REFERENCES users(id),
    reviewed_at     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(donor_a_id, donor_b_id)
);
CREATE INDEX idx_dupes_status ON duplicate_candidates(status);

-- Audit trail of completed merges (so a merge can be understood after the fact).
CREATE TABLE merge_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    surviving_id    INTEGER NOT NULL REFERENCES donors(id),
    merged_id       INTEGER NOT NULL,            -- the donor id that was absorbed (now is_merged=1)
    performed_by    INTEGER REFERENCES users(id),
    detail_json     TEXT,                        -- snapshot of what moved
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- -----------------------------------------------------------------------------
-- HELPER VIEW — recompute a donor's giving summary from raw donations.
-- Use to reconcile/repair the rolling columns on the donors table.
-- -----------------------------------------------------------------------------
CREATE VIEW vw_donor_giving AS
SELECT
    d.id                              AS donor_id,
    COUNT(dn.id)                      AS gift_count,
    COALESCE(SUM(dn.amount_cents), 0) AS donation_total_cents,
    MIN(dn.donation_date)            AS first_gift_date,
    MAX(dn.donation_date)            AS last_gift_date,
    COALESCE(MAX(dn.amount_cents), 0) AS largest_gift_cents,
    MAX(dn.is_recurring)             AS has_recurring
FROM donors d
LEFT JOIN donations dn ON dn.donor_id = d.id
GROUP BY d.id;
