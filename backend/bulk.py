"""Background bulk-verification jobs (upload → process → download) with real
pause/resume/cancel, plus proxy management and an SMTP proxy tester.

The raw uploaded list is stored in GridFS (MongoDB) so it never relies on
pod-local disk. Derived working/result files are kept on local scratch disk.
"""
import os
import csv
import time
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket
from bson import ObjectId
from dotenv import load_dotenv

import verifier

logger = logging.getLogger("bulk")

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")
DATA_DIR = ROOT_DIR / "data"
WORK_DIR = DATA_DIR / "work"
RESULT_DIR = DATA_DIR / "results"
for d in (WORK_DIR, RESULT_DIR):
    d.mkdir(parents=True, exist_ok=True)

_client = AsyncIOMotorClient(os.environ["MONGO_URL"])
_db = _client[os.environ["DB_NAME"]]
jobs = _db.jobs
proxies_col = _db.proxies
_bucket = AsyncIOMotorGridFSBucket(_db, bucket_name="uploads")

WINDOW = 200               # emails processed per checkpoint
CSV_HEADER = "email,status,category,reason,mx\n"

JOB_CONTROL: dict = {}     # job_id -> "run" | "pause" | "cancel"
JOB_TASKS: dict = {}       # job_id -> asyncio.Task

router = APIRouter(prefix="/api")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _work_paths(job_id):
    return (WORK_DIR / f"{job_id}.emails", RESULT_DIR / f"{job_id}.csv")


# ---------------------------------------------------------------------------
# Preparation & processing
# ---------------------------------------------------------------------------

async def _prepare_from_gridfs(grid_id, work_path: Path, dedupe: bool) -> int:
    """Stream the raw upload out of GridFS, extract + dedupe emails into work file."""
    seen = set()
    total = 0
    buf = b""
    processed_lines = 0
    stream = await _bucket.open_download_stream(grid_id)
    with open(work_path, "w", encoding="utf-8") as fout:
        while True:
            chunk = await stream.read(1024 * 512)
            if not chunk:
                break
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for raw in lines:
                total += _write_email(raw, fout, seen, dedupe)
            processed_lines += len(lines)
            if processed_lines >= 20000:
                processed_lines = 0
                await asyncio.sleep(0)
        if buf:
            total += _write_email(buf, fout, seen, dedupe)
    return total


def _write_email(raw_bytes, fout, seen, dedupe) -> int:
    line = raw_bytes.decode("utf-8", errors="ignore").strip()
    if not line:
        return 0
    email = verifier.extract_email(line)
    if not email:
        return 0
    key = email.lower()
    if dedupe:
        if key in seen:
            return 0
        seen.add(key)
    fout.write(email + "\n")
    return 1


def _process_window(emails, smtp_check, proxies):
    return verifier.verify_batch(emails, smtp_check=smtp_check, proxies=proxies)


async def _load_proxies():
    out = []
    async for p in proxies_col.find({"enabled": True}):
        out.append({"type": p.get("type"), "host": p.get("host"), "port": p.get("port"),
                    "username": p.get("username"), "password": p.get("password")})
    return out


