#!/usr/bin/env bash
#
# Always & Furever Donor CRM — VPS installer
# =============================================================================
# One-liner:
#   curl -fsSL https://raw.githubusercontent.com/rkweekley/alwaysandfurever-donor-crm/main/install.sh | bash
#
# What it does:
#   1. Installs system deps (python3, venv, git) via the OS package manager
#   2. Clones (or updates) the repo into an install directory
#   3. Creates a virtualenv and installs Python dependencies
#   4. Walks you through setup: admin account, domain, port, demo-vs-real data
#   5. Generates a strong SECRET_KEY and writes .env
#   6. Initializes the database (real admin OR demo data, your choice)
#   7. Optionally installs a systemd service (gunicorn) and a Caddy site for
#      automatic HTTPS
#
# Safe to re-run: it won't overwrite an existing database unless you say so.
# This script holds no secrets; everything you type stays on your server.
# =============================================================================
set -euo pipefail

REPO_URL="https://github.com/rkweekley/alwaysandfurever-donor-crm.git"
DEFAULT_DIR="/opt/alwaysandfurever-crm"

# ---- pretty output ---------------------------------------------------------
bold()  { printf "\033[1m%s\033[0m\n" "$*"; }
green() { printf "\033[1;32m%s\033[0m\n" "$*"; }
yellow(){ printf "\033[1;33m%s\033[0m\n" "$*"; }
red()   { printf "\033[1;31m%s\033[0m\n" "$*"; }
hr()    { printf '%s\n' "----------------------------------------------------------------"; }

ask() {  # ask "Prompt" "default" -> echoes answer
    local prompt="$1" default="${2:-}" reply
    if [ -n "$default" ]; then
        read -r -p "$prompt [$default]: " reply </dev/tty || true
        echo "${reply:-$default}"
    else
        read -r -p "$prompt: " reply </dev/tty || true
        echo "$reply"
    fi
}

ask_secret() {  # ask_secret "Prompt" -> echoes hidden input
    local prompt="$1" reply
    read -r -s -p "$prompt: " reply </dev/tty || true
    echo >/dev/tty
    echo "$reply"
}

ask_yn() {  # ask_yn "Prompt" "y|n" -> returns 0 for yes
    local prompt="$1" default="${2:-n}" reply
    local hint="[y/N]"; [ "$default" = "y" ] && hint="[Y/n]"
    read -r -p "$prompt $hint: " reply </dev/tty || true
    reply="${reply:-$default}"
    case "$reply" in [Yy]*) return 0 ;; *) return 1 ;; esac
}

need_root_for() {  # returns 0 if we can sudo/are root, for system-level steps
    [ "$(id -u)" = "0" ] || command -v sudo >/dev/null 2>&1
}

SUDO=""
[ "$(id -u)" = "0" ] || SUDO="sudo"

# ---- 0. intro --------------------------------------------------------------
clear || true
hr
bold "  Always & Furever — Donor CRM installer"
hr
echo "This will set up the CRM on this server. It holds donor PII, so the"
echo "installer defaults to a secure configuration (HTTPS, hardened cookies,"
echo "no debug). You'll answer a few questions; nothing leaves this machine."
echo
echo "You can press Ctrl-C any time. Re-running is safe."
echo
ask_yn "Ready to begin?" "y" || { echo "Aborted."; exit 0; }

# ---- 1. system dependencies ------------------------------------------------
hr; bold "Step 1 / 7 — System dependencies"
install_pkgs() {
    if command -v apt-get >/dev/null 2>&1; then
        $SUDO apt-get update -qq
        $SUDO apt-get install -y -qq python3 python3-venv python3-pip git curl
    elif command -v dnf >/dev/null 2>&1; then
        $SUDO dnf install -y -q python3 python3-pip git curl
    elif command -v yum >/dev/null 2>&1; then
        $SUDO yum install -y -q python3 python3-pip git curl
    elif command -v apk >/dev/null 2>&1; then
        $SUDO apk add --no-cache python3 py3-pip git curl
    else
        yellow "Could not detect a supported package manager."
        yellow "Make sure python3 (3.9+), pip, venv and git are installed, then re-run."
        command -v python3 >/dev/null 2>&1 || { red "python3 not found — cannot continue."; exit 1; }
    fi
}
if need_root_for; then
    install_pkgs
    green "System dependencies ready."
else
    yellow "Not root and no sudo — skipping system package install."
    yellow "Assuming python3, venv and git are already present."
fi

# ---- 2. clone / update repo ------------------------------------------------
hr; bold "Step 2 / 7 — Application files"
INSTALL_DIR="$(ask "Install directory" "$DEFAULT_DIR")"
if [ ! -d "$INSTALL_DIR/.git" ]; then
    if [ -e "$INSTALL_DIR" ] && [ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null || true)" ]; then
        red "$INSTALL_DIR exists and is not empty. Choose another directory or clear it."
        exit 1
    fi
    $SUDO mkdir -p "$INSTALL_DIR"
    $SUDO chown "$(id -un)":"$(id -gn)" "$INSTALL_DIR" 2>/dev/null || true
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
else
    bold "Repo already present — pulling latest."
    git -C "$INSTALL_DIR" pull --ff-only || yellow "Could not fast-forward; keeping existing checkout."
