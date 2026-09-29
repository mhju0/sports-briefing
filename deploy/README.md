# Single-host deployment runbook

Status: **prepared, not deployed.** No server has been provisioned yet.

This deploys the API as a small, always-on public demo: one Linux VM, Caddy for HTTPS, one Uvicorn process supervised by systemd, and SQLite on local disk with daily backups. It deliberately has no containers, orchestration, managed database or deployment automation. Those can follow once a manual deployment has worked.

```text
Internet ──HTTPS──> Caddy :443 ──> Uvicorn 127.0.0.1:8000 (systemd) ──> SQLite /var/lib/sports-briefing
```

## Data policy for the first deployment

The server runs with `SPORTS_BRIEFING_PUBLIC_MODE=true` and **no provider credentials**:

- **Arsenal** is unavailable until football-data.org confirms public display and caching.
- **Texans and Scottie** show labelled synthetic demo items only, and Sportradar is never called.
- **No LLM**: there is no external inference.
- **No ingestion timers**: none are installed until a source is cleared. Future timers would sit beside the backup timer as `sports-briefing-ingest-<source>.timer`.

In public mode the web process only reads SQLite, and nothing writes to it. The database file therefore does not exist until an ingestion source is enabled, and the backup job reports "nothing to back up" until then.

## Files

| File | Installed as |
| --- | --- |
| `sports-briefing.service` | `/etc/systemd/system/sports-briefing.service` |
| `sports-briefing-backup.service`, `sports-briefing-backup.timer` | `/etc/systemd/system/` |
| `sports-briefing.env.example` | `/etc/sports-briefing.env` (root:sports-briefing, `0640`) |
| `Caddyfile.example` | `/etc/caddy/Caddyfile` |
| `backup.sh` | run in place from the checkout |
| `smoke_check.sh` | run in place against the local or public URL |

Conventions used by the units:
- service user `sports-briefing`, with no login and no sudo;
- checkout at `/opt/sports-briefing`, owned by your admin user and read-only for the service;
- state in `/var/lib/sports-briefing`.

If you change any of these, change them in every unit.

## Why one process

SQLite and this application are single-node by design. Each request opens a short-lived connection, the public web path is read-only, and writes only ever come from the CLI. One Uvicorn process is enough for this traffic, and extra workers would add nothing but memory use. systemd restarts the process on failure.

SQLite settings are left at the application's defaults:
- rollback journal, not WAL;
- Python's default 5-second busy timeout;
- foreign keys enabled by the news storage code.

With one reader process and occasional CLI writes, there is no measured reason to change them. `backup.sh` uses SQLite's online backup API, so it is consistent in either journal mode.

`/health` returns a static `{"status": "ok"}` and touches neither the database nor any provider. That is intentional for external uptime checks: a missing or empty database is a normal public-mode state, not an outage. Use `smoke_check.sh` for the deeper check.

## Initial server setup

These steps assume Ubuntu 24.04 LTS and a sudo-capable admin user logged in over SSH with a key. Ubuntu 24.04 ships Python 3.12, which satisfies the project's `>=3.11` requirement; CI tests 3.11, so run the test suite once on the server before starting the service.

Baseline security:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y unattended-upgrades && sudo dpkg-reconfigure -plow unattended-upgrades
# Key-only SSH: set `PasswordAuthentication no` and `PermitRootLogin prohibit-password` (or `no`)
sudoedit /etc/ssh/sshd_config && sudo systemctl reload ssh
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw enable
```

Port 8000 stays closed: Uvicorn binds only to `127.0.0.1`.

Packages, service user and checkout:

```bash
sudo apt install -y python3 python3-venv git sqlite3
# Caddy: follow https://caddyserver.com/docs/install#debian-ubuntu-raspbian (official apt repository)
sudo useradd --system --home-dir /var/lib/sports-briefing --shell /usr/sbin/nologin sports-briefing
sudo install -d -o sports-briefing -g sports-briefing -m 0750 /var/lib/sports-briefing
sudo install -d -o "$USER" -g "$USER" -m 0755 /opt/sports-briefing
git clone https://github.com/mhju0/sports-briefing.git /opt/sports-briefing
cd /opt/sports-briefing
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests
```

## Application setup

```bash
cd /opt/sports-briefing
sudo install -o root -g sports-briefing -m 0640 deploy/sports-briefing.env.example /etc/sports-briefing.env
sudo install -m 0644 deploy/sports-briefing.service deploy/sports-briefing-backup.service \
  deploy/sports-briefing-backup.timer /etc/systemd/system/