async def _run_job(job_id: str):
    oid = ObjectId(job_id)
    work_path, result_path = _work_paths(job_id)
    try:
        job = await jobs.find_one({"_id": oid})
        if not job:
            return
        JOB_CONTROL[job_id] = "run"

        # If prepared but the derived work file vanished (pod restart), re-prepare.
        if job.get("prepared") and not work_path.exists():
            await jobs.update_one({"_id": oid}, {"$set": {
                "prepared": False, "processed": 0, "deliverable_count": 0,
                "invalid_count": 0, "unknown_count": 0, "catchall_count": 0,
                "active_seconds": 0.0}})
            job = await jobs.find_one({"_id": oid})

        # ---- prepare phase ----
        if not job.get("prepared"):
            await jobs.update_one({"_id": oid}, {"$set": {"status": "preparing", "updated_at": _now()}})
            total = await _prepare_from_gridfs(job["raw_grid_id"], work_path, job.get("dedupe", True))
            with open(result_path, "w", encoding="utf-8") as f:
                f.write(CSV_HEADER)
            await jobs.update_one({"_id": oid}, {"$set": {
                "prepared": True, "total": total, "processed": 0,
                "deliverable_count": 0, "invalid_count": 0, "unknown_count": 0,
                "catchall_count": 0, "updated_at": _now()}})
            job = await jobs.find_one({"_id": oid})

        smtp_check = job.get("smtp_check", True)
        proxies = await _load_proxies() if smtp_check else []

        processed = job.get("processed", 0)
        counts = {
            "deliverable_count": job.get("deliverable_count", 0),
            "invalid_count": job.get("invalid_count", 0),
            "unknown_count": job.get("unknown_count", 0),
            "catchall_count": job.get("catchall_count", 0),
        }
        active_seconds = job.get("active_seconds", 0.0)

        await jobs.update_one({"_id": oid}, {"$set": {"status": "running", "updated_at": _now()}})

        result_file = open(result_path, "a", encoding="utf-8", newline="")
        writer = csv.writer(result_file)

        with open(work_path, "r", encoding="utf-8") as f:
            for _ in range(processed):        # skip already-processed lines
                if f.readline() == "":
                    break

            window = []

            async def flush_window():
                nonlocal processed, active_seconds
                if not window:
                    return
                t0 = time.time()
                results = await asyncio.to_thread(_process_window, list(window), smtp_check, proxies)
                for r in results:
                    writer.writerow([r["email"], r["status"], r["category"], r["reason"], r.get("mx") or ""])
                    if r["category"] == "invalid":
                        counts["invalid_count"] += 1
                    else:
                        counts["deliverable_count"] += 1
                        if r["status"] in ("unknown", "greylisted"):
                            counts["unknown_count"] += 1
                        elif r["status"] == "catch_all":
                            counts["catchall_count"] += 1
                result_file.flush()
                processed += len(window)
                active_seconds += time.time() - t0
                rate = round(processed / active_seconds, 1) if active_seconds > 0 else 0
                await jobs.update_one({"_id": oid}, {"$set": {
                    "processed": processed, "active_seconds": active_seconds, "rate": rate,
                    "updated_at": _now(), **counts}})
                window.clear()

            for line in f:
                ctrl = JOB_CONTROL.get(job_id, "run")
                if ctrl == "pause":
                    await flush_window()
                    result_file.close()
                    await jobs.update_one({"_id": oid}, {"$set": {"status": "paused", "updated_at": _now()}})
                    return
                if ctrl == "cancel":
                    result_file.close()
                    await jobs.update_one({"_id": oid}, {"$set": {"status": "canceled", "updated_at": _now()}})
                    return
                em = line.strip()
                if em:
                    window.append(em)
                if len(window) >= WINDOW:
                    await flush_window()

            await flush_window()
            result_file.close()

        await jobs.update_one({"_id": oid}, {"$set": {"status": "completed", "updated_at": _now()}})
    except asyncio.CancelledError:
        raise
    except Exception as ex:
        logger.exception("job failed")
        await jobs.update_one({"_id": oid}, {"$set": {"status": "failed", "error": str(ex), "updated_at": _now()}})
    finally:
        JOB_TASKS.pop(job_id, None)


def _launch(job_id: str):
    JOB_CONTROL[job_id] = "run"
    JOB_TASKS[job_id] = asyncio.create_task(_run_job(job_id))


