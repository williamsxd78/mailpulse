"""Pure email-verification logic: syntax, MX, and proxy-aware SMTP mailbox probing.
No database access lives here so it can be reused by both quick and bulk flows.
"""
import re
import os
import time
import random
import string
import smtplib
from pathlib import Path
from dotenv import load_dotenv
import dns.resolver
import socks

load_dotenv(Path(__file__).parent / ".env")

MAX_WORKERS = 10

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9]"
                         r"(?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
                         r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$")

# Un-anchored: pulls the email out of combo lines like "email:pass" or "url:email:pass".
EMAIL_SEARCH = re.compile(r"[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9]"
                          r"(?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
                          r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+")


def extract_email(line: str) -> str:
    """Pick only the email from a line, dropping any :password / delimiters."""
    m = EMAIL_SEARCH.search(line)
    return m.group(0) if m else line


DISPOSABLE_DOMAINS = {
    "mailinator.com", "10minutemail.com", "guerrillamail.com", "guerrillamail.info",
    "trashmail.com", "yopmail.com", "tempmail.com", "temp-mail.org", "getnada.com",
    "throwaway.email", "maildrop.cc", "dispostable.com", "fakeinbox.com", "sharklasers.com",
    "grr.la", "spam4.me", "mailnesia.com", "mailcatch.com", "tempinbox.com", "mohmal.com",
    "emailondeck.com", "moakt.com", "burnermail.io", "tempr.email", "33mail.com",
    "mytemp.email", "1secmail.com", "einrot.com", "discard.email", "gettempmail.com",
}

ROLE_PREFIXES = {
    "admin", "administrator", "support", "info", "sales", "contact", "help", "team",
    "office", "hello", "billing", "abuse", "postmaster", "webmaster", "noreply",
    "no-reply", "marketing", "hr", "jobs", "careers", "service", "enquiries", "inquiries",
    "root", "security", "sysadmin", "hostmaster",
}

TYPO_DOMAINS = {
    "gmial.com": "gmail.com", "gmai.com": "gmail.com", "gmail.co": "gmail.com",
    "gnail.com": "gmail.com", "gmail.con": "gmail.com", "gamil.com": "gmail.com",
    "gmali.com": "gmail.com", "gmaill.com": "gmail.com", "gmail.cm": "gmail.com",
    "hotmial.com": "hotmail.com", "hotmai.com": "hotmail.com", "hotmail.co": "hotmail.com",
    "hotnail.com": "hotmail.com", "yaho.com": "yahoo.com", "yahooo.com": "yahoo.com",
    "yahoo.co": "yahoo.com", "yhoo.com": "yahoo.com", "outlok.com": "outlook.com",
    "outllok.com": "outlook.com", "outllook.com": "outlook.com", "outlook.co": "outlook.com",
    "hotmail.con": "hotmail.com",
}

MAIL_FROM = os.environ.get("SMTP_MAIL_FROM", "verify@mailpulse.io")
HELO_NAME = os.environ.get("SMTP_HELO_NAME", "mailpulse.io")

NOT_FOUND_HINTS = (
    "does not exist", "doesn't exist", "no such user", "user unknown", "unknown user",
    "user not found", "recipient not found", "no mailbox", "mailbox not found",
    "invalid recipient", "invalid mailbox", "address rejected", "recipient rejected",
    "account that you tried to reach", "recipient address rejected", "no such recipient",
    "unrouteable address", "unknown recipient",
)
BLOCK_HINTS = (
    "blocked", "blacklist", "spamhaus", "spam", "denied", "reputation", "policy",
    "greylist", "grey list", "rate limit", "too many", "try again", "temporarily",
    "service unavailable", "not authorized", "access denied", "barracuda",
)

_resolver = dns.resolver.Resolver()
_resolver.timeout = 4
_resolver.lifetime = 4
_mx_cache: dict = {}

_SOCKS_TYPES = {"socks5": socks.SOCKS5, "socks4": socks.SOCKS4, "http": socks.HTTP}


def check_mx(domain: str):
    if domain in _mx_cache:
        return _mx_cache[domain]
    result = (False, None)
    try:
        answers = _resolver.resolve(domain, "MX")
        hosts = sorted([(r.preference, str(r.exchange).rstrip('.')) for r in answers])
        if hosts:
            result = (True, hosts[0][1])
    except Exception:
        try:
            _resolver.resolve(domain, "A")
            result = (True, None)
        except Exception:
            result = (False, None)
    _mx_cache[domain] = result
    return result


def _random_local(n=14):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def smtp_connect(mx_host, timeout=12, proxy=None):
    """Return a connected smtplib.SMTP, optionally routed through a SOCKS/HTTP proxy."""
    if not proxy:
        return smtplib.SMTP(mx_host, 25, local_hostname=HELO_NAME, timeout=timeout)

    ptype = _SOCKS_TYPES.get((proxy.get("type") or "socks5").lower(), socks.SOCKS5)
    sock = socks.socksocket()
    sock.set_proxy(ptype, proxy["host"], int(proxy["port"]),
                   username=(proxy.get("username") or None),
                   password=(proxy.get("password") or None))
    sock.settimeout(timeout)
    sock.connect((mx_host, 25))
    s = smtplib.SMTP(local_hostname=HELO_NAME, timeout=timeout)
    s.sock = sock
    s.file = None
    code, msg = s.getreply()
    if code != 220:
        try:
            s.close()
        except Exception:
            pass
        raise smtplib.SMTPConnectError(code, msg)
    s._host = mx_host
    return s


def _probe(server, addr):
    try:
        server.rset()
    except Exception:
        pass
    server.mail(MAIL_FROM)
    code, msg = server.rcpt(addr)
    text = msg.decode(errors="replace") if isinstance(msg, bytes) else str(msg)
    return code, text


def _classify_smtp(out, code, text, catch_all):
    low = (text or "").lower()
    if code in (250, 251):
        if catch_all:
            out.update(status="catch_all", category="deliverable",
                       reason="Catch-all domain — accepts all mail, exact mailbox unconfirmed")
            out["tags"].append("Catch-All")
        else:
            out.update(status="deliverable", category="deliverable",
                       reason="Mailbox verified via SMTP")
            out["tags"].append("Mailbox Verified")
    elif code is not None and 500 <= code < 600 and (
        any(h in low for h in NOT_FOUND_HINTS) or (code in (550, 551, 553) and not any(b in low for b in BLOCK_HINTS))
    ):
        out.update(status="mailbox_not_found", category="invalid",
                   reason=f"Mailbox does not exist ({code})")
        out["tags"] = ["Mailbox Not Found"]
    elif code is not None and 400 <= code < 500:
        out.update(status="greylisted", category="deliverable",
                   reason="Greylisted — server asked to retry later; re-check this address after a while")
        out["tags"].append("Greylisted")
    else:
        out.update(status="unknown", category="deliverable",
                   reason="Mailbox could not be verified (server greylisted or blocked the probe)")
        out["tags"].append("Unverified")
    return out


def _mx_only_classify(out, local):
    out["tags"] = ["MX Active"]
    if local in ROLE_PREFIXES:
        out.update(status="risky", category="deliverable",
                   reason="Role address; domain MX active (mailbox not probed)")
        out["tags"].append("Role Account")
    else:
        out.update(status="deliverable", category="deliverable",
                   reason="Valid syntax and active MX record (mailbox not probed)")
        out["tags"].insert(0, "Syntax Valid")
    if out.get("suggestion"):
        out["tags"].append("Possible Typo")


def _verify_domain(domain, keys, results_map, smtp_check, proxy=None):
    has_mx, mx_host = check_mx(domain)
    if not has_mx:
        for k in keys:
            out = results_map[k]
            out.update(status="no_mx", category="invalid", reason="No MX record found for domain")
            out["tags"] = ["No MX Record"]
        return

    for k in keys:
        results_map[k]["mx"] = mx_host

    if not smtp_check or not mx_host:
        for k in keys:
            _mx_only_classify(results_map[k], results_map[k]["_local"])
        return

    # Try proxy first (if given), then a direct connection as fallback.
    attempts = [proxy, None] if proxy else [None]
    server = None
    for attempt in attempts:
        try:
            server = smtp_connect(mx_host, 12, attempt)
            server.ehlo_or_helo_if_needed()
            break
        except Exception:
            if server:
                try:
                    server.close()
                except Exception:
                    pass
            server = None
    if server is None:
        for k in keys:
            _mx_only_classify(results_map[k], results_map[k]["_local"])
        return

    try:
        catch_all = False
        try:
            code, _ = _probe(server, f"{_random_local()}@{domain}")
            if code in (250, 251):
                catch_all = True
        except Exception:
            pass
        for k in keys:
            out = results_map[k]
            out["tags"] = ["MX Active"]
            if out["_local"] in ROLE_PREFIXES:
                out["tags"].append("Role Account")
            try:
                code, text = _probe(server, k)
            except Exception as ex:
                code, text = None, str(ex)
            _classify_smtp(out, code, text, catch_all)
            if out.get("suggestion"):
                out["tags"].append("Possible Typo")
        try:
            server.quit()
        except Exception:
            pass
    except Exception:
        for k in keys:
            out = results_map[k]
            if not out.get("status") or out["status"] == "invalid":
                _mx_only_classify(out, out["_local"])
        try:
            server.close()
        except Exception:
            pass


def _prevalidate(email, out):
    """Fast checks. Returns (needs_smtp, domain, local)."""
    key = email.lower()
    if "@" not in key or not EMAIL_REGEX.match(key):
        out.update(status="invalid_syntax", reason="Malformed email syntax")
        out["tags"] = ["Invalid Syntax"]
        return False, None, None
    local, domain = key.rsplit("@", 1)
    if domain in TYPO_DOMAINS:
        suggestion = f"{local}@{TYPO_DOMAINS[domain]}"
        out["suggestion"] = suggestion
        out.update(status="typo", category="invalid",
                   reason=f"Misspelled domain — did you mean {suggestion}?")
        out["tags"] = ["Possible Typo"]
        return False, None, None
    if domain in DISPOSABLE_DOMAINS:
        out.update(status="disposable", reason="Disposable / throwaway domain")
        out["tags"] = ["Disposable Domain"]
        return False, None, None
    return True, domain, local


def verify_batch(emails, smtp_check=True, proxies=None):
    """Verify a list of already-parsed emails, grouped by domain, with a thread
    pool for per-domain concurrency. Returns result dicts in input order.
    """
    from concurrent.futures import ThreadPoolExecutor
    results_map = {}
    order = []
    for e in emails:
        e = extract_email(e.strip())
        if not e:
            continue
        key = e.lower()
        order.append(key)
        out = {"email": e.strip(), "status": "invalid", "category": "invalid",
               "reason": "", "tags": [], "mx": None, "suggestion": None}
        results_map[key] = out
        needs_smtp, domain, local = _prevalidate(e, out)
        if needs_smtp:
            out["_domain"] = domain
            out["_local"] = local

    domains = {}
    for k in order:
        out = results_map[k]
        if "_domain" in out:
            domains.setdefault(out["_domain"], []).append(k)

    def work(item):
        domain, keys = item
        proxy = random.choice(proxies) if proxies else None
        _verify_domain(domain, keys, results_map, smtp_check, proxy)

    if domains:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            list(pool.map(work, domains.items()))

    final = []
    for k in order:
        out = results_map[k]
        out.pop("_domain", None)
        out.pop("_local", None)
        final.append(out)
    return final


async def validate_emails(emails, dedupe=True, smtp_check=True, proxies=None):
    """Async quick-mode validator: dedupe + concurrent per-domain verification."""
    import asyncio
    results_map = {}
    order = []
    seen = set()
    for e in emails:
        e = extract_email(e.strip())
        if not e:
            continue
        key = e.lower()
        if dedupe and key in seen:
            continue
        seen.add(key)
        order.append(key)
        out = {"email": e.strip(), "status": "invalid", "category": "invalid",
               "reason": "", "tags": [], "mx": None, "suggestion": None}
        results_map[key] = out
        needs_smtp, domain, local = _prevalidate(e, out)
        if needs_smtp:
            out["_domain"] = domain
            out["_local"] = local

    domains = {}
    for k in order:
        out = results_map[k]
        if "_domain" in out:
            domains.setdefault(out["_domain"], []).append(k)

    sem = asyncio.Semaphore(MAX_WORKERS)

    async def process(domain, keys):
        proxy = random.choice(proxies) if proxies else None
        async with sem:
            await asyncio.to_thread(_verify_domain, domain, keys, results_map, smtp_check, proxy)

    await asyncio.gather(*[process(d, ks) for d, ks in domains.items()])

    final = []
    for k in order:
        out = results_map[k]
        out.pop("_domain", None)
        out.pop("_local", None)
        final.append(out)
    return final


def test_proxy_smtp(proxy=None, target_domain="gmail.com"):
    """Check whether a proxy (or direct, if proxy is None) can reach an MX on port 25."""
    start = time.time()
    has_mx, mx = check_mx(target_domain)
    if not mx:
        return {"ok": False, "port25": False, "latency_ms": 0,
                "message": f"Could not resolve MX for {target_domain}", "mx": None}
    server = None
    try:
        server = smtp_connect(mx, 15, proxy)
        server.ehlo_or_helo_if_needed()
        try:
            server.quit()
        except Exception:
            pass
        return {"ok": True, "port25": True, "latency_ms": int((time.time() - start) * 1000),
                "message": f"Connected to {mx} on port 25 — SMTP verification supported.", "mx": mx}
    except Exception as ex:
        if server:
            try:
                server.close()
            except Exception:
                pass
        return {"ok": False, "port25": False, "latency_ms": int((time.time() - start) * 1000),
                "message": f"{type(ex).__name__}: {ex}", "mx": mx}
