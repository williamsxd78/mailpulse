from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import re
import asyncio
import logging
import smtplib
import random
import string
from pathlib import Path
from pydantic import BaseModel, Field, field_validator
from pydantic_core import core_schema
from typing import List, Optional, Any, Annotated
from datetime import datetime, timezone
from bson import ObjectId
import dns.resolver

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI(title="Mail Pulse - Email Validator")
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MAX_WORKERS = 10  # fixed sensible concurrency for MX / SMTP lookups

# ---------------------------------------------------------------------------
# ObjectId helpers (BaseDocument pattern)
# ---------------------------------------------------------------------------

class PyObjectId(str):
    @classmethod
    def __get_pydantic_core_schema__(cls, source, handler):
        return core_schema.no_info_before_validator_function(cls.validate, core_schema.str_schema())

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return str(v)
        return str(v)


# ---------------------------------------------------------------------------
# Validation engine
# ---------------------------------------------------------------------------

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9]"
                         r"(?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
                         r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$")

# Un-anchored: pulls the email out of combo lines like "email:pass" or "url:email:pass".
EMAIL_SEARCH = re.compile(r"[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9]"
                          r"(?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
                          r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+")


def _extract_email(line: str) -> str:
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
    "gnail.com": "gmail.com", "gmail.con": "gmail.com", "hotmial.com": "hotmail.com",
    "hotmai.com": "hotmail.com", "yaho.com": "yahoo.com", "yahooo.com": "yahoo.com",
    "outlok.com": "outlook.com", "outllok.com": "outlook.com",
}

_resolver = dns.resolver.Resolver()
_resolver.timeout = 4
_resolver.lifetime = 4
_mx_cache: dict = {}


def _check_mx(domain: str):
    """Return (has_mx, mx_host or None). Cached per domain."""
    if domain in _mx_cache:
        return _mx_cache[domain]
    result = (False, None)
    try:
        answers = _resolver.resolve(domain, "MX")
        hosts = sorted([(r.preference, str(r.exchange).rstrip('.')) for r in answers])
        if hosts:
            result = (True, hosts[0][1])
    except Exception:
        # fallback: A record means domain accepts mail sometimes
        try:
            _resolver.resolve(domain, "A")
            result = (True, None)
        except Exception:
            result = (False, None)
    _mx_cache[domain] = result
    return result


# ---------------------------------------------------------------------------
# SMTP mailbox verification (RCPT TO probe)
# ---------------------------------------------------------------------------

MAIL_FROM = "verify@mailpulse.io"
HELO_NAME = "mailpulse.io"

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


def _random_local(n=14):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


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


def _verify_domain(domain, keys, results_map, smtp_check):
    """Runs in a worker thread. Resolves MX and (optionally) SMTP-probes every mailbox."""
    has_mx, mx_host = _check_mx(domain)
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
            out = results_map[k]
            _mx_only_classify(out, out["_local"])
        return

    server = None
    try:
        server = smtplib.SMTP(mx_host, 25, local_hostname=HELO_NAME, timeout=12)
        server.ehlo_or_helo_if_needed()
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
        # Connection-level failure: fall back to MX-only signal.
        for k in keys:
            out = results_map[k]
            _mx_only_classify(out, out["_local"])
        if server:
            try:
                server.close()
            except Exception:
                pass


async def validate_emails(emails: List[str], dedupe: bool, smtp_check: bool = True) -> List[dict]:
    results_map = {}
    order = []
    seen = set()
    for e in emails:
        e = _extract_email(e.strip())
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

        if "@" not in key or not EMAIL_REGEX.match(key):
            out.update(status="invalid_syntax", reason="Malformed email syntax")
            out["tags"] = ["Invalid Syntax"]
            continue
        local, domain = key.rsplit("@", 1)
        if domain in TYPO_DOMAINS:
            out["suggestion"] = f"{local}@{TYPO_DOMAINS[domain]}"
        if domain in DISPOSABLE_DOMAINS:
            out.update(status="disposable", reason="Disposable / throwaway domain")
            out["tags"] = ["Disposable Domain"]
            continue
        out["_domain"] = domain
        out["_local"] = local

    domains = {}
    for k in order:
        out = results_map[k]
        if "_domain" in out:
            domains.setdefault(out["_domain"], []).append(k)

    sem = asyncio.Semaphore(MAX_WORKERS)

    async def process(domain, keys):
        async with sem:
            await asyncio.to_thread(_verify_domain, domain, keys, results_map, smtp_check)

    await asyncio.gather(*[process(d, ks) for d, ks in domains.items()])

    final = []
    for k in order:
        out = results_map[k]
        out.pop("_domain", None)
        out.pop("_local", None)
        final.append(out)
    return final


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class EmailResult(BaseModel):
    email: str
    status: str
    category: str
    reason: str
    tags: List[str] = []
    mx: Optional[str] = None
    suggestion: Optional[str] = None


class ValidateRequest(BaseModel):
    emails: List[str]
    name: Optional[str] = None
    dedupe: bool = True
    smtp_check: bool = True

    @field_validator("emails")
    @classmethod
    def non_empty(cls, v):
        if not v:
            raise ValueError("emails list cannot be empty")
        if len(v) > 5000:
            raise ValueError("maximum 5000 emails per batch")
        return v


class BatchSummary(BaseModel):
    id: str
    name: str
    created_at: str
    total: int
    deliverable_count: int
    invalid_count: int


class BatchDetail(BatchSummary):
    results: List[EmailResult]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@api_router.get("/")
async def root():
    return {"message": "Mail Pulse email validator API"}


@api_router.post("/validate", response_model=BatchDetail)
async def validate(req: ValidateRequest):
    results = await validate_emails(req.emails, req.dedupe, req.smtp_check)
    if not results:
        raise HTTPException(status_code=400, detail="No valid email entries to process")

    deliverable = [r for r in results if r["category"] == "deliverable"]
    invalid = [r for r in results if r["category"] == "invalid"]

    now = datetime.now(timezone.utc).isoformat()
    name = (req.name or "").strip() or f"Batch {datetime.now(timezone.utc).strftime('%b %d, %H:%M:%S')}"

    doc = {
        "name": name,
        "created_at": now,
        "total": len(results),
        "deliverable_count": len(deliverable),
        "invalid_count": len(invalid),
        "results": results,
    }
    inserted = await db.batches.insert_one(doc)
    doc["id"] = str(inserted.inserted_id)
    return BatchDetail(**doc)


@api_router.get("/history", response_model=List[BatchSummary])
async def history():
    cursor = db.batches.find({}, {"results": 0}).sort("created_at", -1).limit(100)
    out = []
    async for d in cursor:
        d["id"] = str(d.pop("_id"))
        out.append(BatchSummary(**d))
    return out


@api_router.get("/history/{batch_id}", response_model=BatchDetail)
async def history_detail(batch_id: str):
    try:
        d = await db.batches.find_one({"_id": ObjectId(batch_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid batch id")
    if not d:
        raise HTTPException(status_code=404, detail="Batch not found")
    d["id"] = str(d.pop("_id"))
    return BatchDetail(**d)


@api_router.delete("/history/{batch_id}")
async def delete_batch(batch_id: str):
    try:
        res = await db.batches.delete_one({"_id": ObjectId(batch_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid batch id")
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Batch not found")
    return {"deleted": True}


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
