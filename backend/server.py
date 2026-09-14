from fastapi import FastAPI, APIRouter, HTTPException, Header
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, field_validator
from typing import List, Optional
from datetime import datetime, timezone
from bson import ObjectId
import bulk
import verifier

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
async def validate(req: ValidateRequest, x_client_id: str = Header(None, alias="X-Client-Id")):
    results = await verifier.validate_emails(req.emails, req.dedupe, req.smtp_check)
    if not results:
        raise HTTPException(status_code=400, detail="No valid email entries to process")

    deliverable = [r for r in results if r["category"] == "deliverable"]
    invalid = [r for r in results if r["category"] == "invalid"]

    now = datetime.now(timezone.utc).isoformat()
    name = (req.name or "").strip() or f"Batch {datetime.now(timezone.utc).strftime('%b %d, %H:%M:%S')}"

    doc = {
        "name": name,
        "created_at": now,
        "owner_id": x_client_id or "public",
        "total": len(results),
        "deliverable_count": len(deliverable),
        "invalid_count": len(invalid),
        "results": results,
    }
    inserted = await db.batches.insert_one(doc)
    doc["id"] = str(inserted.inserted_id)
    return BatchDetail(**doc)


@api_router.get("/history", response_model=List[BatchSummary])
async def history(x_client_id: str = Header(None, alias="X-Client-Id")):
    owner = x_client_id or "public"
    cursor = db.batches.find({"owner_id": owner}, {"results": 0}).sort("created_at", -1).limit(100)
    out = []
    async for d in cursor:
        d["id"] = str(d.pop("_id"))
        out.append(BatchSummary(**d))
    return out


@api_router.get("/history/{batch_id}", response_model=BatchDetail)
async def history_detail(batch_id: str, x_client_id: str = Header(None, alias="X-Client-Id")):
    owner = x_client_id or "public"
    try:
        oid = ObjectId(batch_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid batch id")
    d = await db.batches.find_one({"_id": oid, "owner_id": owner})
    if not d:
        raise HTTPException(status_code=404, detail="Batch not found")
    d["id"] = str(d.pop("_id"))
    return BatchDetail(**d)


@api_router.delete("/history")
async def clear_history(x_client_id: str = Header(None, alias="X-Client-Id")):
    owner = x_client_id or "public"
    res = await db.batches.delete_many({"owner_id": owner})
    return {"deleted": res.deleted_count}


@api_router.delete("/history/{batch_id}")
async def delete_batch(batch_id: str, x_client_id: str = Header(None, alias="X-Client-Id")):
    owner = x_client_id or "public"
    try:
        oid = ObjectId(batch_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid batch id")
    res = await db.batches.delete_one({"_id": oid, "owner_id": owner})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Batch not found")
    return {"deleted": True}


app.include_router(api_router)
app.include_router(bulk.router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _resume_bulk_jobs():
    try:
        await bulk.resume_jobs()
    except Exception:
        logger.exception("failed to resume bulk jobs")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
