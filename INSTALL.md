# MailPulse — VPS install

A self-hosted email validator: syntax + MX + live SMTP mailbox verification,
bulk background jobs (upload → progress → download CSV), pause/resume, proxy
rotation, and per-browser private history.

## One-command install (Ubuntu 22.04 / 24.04 or Debian 12)

```bash
# 1. copy this whole project folder to your VPS (scp / git clone / rsync)
# 2. from inside the project folder:
sudo bash install.sh
```

Then open `http://YOUR_SERVER_IP/`.

### Optional overrides

```bash
sudo SERVER_NAME=verify.mydomain.com \
     SMTP_HELO_NAME=mydomain.com \
     SMTP_MAIL_FROM=verifier@mydomain.com \
     DB_NAME=mailpulse \
     bash install.sh
```

## What it sets up
- **MongoDB 7** (local), **Python venv** + FastAPI backend on a systemd service
  `mailpulse` (single worker — required for background jobs / pause-resume).
- **React frontend** built to static files, served by **Nginx** same-origin with
  `/api` reverse-proxied to the backend. `client_max_body_size 2G` for big uploads.
- Firewall opens 22/80/443, and an **outbound port-25 check** for SMTP verification.

## Useful commands
```bash
systemctl status mailpulse         # backend status
journalctl -u mailpulse -f         # backend logs
systemctl restart mailpulse        # after editing backend/.env
systemctl status mongod nginx
```

## HTTPS (recommended)
```bash
apt-get install -y certbot python3-certbot-nginx
certbot --nginx        # needs SERVER_NAME set to a real domain
```

## Accurate Yahoo / AOL / iCloud results
These providers require a clean IP with **FCrDNS** (matching forward + reverse DNS),
SPF and DMARC on the domain you use in `SMTP_HELO_NAME` / `SMTP_MAIL_FROM`.
See the in-app **Proxies → Setup guide** for the full checklist. Without it,
those providers rate-limit/greylist probes (shown as amber "Unverified"/"Greylisted"),
which is expected — not a bug.
