"""
Always & Furever — Donor CRM (Phase 1 web app)
A lightweight Flask app over the SQLite schema in db/schema.sql.

Run:  ./run.sh        (creates db, seeds demo data, starts server)
Then: http://127.0.0.1:5000

SECURITY: This app holds donor PII (names, emails, phones, addresses, giving
history). It must never be served on the public internet without:
  - A strong SECRET_KEY set via the environment (see .env.example)
  - HTTPS terminated in front of it (nginx/Caddy) so secure cookies work
  - The login gate below (every route except /login + static requires auth)
"""
import os
import hmac
import secrets
import sqlite3
import functools
from datetime import datetime
from collections import defaultdict

from flask import (
    Flask, g, render_template, request, redirect, url_for, flash,
    session, abort, get_flashed_messages,
)
from werkzeug.security import check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "donor_crm.sqlite")

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Configuration & hardening
# ---------------------------------------------------------------------------
# SECRET_KEY MUST come from the environment in production. We fall back to a
# random per-process key for local dev — that logs everyone out on restart,
# which is the safe failure mode (never ship a hardcoded secret).
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
if not os.environ.get("SECRET_KEY"):
    app.logger.warning("SECRET_KEY not set — using an ephemeral dev key. "
                       "Set SECRET_KEY in the environment before hosting.")

# Secure cookies. SESSION_COOKIE_SECURE is on unless explicitly disabled for
# plain-HTTP local dev (set CRM_INSECURE_COOKIES=1).
_insecure = os.environ.get("CRM_INSECURE_COOKIES") == "1"
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,        # JS can't read the session cookie (XSS mitigation)
    SESSION_COOKIE_SAMESITE="Lax",       # CSRF mitigation for top-level navigations
    SESSION_COOKIE_SECURE=not _insecure, # cookie only sent over HTTPS
    PERMANENT_SESSION_LIFETIME=60 * 60 * 12,  # 12h idle horizon
    MAX_CONTENT_LENGTH=16 * 1024 * 1024, # 16 MB cap (future CSV uploads)
)

# Trust one proxy hop for X-Forwarded-* (so url_for/secure cookies work behind
# nginx/Caddy). Only enable when actually behind a trusted proxy.
if os.environ.get("CRM_BEHIND_PROXY") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


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
# Authentication
# ---------------------------------------------------------------------------
def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    if "user" not in g:
        g.user = q1("SELECT id, username, display_name, email, role FROM users "
                    "WHERE id = ? AND is_active = 1", (uid,))
    return g.user


def login_required(view):
    @functools.wraps(view)
    def wrapped(*a, **kw):
        if current_user() is None:
            session.clear()
            flash("Please sign in to continue.")
            return redirect(url_for("login", next=request.path))
        return view(*a, **kw)
    return wrapped


# Simple in-memory login throttle: max 5 failures per (ip+username) per window.
_LOGIN_FAILS = defaultdict(list)
_LOGIN_MAX = 5
_LOGIN_WINDOW = 300  # seconds


def _throttle_key():
    return (request.remote_addr or "?", (request.form.get("username") or "").lower())


def _too_many_attempts(key):
    now = datetime.utcnow().timestamp()
    fails = [t for t in _LOGIN_FAILS[key] if now - t < _LOGIN_WINDOW]
    _LOGIN_FAILS[key] = fails
    return len(fails) >= _LOGIN_MAX


def _record_fail(key):
    _LOGIN_FAILS[key].append(datetime.utcnow().timestamp())


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        # CSRF is validated globally in before_request for all POSTs.
        key = _throttle_key()
        if _too_many_attempts(key):
            flash("Too many sign-in attempts. Wait a few minutes and try again.")
            return render_template("login.html"), 429
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        user = q1("SELECT * FROM users WHERE lower(username) = ? AND is_active = 1",
                  (username,))
        # Always run a hash check to keep timing uniform whether or not the
        # user exists (avoids username enumeration via response time).
        stored = user["password_hash"] if user and user["password_hash"] else \
            "pbkdf2:sha256:600000$x$0000000000000000000000000000000000000000000000000000000000000000"
        ok = check_password_hash(stored, password)
        if user and ok:
            session.clear()
            session["uid"] = user["id"]
            session.permanent = True
            db = get_db()
            db.execute("UPDATE users SET last_login = datetime('now') WHERE id = ?",
                       (user["id"],))
            db.commit()
            nxt = request.args.get("next") or request.form.get("next") or ""
            # Only allow internal relative redirects (open-redirect guard).
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = url_for("dashboard")
            return redirect(nxt)
        _record_fail(key)
        flash("Invalid username or password.")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Signed out.")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# CSRF protection (double-submit token tied to the session)
# ---------------------------------------------------------------------------
def csrf_token():
    tok = session.get("csrf")
    if not tok:
        tok = secrets.token_urlsafe(32)
        session["csrf"] = tok
    return tok


app.jinja_env.globals["csrf_token"] = csrf_token
app.jinja_env.globals["current_user"] = current_user


@app.before_request
def csrf_protect():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        good = session.get("csrf", "")
        if not good or not hmac.compare_digest(sent, good):
            abort(400, description="CSRF token missing or invalid.")


# ---------------------------------------------------------------------------
# Security response headers
# ---------------------------------------------------------------------------
@app.after_request
def security_headers(resp):
    # CSP: allow self + Google Fonts (used by base.html). 'unsafe-inline' is
    # needed for the inline <style> blocks; tighten with hashes in Phase 2.
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "script-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    if app.config["SESSION_COOKIE_SECURE"]:
        resp.headers.setdefault("Strict-Transport-Security",
                                "max-age=31536000; includeSubDomains")
    return resp


@app.errorhandler(400)
def bad_request(e):
    return render_template("error.html", code=400,
                           message=getattr(e, "description", "Bad request.")), 400


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404,
                           message="That page doesn't exist."), 404


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@app.route("/")
@login_required
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
                        dn.organization_name, dn.household_name, '(unnamed)') AS donor_name
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
@login_required
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
@login_required
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
@login_required
def add_note(donor_id):
    text = request.form.get("note_text", "").strip()
    if text:
        note_type = request.form.get("note_type", "general")
        fu = 1 if request.form.get("follow_up_needed") else 0
        fu_date = request.form.get("follow_up_date") or None
        author_id = current_user()["id"]
        db = get_db()
        db.execute("""INSERT INTO donor_notes (donor_id, note_type, note_text,
                      follow_up_needed, follow_up_date, author_id)
                      VALUES (?,?,?,?,?,?)""",
                   (donor_id, note_type, text, fu, fu_date, author_id))
        db.commit()
        flash("Note added.")
    return redirect(url_for("donor_detail", donor_id=donor_id))


# ---------------------------------------------------------------------------
# Donations
# ---------------------------------------------------------------------------
@app.route("/donations")
@login_required
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
@login_required
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
                               organization_name, household_name,'(unnamed)') AS name, primary_email
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
@login_required
def import_page():
    batches = q("""SELECT b.*, s.label AS source FROM import_batches b
                   LEFT JOIN sources s ON s.id=b.source_id
                   ORDER BY b.created_at DESC""")
    return render_template("import.html", batches=batches)


if __name__ == "__main__":
    # debug=False always — the Werkzeug debugger is a remote code execution
    # vector if ever reachable. Use FLASK_DEBUG locally only if you must.
    debug = os.environ.get("FLASK_DEBUG") == "1"
    app.run(debug=debug, host="127.0.0.1", port=5000)
