"""
Production database initializer for the Always & Furever Donor CRM.

Unlike seed_demo.py (which loads 10 fake donors for a demo), this script writes
ONLY what a real deployment needs to start:

  - the full schema (db/schema.sql)
  - the lookup values (db/seed_lookups.sql): sources, payment methods, funds,
    tribute types, and the built-in 'system' user
  - ONE real admin account, created from your answers

It will NOT overwrite an existing database unless you pass --force, so re-running
the installer can't wipe real donor data by accident.

Inputs (all via environment, so the installer can drive it non-interactively):
  ADMIN_USERNAME      required   login name for the first admin
  ADMIN_PASSWORD      required   plaintext password (hashed before storage)
  ADMIN_DISPLAY_NAME  optional   defaults to the username
  ADMIN_EMAIL         optional   defaults to empty

Usage:
  ADMIN_USERNAME=ryan ADMIN_PASSWORD=... python scripts/init_db.py
  python scripts/init_db.py --force      # rebuild even if the DB exists
"""
import os
import sys
import sqlite3
from werkzeug.security import generate_password_hash

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "donor_crm.sqlite")
SCHEMA = os.path.join(BASE, "db", "schema.sql")
LOOKUPS = os.path.join(BASE, "db", "seed_lookups.sql")


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    force = "--force" in sys.argv[1:]

    username = os.environ.get("ADMIN_USERNAME", "").strip()
    password = os.environ.get("ADMIN_PASSWORD", "")
    display = os.environ.get("ADMIN_DISPLAY_NAME", "").strip() or username
    email = os.environ.get("ADMIN_EMAIL", "").strip() or None

    if not username:
        fail("ADMIN_USERNAME is required.")
    if not password:
        fail("ADMIN_PASSWORD is required.")
    if username == "system":
        fail("'system' is reserved for the built-in import user; pick another name.")

    if os.path.exists(DB):
        if not force:
            fail(f"{DB} already exists. Refusing to overwrite real data. "
                 "Pass --force only if you intend to rebuild from scratch.")
        os.remove(DB)

    for path in (SCHEMA, LOOKUPS):
        if not os.path.exists(path):
            fail(f"missing required SQL file: {path}")

    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    try:
        with open(SCHEMA) as f:
            db.executescript(f.read())
        with open(LOOKUPS) as f:
            db.executescript(f.read())

        # py3.9's hashlib has no scrypt (werkzeug's default), so pin pbkdf2:sha256.
        pw_hash = generate_password_hash(password, method="pbkdf2:sha256")
        db.execute(
            "INSERT INTO users (username, display_name, email, role, password_hash) "
            "VALUES (?,?,?,?,?)",
            (username, display, email, "admin", pw_hash),
        )
        db.commit()
    finally:
        db.close()

    print("-" * 60)
    print("  Database initialized (schema + lookups + admin account).")
    print(f"  Location:  {DB}")
    print(f"  Admin login:  {username}")
    print("  No demo donor data was loaded — this database is empty and")
    print("  ready for real imports.")
    print("-" * 60)


if __name__ == "__main__":
    main()