fi
cd "$INSTALL_DIR"
green "Application files in $INSTALL_DIR"

# ---- 3. python virtualenv --------------------------------------------------
hr; bold "Step 3 / 7 — Python environment"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
. .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
green "Virtualenv ready (Flask, Werkzeug, gunicorn installed)."

# ---- 4. setup walkthrough --------------------------------------------------
hr; bold "Step 4 / 7 — Configuration walkthrough"
echo

bold "Admin account (your first login):"
ADMIN_USERNAME=""
while [ -z "$ADMIN_USERNAME" ] || [ "$ADMIN_USERNAME" = "system" ]; do
    ADMIN_USERNAME="$(ask "  Admin username" "admin")"
    [ "$ADMIN_USERNAME" = "system" ] && yellow "  'system' is reserved — pick another."
done
ADMIN_DISPLAY_NAME="$(ask "  Display name" "$ADMIN_USERNAME")"
ADMIN_EMAIL="$(ask "  Admin email (optional)" "")"

ADMIN_PASSWORD=""
while true; do
    ADMIN_PASSWORD="$(ask_secret "  Admin password (min 8 chars, hidden)")"
    if [ "${#ADMIN_PASSWORD}" -lt 8 ]; then
        yellow "  Too short — use at least 8 characters."; continue
    fi
    CONFIRM="$(ask_secret "  Confirm password")"
    [ "$ADMIN_PASSWORD" = "$CONFIRM" ] && break
    yellow "  Passwords did not match — try again."
done
green "  Admin account captured."
echo

bold "Hosting:"
DOMAIN="$(ask "  Domain name (blank = IP/localhost only, no auto-HTTPS)" "")"
BIND_PORT="$(ask "  Local port for the app server (gunicorn)" "8000")"
WORKERS="$(ask "  Gunicorn worker processes" "3")"
echo

bold "Reverse proxy / HTTPS:"
BEHIND_PROXY="1"
INSECURE_COOKIES=""
if [ -n "$DOMAIN" ]; then
    echo "  A domain was given, so the app will run behind an HTTPS reverse proxy."
    echo "  Secure cookies stay ON (CRM_BEHIND_PROXY=1)."
else
    if ask_yn "  No domain. Allow plain HTTP (insecure, local testing only)?" "n"; then
        INSECURE_COOKIES="1"; BEHIND_PROXY=""
        yellow "  Secure-cookie flag will be DROPPED. Do not expose this to the internet."
    fi
fi
echo

bold "Database / seed data:"
echo "  The app can start with either:"
echo "    - REAL setup only: empty database + lookups + your admin account"
echo "    - DEMO data: 10 fake donors and gifts so you can explore the UI first"
LOAD_DEMO="n"
if ask_yn "  Load demo data? (No = clean production database)" "n"; then
    LOAD_DEMO="y"
fi
echo

# ---- 5. write .env ---------------------------------------------------------
hr; bold "Step 5 / 7 — Writing configuration (.env)"
SECRET_KEY="$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
{
    echo "# Generated by install.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "SECRET_KEY=$SECRET_KEY"
    [ -n "$BEHIND_PROXY" ]     && echo "CRM_BEHIND_PROXY=1"
    [ -n "$INSECURE_COOKIES" ] && echo "CRM_INSECURE_COOKIES=1"
    echo "# FLASK_DEBUG stays unset — never enable on a public server."
} > .env
chmod 600 .env
green ".env written (SECRET_KEY generated, mode 600)."

# ---- 6. initialize database ------------------------------------------------
hr; bold "Step 6 / 7 — Initializing database"
DB_EXISTS=""; [ -f donor_crm.sqlite ] && DB_EXISTS="1"
if [ -n "$DB_EXISTS" ]; then
    yellow "A database already exists at donor_crm.sqlite."
    if ask_yn "  REBUILD it from scratch? This DELETES existing data." "n"; then
        FORCE="--force"
    else
        echo "  Keeping existing database. Skipping initialization."
        FORCE="SKIP"
    fi
else
    FORCE=""
fi

if [ "$FORCE" != "SKIP" ]; then
    if [ "$LOAD_DEMO" = "y" ]; then
        SEED_ADMIN_PASSWORD="$ADMIN_PASSWORD" .venv/bin/python seed_demo.py
        yellow "NOTE: demo data uses the built-in 'ksmith' admin. Your chosen password"
        yellow "      was applied to it. Replace demo donors before going live."
    else
        ADMIN_USERNAME="$ADMIN_USERNAME" \
        ADMIN_PASSWORD="$ADMIN_PASSWORD" \
        ADMIN_DISPLAY_NAME="$ADMIN_DISPLAY_NAME" \
        ADMIN_EMAIL="$ADMIN_EMAIL" \
        .venv/bin/python scripts/init_db.py ${FORCE}
    fi