async def resume_jobs():
    async for job in jobs.find({"status": {"$in": ["queued", "preparing", "running"]}}):
        _launch(str(job["_id"]))


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _job_public(job):
    total = job.get("total", 0)
    processed = job.get("processed", 0)
    pct = round((processed / total) * 100, 1) if total else 0.0
    return {
        "id": str(job["_id"]),
        "name": job.get("name"),
        "status": job.get("status"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "smtp_check": job.get("smtp_check", True),
        "dedupe": job.get("dedupe", True),
        "total": total,
        "processed": processed,
        "percent": pct,
        "rate": job.get("rate", 0),
        "deliverable_count": job.get("deliverable_count", 0),
        "invalid_count": job.get("invalid_count", 0),
        "unknown_count": job.get("unknown_count", 0),
        "catchall_count": job.get("catchall_count", 0),
        "error": job.get("error"),
    }


# ---------------------------------------------------------------------------
# Job endpoints
# ---------------------------------------------------------------------------

@router.post("/jobs")
async def create_job(
    name: str = Form(None),
    dedupe: bool = Form(True),
    smtp_check: bool = Form(True),
    text: str = Form(None),
    file: UploadFile = File(None),
):
    if not file and not (text and text.strip()):
        raise HTTPException(status_code=400, detail="Provide a file or pasted emails")

    grid_in = _bucket.open_upload_stream("bulk.raw")
    if file:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            await grid_in.write(chunk)
    if text and text.strip():
        await grid_in.write(("\n" + text).encode("utf-8"))
    await grid_in.close()
    raw_grid_id = grid_in._id

    now = _now()
    job_name = (name or "").strip() or f"Bulk {datetime.now(timezone.utc).strftime('%b %d, %H:%M:%S')}"
    doc = {
        "name": job_name, "status": "queued", "created_at": now, "updated_at": now,
        "smtp_check": smtp_check, "dedupe": dedupe, "prepared": False, "raw_grid_id": raw_grid_id,
        "total": 0, "processed": 0, "deliverable_count": 0, "invalid_count": 0,
        "unknown_count": 0, "catchall_count": 0, "active_seconds": 0.0, "rate": 0,
    }
    inserted = await jobs.insert_one(doc)
    doc["_id"] = inserted.inserted_id
    _launch(str(inserted.inserted_id))
    return _job_public(doc)


@router.get("/jobs")
async def list_jobs():
    return [_job_public(job) async for job in jobs.find().sort("created_at", -1).limit(100)]


def _get_oid(job_id):
    try:
        return ObjectId(job_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = await jobs.find_one({"_id": _get_oid(job_id)})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_public(job)


@router.post("/jobs/{job_id}/pause")
async def pause_job(job_id: str):
    job = await jobs.find_one({"_id": _get_oid(job_id)})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") != "running":
        raise HTTPException(status_code=400, detail="Job can only be paused while running")
    JOB_CONTROL[job_id] = "pause"
    return {"status": "pausing"}


@router.post("/jobs/{job_id}/resume")
async def resume_job(job_id: str):
    oid = _get_oid(job_id)
    job = await jobs.find_one({"_id": oid})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") not in ("paused", "failed"):
        raise HTTPException(status_code=400, detail="Job cannot be resumed")
    if job_id in JOB_TASKS:
        raise HTTPException(status_code=400, detail="Job already running")
    await jobs.update_one({"_id": oid}, {"$set": {"status": "running", "error": None, "updated_at": _now()}})
    _launch(job_id)
    return {"status": "resumed"}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    oid = _get_oid(job_id)
    job = await jobs.find_one({"_id": oid})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    JOB_CONTROL[job_id] = "cancel"
    if job.get("status") == "paused" and job_id not in JOB_TASKS:
        await jobs.update_one({"_id": oid}, {"$set": {"status": "canceled", "updated_at": _now()}})
    return {"status": "canceling"}


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    oid = _get_oid(job_id)
    JOB_CONTROL[job_id] = "cancel"
    task = JOB_TASKS.get(job_id)
    if task:
        task.cancel()
    job = await jobs.find_one({"_id": oid})
    res = await jobs.delete_one({"_id": oid})
    if job and job.get("raw_grid_id"):
        try:
            await _bucket.delete(job["raw_grid_id"])
        except Exception:
            pass
    for p in _work_paths(job_id):
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"deleted": True}


@router.get("/jobs/{job_id}/download")
async def download_job(job_id: str, category: str = "all"):
    oid = _get_oid(job_id)
    job = await jobs.find_one({"_id": oid})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _, result_path = _work_paths(job_id)
    if not result_path.exists():
        raise HTTPException(status_code=404, detail="No results yet")

    want = category if category in ("deliverable", "invalid") else None

    def generate():
        yield CSV_HEADER
        with open(result_path, "r", encoding="utf-8") as f:
            next(f, None)
            for line in f:
                if want is None:
                    yield line
                else:
                    parts = line.split(",")
                    if len(parts) >= 3 and parts[2] == want:
                        yield line

    fname = f"{(job.get('name') or 'results').replace(' ', '_')}_{category}.csv"
    return StreamingResponse(generate(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ---------------------------------------------------------------------------
# Proxy endpoints
# ---------------------------------------------------------------------------

class ProxyIn(BaseModel):
    label: Optional[str] = None
    type: str = "socks5"
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None
    enabled: bool = True


class ProxyTestIn(BaseModel):
    id: Optional[str] = None
    type: Optional[str] = "socks5"
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None


def _proxy_public(p):
    return {"id": str(p["_id"]), "label": p.get("label"), "type": p.get("type"),
            "host": p.get("host"), "port": p.get("port"),
            "username": p.get("username"), "enabled": p.get("enabled", True),
            "last_status": p.get("last_status")}


@router.get("/proxies")
async def list_proxies():
    return [_proxy_public(p) async for p in proxies_col.find().sort("_id", -1)]


@router.post("/proxies")
async def add_proxy(proxy: ProxyIn):
    doc = proxy.model_dump()
    doc["created_at"] = _now()
    inserted = await proxies_col.insert_one(doc)
    doc["_id"] = inserted.inserted_id
    return _proxy_public(doc)


@router.delete("/proxies/{proxy_id}")
async def delete_proxy(proxy_id: str):
    res = await proxies_col.delete_one({"_id": _get_oid(proxy_id)})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Proxy not found")
    return {"deleted": True}


@router.post("/proxies/test")
async def test_proxy(body: ProxyTestIn):
    proxy = None
    proxy_id = None
    if body.id:
        p = await proxies_col.find_one({"_id": _get_oid(body.id)})
        if not p:
            raise HTTPException(status_code=404, detail="Proxy not found")
        proxy_id = p["_id"]
        proxy = {"type": p.get("type"), "host": p.get("host"), "port": p.get("port"),
                 "username": p.get("username"), "password": p.get("password")}
    elif body.host and body.port:
        proxy = {"type": body.type, "host": body.host, "port": body.port,
                 "username": body.username, "password": body.password}
    result = await asyncio.to_thread(verifier.test_proxy_smtp, proxy)
    if proxy_id is not None:
        await proxies_col.update_one({"_id": proxy_id}, {"$set": {"last_status": result}})
    return result