sudo install -m 0644 deploy/Caddyfile.example /etc/caddy/Caddyfile
sudoedit /etc/caddy/Caddyfile   # replace briefing.example.com with the real hostname
sudo systemd-analyze verify /etc/systemd/system/sports-briefing*.service
sudo caddy validate --config /etc/caddy/Caddyfile
```

The environment file contains only non-secret settings. Never add provider keys to it until their public use is cleared in [the rights matrix](../docs/feasibility.md#public-deployment-rights-checked-2026-09-27).

## Start

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sports-briefing.service sports-briefing-backup.timer
sudo systemctl reload caddy
```

Caddy obtains the HTTPS certificate once DNS for the hostname points at the server and ports 80/443 are open.

## Verify

```bash
deploy/smoke_check.sh http://127.0.0.1:8000           # on the server
deploy/smoke_check.sh https://briefing.example.com    # public URL, from anywhere
systemctl status sports-briefing
systemctl list-timers sports-briefing-backup.timer
```

The smoke check asserts:
- `/health` is ok;
- `/meta` reports public mode, with Arsenal `unavailable` and Texans/Scottie `demo`;
- every `/timeline` item carries `data_mode: "demo"` and its demo labels.

## Logs

The app logs to journald; no external logging service is used. The public deployment holds no credentials to leak into logs.

```bash
systemctl status sports-briefing
journalctl -u sports-briefing --since today
journalctl -u sports-briefing -f
journalctl -u sports-briefing-backup
```

Uvicorn's access log records client IPs, which Caddy forwards and Uvicorn trusts only from localhost.

## Backups

- **Schedule:** `sports-briefing-backup.timer` runs `backup.sh` daily, with a random delay of up to 15 minutes. `Persistent=true` catches up after downtime.
- **Output:** `/var/lib/sports-briefing/backups/sports_briefing-<UTC stamp>.sqlite3`, owned by `sports-briefing` with mode `0640`. The newest 14 are kept; set `SPORTS_BRIEFING_BACKUP_KEEP` in the environment file to change this.
- **Method:**
  1. `sqlite3 .backup` (the online backup API) into a temporary file;
  2. `PRAGMA integrity_check`;
  3. an atomic rename.

  Any failure exits non-zero, so the systemd unit shows as failed.
- **Contents:** the database only. The environment file holds no secrets and is not backed up.
- **Manual run:** `sudo systemctl start sports-briefing-backup.service`, then check `journalctl -u sports-briefing-backup`.
- **Second layer:** backups sit on the same disk. Enable the host provider's VM backups as the second layer; off-host copies are a later step.

## Restore

```bash
STATE=/var/lib/sports-briefing
BACKUP=$STATE/backups/sports_briefing-<UTC stamp>.sqlite3   # pick from: ls $STATE/backups
sudo systemctl stop sports-briefing
sudo -u sports-briefing mv $STATE/sports_briefing.sqlite3 $STATE/sports_briefing.sqlite3.pre-restore-$(date -u +%Y%m%dT%H%M%SZ)
sudo -u sports-briefing cp "$BACKUP" $STATE/sports_briefing.sqlite3
sudo -u sports-briefing sqlite3 $STATE/sports_briefing.sqlite3 'PRAGMA integrity_check;'   # must print: ok
sudo systemctl start sports-briefing
/opt/sports-briefing/deploy/smoke_check.sh http://127.0.0.1:8000
```

If a `sports_briefing.sqlite3-journal` file exists next to the database, move it aside with the old database; never pair it with the restored file. This sequence was rehearsed locally against a service-like Uvicorn run: backup, stop, restore, integrity check, restart, then a smoke check and a readback of the restored data.

## Update

```bash
cd /opt/sports-briefing
git rev-parse HEAD > ~/sports-briefing.last-good
git fetch origin && git checkout main && git merge --ff-only origin/main
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests
sudo systemctl restart sports-briefing
deploy/smoke_check.sh http://127.0.0.1:8000
```

If a unit file in `deploy/` changed, reinstall it and run `sudo systemctl daemon-reload` before restarting. Restarts cause a few seconds of downtime; zero-downtime deploys are out of scope.

## Rollback

```bash
cd /opt/sports-briefing
git checkout --detach "$(cat ~/sports-briefing.last-good)"
.venv/bin/python -m pip install -r requirements-dev.txt
sudo systemctl restart sports-briefing
deploy/smoke_check.sh http://127.0.0.1:8000
```

Return to `main` with `git checkout main` once the fix is released. Restore the database from a backup only if a release changed stored data.

## Cost envelope

The planning budget is **$10–25/month** in total and owner-funded:
- one small VM (for example a Hetzner Cloud CX23-class instance, EU region) with provider backups;
- optionally, a domain later;
- a free external uptime check against `/health`.

It includes no paid sports provider and no LLM cost. Check current prices when provisioning.

## Version note

`/meta` reports `0.2.0` from the API, while `pyproject.toml` still says `0.1.0`. History does not settle which is intended, so the mismatch is left for a separate decision.
