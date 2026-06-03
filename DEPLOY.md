# Deploying the Always & Furever Donor CRM

This app holds donor PII. Treat hosting it like hosting a small bank: HTTPS
only, never the dev server, never debug mode on the public internet.

## 1. Install

    python3 -m venv venv
    . venv/bin/activate
    pip install -r requirements.txt

## 2. Configure secrets

    cp .env.example .env
    python -c "import secrets; print(secrets.token_hex(32))"   # paste into SECRET_KEY
    # edit .env: set SECRET_KEY, keep CRM_BEHIND_PROXY=1 (see below)

Load it before running:  `set -a; . ./.env; set +a`

The app refuses to use a stable session key unless SECRET_KEY is set — it
will warn and generate an ephemeral key (logging everyone out on restart)
until you provide one.

## 3. Seed the database

    python seed_demo.py

This prints the demo login (username `ksmith`). Override the password first
with `SEED_ADMIN_PASSWORD` if you like. For a real deployment, replace the
demo donors with a real import and create real staff accounts.

## 4. Run behind a real server

Never expose Flask's dev server. Use gunicorn bound to localhost:

    gunicorn -w 3 -b 127.0.0.1:8000 app:app

## 5. Terminate TLS at a reverse proxy

Put nginx or Caddy in front, terminating HTTPS and forwarding to gunicorn.
Set `CRM_BEHIND_PROXY=1` so ProxyFix trusts the X-Forwarded-* headers and
the Secure cookie flag works.

Caddy (automatic HTTPS):

    crm.example.org {
        reverse_proxy 127.0.0.1:8000
    }

nginx (essentials):

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

## Security checklist before going live

- [ ] SECRET_KEY set to a strong random value, kept out of git
- [ ] HTTPS enforced; HTTP redirects to HTTPS at the proxy
- [ ] CRM_BEHIND_PROXY=1; FLASK_DEBUG unset; CRM_INSECURE_COOKIES unset
- [ ] Demo admin password changed; demo donor data replaced
- [ ] Database file (donor_crm.sqlite) not web-served and backed up
- [ ] .env never committed (already in .gitignore)

## What the app enforces in code

- Authentication: every route except /login and static requires a session
- Passwords: werkzeug hashing (pbkdf2); constant-time check; no username
  enumeration via timing
- CSRF: per-session token required on all POSTs
- Login rate limiting: throttles repeated failed attempts per IP+username
- Security headers: CSP, X-Frame-Options, X-Content-Type-Options,
  Referrer-Policy
- Cookies: HttpOnly, SameSite=Lax, Secure (unless CRM_INSECURE_COOKIES=1)
- Debug off by default (no Werkzeug console on the web)
