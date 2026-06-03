"""
Always & Furever — Donor CRM (Phase 1 web app)
A lightweight Flask app over the SQLite schema in db/schema.sql.

Run:  ./run.sh        (creates db, seeds demo data, starts server)
Then: http://127.0.0.1:5000
"""
import os
import sqlite3
from datetime import datetime
from flask import Flask, g, render_template, request, redirect, url_for, flash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "donor_crm.sqlite")

app = Flask(__name__)
app.secret_key = "dev-only-not-secret"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def money(cents):
    if cents is None:
        cents = 0
    return "${:,.2f}".format(cents / 100.0)


app.jinja_env.filters["money"] = money


def q(sql, args=()):
    return get_db().execute(sql, args).fetchall()


def q1(sql, args=()):
    return get_db().execute(sql, args).fetchone()


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@app.route("/")
def dashboard():
    totals = q1("""
        SELECT
            COUNT(*)                       AS gift_count,
            COALESCE(SUM(amount_cents),0)  AS gross,
            COALESCE(SUM(fee_cents),0)     AS fees,
            COALESCE(SUM(net_cents),0)     AS net
        FROM donations
    """)
    donor_count = q1("SELECT COUNT(*) AS c FROM donors WHERE is_merged = 0")["c"]
    recurring = q1("SELECT COUNT(*) AS c FROM donors WHERE is_recurring_donor = 1 AND is_merged = 0")["c"]

    by_source = q("""
        SELECT s.label AS label,
               COUNT(*) AS gifts,
               SUM(d.amount_cents) AS gross
        FROM donations d JOIN sources s ON s.id = d.source_id
        GROUP BY s.id ORDER BY gross DESC
    """)
    by_month = q("""
        SELECT substr(donation_date,1,7) AS ym,
               COUNT(*) AS gifts,
               SUM(amount_cents) AS gross
        FROM donations
        GROUP BY ym ORDER BY ym DESC LIMIT 12
    """)
    recent = q("""
        SELECT d.id, d.donation_date, d.amount_cents, s.label AS source,
               dn.id AS donor_id,
               COALESCE(NULLIF(TRIM(COALESCE(dn.first_name,'')||' '||COALESCE(dn.last_name,'')),''),
                        dn.organization_name, dn.household_name, '(unnamed)') AS donor_name
        FROM donations d
        JOIN donors dn ON dn.id = d.donor_id
        LEFT JOIN sources s ON s.id = d.source_id
        ORDER BY d.donation_date DESC, d.id DESC LIMIT 10
    """)
    followups = q("""
        SELECT n.id, n.follow_up_date, n.note_text, dn.id AS donor_id,
               COALESCE(NULLIF(TRIM(COALESCE(dn.first_name,'')||' '||COALESCE(dn.last_name,'')),''),
                        dn.organization_name, '(unnamed)') AS donor_name
        FROM donor_notes n JOIN donors dn ON dn.id = n.donor_id
        WHERE n.follow_up_needed = 1 AND n.follow_up_done = 0
        ORDER BY n.follow_up_date LIMIT 10
    """)
    open_dupes = q1("SELECT COUNT(*) AS c FROM duplicate_candidates WHERE status='open'")["c"]
    return render_template("dashboard.html", totals=totals, donor_count=donor_count,
                           recurring=recurring, by_source=by_source, by_month=by_month,
                           recent=recent, followups=followups, open_dupes=open_dupes)


# ---------------------------------------------------------------------------
# Donors
# ---------------------------------------------------------------------------
@app.route("/donors")
def donors():
    search = request.args.get("q", "").strip()
    where, args = "WHERE d.is_merged = 0", []
    if search:
        like = f"%{search}%"
        where += """ AND (
            d.first_name LIKE ? OR d.last_name LIKE ? OR d.organization_name LIKE ?
            OR d.household_name LIKE ? OR d.primary_email LIKE ? OR d.primary_phone LIKE ?
            OR d.city LIKE ? OR d.postal_code LIKE ?)"""
        args += [like] * 8
    rows = q(f"""
        SELECT d.*,
               COALESCE(NULLIF(TRIM(COALESCE(d.first_name,'')||' '||COALESCE(d.last_name,'')),''),
                        d.organization_name, d.household_name, '(unnamed)') AS display_name
        FROM donors d {where}
        ORDER BY d.donation_total_cents DESC, d.last_name
        LIMIT 200
    """, args)
    return render_template("donors.html", donors=rows, search=search)


@app.route("/donors/<int:donor_id>")
def donor_detail(donor_id):
    d = q1("SELECT * FROM donors WHERE id = ?", (donor_id,))
    if not d:
        flash("Donor not found.")
        return redirect(url_for("donors"))
    gifts = q("""
        SELECT dn.*, s.label AS source, pm.label AS pay_method,
               c.label AS campaign, f.label AS fund, tt.label AS tribute_type
        FROM donations dn
        LEFT JOIN sources s ON s.id = dn.source_id
        LEFT JOIN payment_methods pm ON pm.id = dn.payment_method_id
        LEFT JOIN campaigns c ON c.id = dn.campaign_id
        LEFT JOIN funds f ON f.id = dn.fund_id
        LEFT JOIN tribute_types tt ON tt.id = dn.tribute_type_id
        WHERE dn.donor_id = ? ORDER BY dn.donation_date DESC, dn.id DESC
    """, (donor_id,))
    notes = q("""
        SELECT n.*, u.display_name AS author
        FROM donor_notes n LEFT JOIN users u ON u.id = n.author_id
        WHERE n.donor_id = ? ORDER BY n.note_date DESC, n.id DESC
    """, (donor_id,))
    emails = q("SELECT * FROM donor_emails WHERE donor_id = ?", (donor_id,))
    phones = q("SELECT * FROM donor_phones WHERE donor_id = ?", (donor_id,))
    tags = q("""SELECT t.name FROM tags t JOIN donor_tags dt ON dt.tag_id = t.id
                WHERE dt.donor_id = ?""", (donor_id,))
    return render_template("donor_detail.html", d=d, gifts=gifts, notes=notes,
                           emails=emails, phones=phones, tags=tags)