fi
green "Database ready."

# ---- 7. service + proxy (optional) -----------------------------------------
hr; bold "Step 7 / 7 — Run as a service (optional)"
RUN_CMD=".venv/bin/gunicorn -w $WORKERS -b 127.0.0.1:$BIND_PORT app:app"
SERVICE_INSTALLED=""
if command -v systemctl >/dev/null 2>&1 && need_root_for; then
    if ask_yn "Install a systemd service so the CRM runs on boot?" "y"; then
        SVC_USER="$(id -un)"
        UNIT="/etc/systemd/system/furever-crm.service"
        $SUDO tee "$UNIT" >/dev/null <<UNITEOF
[Unit]
Description=Always & Furever Donor CRM
After=network.target

[Service]
Type=simple
User=$SVC_USER
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$INSTALL_DIR/.env
ExecStart=$INSTALL_DIR/$RUN_CMD
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
UNITEOF
        $SUDO systemctl daemon-reload
        $SUDO systemctl enable --now furever-crm.service
        SERVICE_INSTALLED="1"
        green "systemd service 'furever-crm' installed and started."
    fi
fi

# Caddy reverse proxy for automatic HTTPS
if [ -n "$DOMAIN" ] && need_root_for; then
    if ask_yn "Configure Caddy reverse proxy for automatic HTTPS on $DOMAIN?" "y"; then
        # Auto-install Caddy from the official apt repo if missing (Debian/Ubuntu).
        if ! command -v caddy >/dev/null 2>&1; then
            if command -v apt-get >/dev/null 2>&1; then
                yellow "Installing Caddy from the official repository..."
                $SUDO apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl >/dev/null 2>&1 || true
                curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
                    | $SUDO gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
                curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
                    | $SUDO tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
                $SUDO apt-get update >/dev/null 2>&1
                $SUDO apt-get install -y caddy >/dev/null 2>&1
            fi
        fi
        if ! command -v caddy >/dev/null 2>&1; then
            yellow "Caddy could not be installed automatically."
            yellow "Install it from https://caddyserver.com/docs/install then add to /etc/caddy/Caddyfile:"
            printf '\n%s {\n    encode zstd gzip\n    reverse_proxy 127.0.0.1:%s\n}\n\n' "$DOMAIN" "$BIND_PORT"
        else
            # Write a clean Caddyfile (overwrite, not append — idempotent across re-runs).
            CADDYFILE="/etc/caddy/Caddyfile"
            $SUDO tee "$CADDYFILE" >/dev/null <<CADDYEOF
$DOMAIN {
	encode zstd gzip
	reverse_proxy 127.0.0.1:$BIND_PORT
}
CADDYEOF
            $SUDO systemctl enable --now caddy >/dev/null 2>&1 || true
            $SUDO systemctl reload caddy 2>/dev/null || $SUDO systemctl restart caddy 2>/dev/null || true
            green "Caddy configured for https://$DOMAIN (Let's Encrypt cert auto-issued)."

            # Lock down the firewall: allow SSH + HTTP/HTTPS only. SSH first so we don't self-lock.
            if command -v ufw >/dev/null 2>&1; then
                if ask_yn "Enable the ufw firewall (allow SSH/80/443, deny the rest)?" "y"; then
                    $SUDO ufw allow 22/tcp   >/dev/null 2>&1
                    $SUDO ufw allow 80/tcp   >/dev/null 2>&1
                    $SUDO ufw allow 443/tcp  >/dev/null 2>&1
                    $SUDO ufw --force enable >/dev/null 2>&1
                    green "Firewall active: 22, 80, 443 open; gunicorn ($BIND_PORT) stays localhost-only."
                fi
            fi
        fi
    fi
fi

# ---- done ------------------------------------------------------------------
hr; green "  Installation complete."
hr
echo "Install dir:   $INSTALL_DIR"
echo "Admin login:   $([ "$LOAD_DEMO" = "y" ] && echo "ksmith (demo)" || echo "$ADMIN_USERNAME")"
echo "App server:    127.0.0.1:$BIND_PORT  (gunicorn, $WORKERS workers)"
if [ -n "$SERVICE_INSTALLED" ]; then
    echo "Service:       systemctl status furever-crm"
else
    echo "Start it:      cd $INSTALL_DIR && set -a; . ./.env; set +a; $RUN_CMD"
fi
if [ -n "$DOMAIN" ]; then
    echo "URL:           https://$DOMAIN"
else
    echo "URL:           http://127.0.0.1:$BIND_PORT  (local only)"
fi
hr
yellow "Security reminders:"
echo "  - Keep .env private (chmod 600 already applied)."
echo "  - Never set FLASK_DEBUG on a public server."
echo "  - Back up donor_crm.sqlite regularly; it holds donor PII."
[ "$LOAD_DEMO" = "y" ] && yellow "  - You loaded DEMO data — replace it before real use."
hr
