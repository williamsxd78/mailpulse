from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import re
import asyncio
import logging
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

MAX_WORKERS = 12  # fixed sensible concurrency for MX lookups

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


def _validate_one(email: str) -> dict:
    raw = email
    email = email.strip().lower()
    out = {"email": raw.strip(), "status": "invalid", "category": "invalid",
           "reason": "", "tags": [], "mx": None, "suggestion": None}

    if not email:
        return None

    if "@" not in email or not EMAIL_REGEX.match(email):
        out.update(status="invalid_syntax", category="invalid", reason="Malformed email syntax")
        out["tags"] = ["Invalid Syntax"]
        return out

    local, domain = email.rsplit("@", 1)

    if domain in TYPO_DOMAINS:
        out["suggestion"] = f"{local}@{TYPO_DOMAINS[domain]}"

    if domain in DISPOSABLE_DOMAINS:
        out.update(status="disposable", category="invalid", reason="Disposable / throwaway domain")
        out["tags"] = ["Disposable Domain"]
        return out

    has_mx, mx_host = _check_mx(domain)
    if not has_mx:
        out.update(status="no_mx", category="invalid", reason="No MX record found for domain")
        out["tags"] = ["No MX Record"]
        return out

    out["mx"] = mx_host
    is_role = local in ROLE_PREFIXES
    if is_role:
        out.update(status="risky", category="deliverable", reason="Role-based address (deliverable but risky)")
        out["tags"] = ["MX Active", "Role Account"]
    else:
        out.update(status="deliverable", category="deliverable", reason="Valid syntax and active MX record")
        out["tags"] = ["Syntax Valid", "MX Active"]
    if out["suggestion"]:
        out["tags"].append("Possible Typo")
    return out


async def validate_emails(emails: List[str], dedupe: bool) -> List[dict]:
    cleaned = []
    seen = set()
    for e in emails:
        e = e.strip()
        if not e:
            continue
        key = e.lower()
        if dedupe and key in seen:
            continue
        seen.add(key)
        cleaned.append(e)

    sem = asyncio.Semaphore(MAX_WORKERS)

    async def run(e):
        async with sem:
            return await asyncio.to_thread(_validate_one, e)

    results = await asyncio.gather(*[run(e) for e in cleaned])
    return [r for r in results if r]


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
    results = await validate_emails(req.emails, req.dedupe)
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