@app.route("/donors/<int:donor_id>/note", methods=["POST"])
def add_note(donor_id):
    text = request.form.get("note_text", "").strip()
    if text:
        note_type = request.form.get("note_type", "general")
        fu = 1 if request.form.get("follow_up_needed") else 0
        fu_date = request.form.get("follow_up_date") or None
        db = get_db()
        db.execute("""INSERT INTO donor_notes (donor_id, note_type, note_text,
                      follow_up_needed, follow_up_date, author_id)
                      VALUES (?,?,?,?,?,1)""",
                   (donor_id, note_type, text, fu, fu_date))
        db.commit()
        flash("Note added.")
    return redirect(url_for("donor_detail", donor_id=donor_id))


# ---------------------------------------------------------------------------
# Donations
# ---------------------------------------------------------------------------
@app.route("/donations")
def donations():
    source = request.args.get("source", "")
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    where, args = "WHERE 1=1", []
    if source:
        where += " AND s.code = ?"
        args.append(source)
    if start:
        where += " AND dn.donation_date >= ?"
        args.append(start)
    if end:
        where += " AND dn.donation_date <= ?"
        args.append(end)
    rows = q(f"""
        SELECT dn.id, dn.donation_date, dn.amount_cents, dn.fee_cents, dn.net_cents,
               dn.is_recurring, dn.is_in_kind, s.label AS source,
               d.id AS donor_id,
               COALESCE(NULLIF(TRIM(COALESCE(d.first_name,'')||' '||COALESCE(d.last_name,'')),''),
                        d.organization_name, d.household_name, '(unnamed)') AS donor_name
        FROM donations dn
        JOIN donors d ON d.id = dn.donor_id
        LEFT JOIN sources s ON s.id = dn.source_id
        {where}
        ORDER BY dn.donation_date DESC, dn.id DESC LIMIT 500
    """, args)
    total = sum(r["amount_cents"] for r in rows)
    sources = q("SELECT code, label FROM sources ORDER BY label")
    return render_template("donations.html", donations=rows, sources=sources,
                           total=total, f={"source": source, "start": start, "end": end})


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
@app.route("/reports")
def reports():
    by_source = q("""SELECT s.label AS label, COUNT(*) AS gifts,
                     SUM(d.amount_cents) AS gross, SUM(d.fee_cents) AS fees,
                     SUM(d.net_cents) AS net
                     FROM donations d JOIN sources s ON s.id=d.source_id
                     GROUP BY s.id ORDER BY gross DESC""")
    by_campaign = q("""SELECT COALESCE(c.label,'(none)') AS label, COUNT(*) AS gifts,
                       SUM(d.amount_cents) AS gross
                       FROM donations d LEFT JOIN campaigns c ON c.id=d.campaign_id
                       GROUP BY c.id ORDER BY gross DESC""")
    by_fund = q("""SELECT COALESCE(f.label,'(none)') AS label, COUNT(*) AS gifts,
                   SUM(d.amount_cents) AS gross
                   FROM donations d LEFT JOIN funds f ON f.id=d.fund_id
                   GROUP BY f.id ORDER BY gross DESC""")
    top_donors = q("""SELECT id, donation_total_cents, gift_count,
                      COALESCE(NULLIF(TRIM(COALESCE(first_name,'')||' '||COALESCE(last_name,'')),''),
                               organization_name, household_name,'(unnamed)') AS name
                      FROM donors WHERE is_merged=0
                      ORDER BY donation_total_cents DESC LIMIT 10""")
    no_address = q("""SELECT id,
                      COALESCE(NULLIF(TRIM(COALESCE(first_name,'')||' '||COALESCE(last_name,'')),''),
                               organization_name,'(unnamed)') AS name, primary_email
                      FROM donors WHERE is_merged=0 AND (address_line1 IS NULL OR address_line1='')
                      ORDER BY donation_total_cents DESC LIMIT 50""")
    need_receipt = q("""SELECT COUNT(*) AS c, COALESCE(SUM(amount_cents),0) AS amt
                        FROM donations WHERE receipt_status='unsent'""")[0]
    recurring_rev = q1("""SELECT COUNT(*) AS gifts, COALESCE(SUM(amount_cents),0) AS gross
                          FROM donations WHERE is_recurring=1""")
    return render_template("reports.html", by_source=by_source, by_campaign=by_campaign,
                           by_fund=by_fund, top_donors=top_donors, no_address=no_address,
                           need_receipt=need_receipt, recurring_rev=recurring_rev)


@app.route("/import")
def import_page():
    batches = q("""SELECT b.*, s.label AS source FROM import_batches b
                   LEFT JOIN sources s ON s.id=b.source_id
                   ORDER BY b.created_at DESC""")
    return render_template("import.html", batches=batches)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
