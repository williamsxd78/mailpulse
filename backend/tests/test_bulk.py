"""Bulk jobs + Proxy manager + SMTP proxy tester tests."""
import io
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://mail-sorter-17.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="session")
def created_job_ids():
    ids = []
    yield ids
    for jid in ids:
        try:
            requests.delete(f"{API}/jobs/{jid}", timeout=15)
        except Exception:
            pass


@pytest.fixture(scope="session")
def created_proxy_ids():
    ids = []
    yield ids
    for pid in ids:
        try:
            requests.delete(f"{API}/proxies/{pid}", timeout=15)
        except Exception:
            pass


# ------------- Quick regression -------------

def test_quick_validate_still_works():
    r = requests.post(f"{API}/validate", json={"emails": ["a@gmail.com", "bad"], "smtp_check": False}, timeout=60)
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 2
    assert d["deliverable_count"] + d["invalid_count"] == 2


# ------------- Bulk small SMTP-on job -------------

def _create_job(text, name, smtp_check=True, dedupe=True):
    data = {"name": name, "dedupe": str(dedupe).lower(), "smtp_check": str(smtp_check).lower(), "text": text}
    r = requests.post(f"{API}/jobs", data=data, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def _wait_status(job_id, statuses, timeout=180, min_processed=None):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = requests.get(f"{API}/jobs/{job_id}", timeout=15)
        assert r.status_code == 200
        last = r.json()
        if last["status"] in statuses:
            if min_processed is None or last["processed"] >= min_processed:
                return last
        time.sleep(0.5)
    raise AssertionError(f"Timeout waiting for {statuses}; last={last}")


def test_bulk_small_smtp_completes(created_job_ids):
    emails = "\n".join([
        "john.doe@gmail.com",
        "asdfghjkqwerty1234@gmail.com",
        "bad-email",
        "test@mailinator.com",
        "info@nonexistentdomain-xyz-123.com",
        "hello@microsoft.com",
    ])
    job = _create_job(emails, "TEST_bulk_smtp", smtp_check=True)
    jid = job["id"]
    created_job_ids.append(jid)
    final = _wait_status(jid, {"completed"}, timeout=180)
    assert final["total"] == 6
    assert final["processed"] == 6
    assert final["deliverable_count"] + final["invalid_count"] == 6
    # required fields
    for k in ("status", "processed", "total", "percent", "rate",
              "deliverable_count", "invalid_count", "unknown_count"):
        assert k in final


# ------------- Pause / Resume (real) -------------

def test_pause_resume_mx_only(created_job_ids):
    # Very large list; smtp_check=False -> only MX (cached fast).
    emails = "\n".join(f"user{i}@gmail.com" for i in range(500000))
    job = _create_job(emails, "TEST_pause_resume", smtp_check=False, dedupe=True)
    jid = job["id"]
    created_job_ids.append(jid)

    # Tight-poll until processed >= 200 (past first window), then pause.
    deadline = time.time() + 60
    started = None
    while time.time() < deadline:
        r = requests.get(f"{API}/jobs/{jid}", timeout=15).json()
        if r["status"] == "completed":
            pytest.skip(f"job completed before pause could observe processed>=200: {r}")
        if r.get("processed", 0) >= 200:
            started = r
            break
        time.sleep(0.02)
    assert started is not None, "job never reached running state with processed>0"

    r = requests.post(f"{API}/jobs/{jid}/pause", timeout=15)
    assert r.status_code == 200, r.text

    paused = _wait_status(jid, {"paused", "completed"}, timeout=60)
    if paused["status"] == "completed":
        # It sped through before the pause landed; still validate persisted counts.
        assert paused["processed"] == paused["total"] == 500000
        return
    assert 0 < paused["processed"] < paused["total"], paused
    saved_processed = paused["processed"]

    # resume
    r = requests.post(f"{API}/jobs/{jid}/resume", timeout=15)
    assert r.status_code == 200, r.text

    final = _wait_status(jid, {"completed"}, timeout=180)
    assert final["processed"] == final["total"] == 500000
    assert final["processed"] >= saved_processed


# ------------- Cancel -------------

def test_cancel_job(created_job_ids):
    emails = "\n".join(f"cancel{i}@gmail.com" for i in range(500000))
    job = _create_job(emails, "TEST_cancel", smtp_check=False)
    jid = job["id"]
    created_job_ids.append(jid)
    time.sleep(0.2)
    r = requests.post(f"{API}/jobs/{jid}/cancel", timeout=15)
    assert r.status_code == 200
    final = _wait_status(jid, {"canceled", "completed"}, timeout=60)
    if final["status"] == "completed":
        pytest.skip("job finished before cancel landed")
    assert final["status"] == "canceled"


# ------------- Download CSV -------------

def test_download_csv_categories(created_job_ids):
    emails = "\n".join([
        "john.doe@gmail.com",
        "bad-email",
        "test@mailinator.com",
        "info@nonexistentdomain-xyz-123.com",
    ])
    job = _create_job(emails, "TEST_download", smtp_check=False)
    jid = job["id"]
    created_job_ids.append(jid)
    _wait_status(jid, {"completed"}, timeout=90)

    r = requests.get(f"{API}/jobs/{jid}/download?category=all", timeout=30)
    assert r.status_code == 200
    lines = [l for l in r.text.splitlines() if l.strip()]
    assert lines[0] == "email,status,category,reason,mx"
    assert len(lines) == 5  # header + 4

    r = requests.get(f"{API}/jobs/{jid}/download?category=invalid", timeout=30)
    assert r.status_code == 200
    lines = [l for l in r.text.splitlines() if l.strip()]
    assert lines[0] == "email,status,category,reason,mx"
    for row in lines[1:]:
        parts = row.split(",")
        assert parts[2] == "invalid", row

    r = requests.get(f"{API}/jobs/{jid}/download?category=deliverable", timeout=30)
    assert r.status_code == 200
    lines = [l for l in r.text.splitlines() if l.strip()]
    for row in lines[1:]:
        parts = row.split(",")
        assert parts[2] == "deliverable", row


# ------------- Delete removes from list -------------

def test_delete_job_removes_from_list():
    job = _create_job("del@gmail.com", "TEST_delete", smtp_check=False)
    jid = job["id"]
    _wait_status(jid, {"completed"}, timeout=60)
    r = requests.delete(f"{API}/jobs/{jid}", timeout=15)
    assert r.status_code == 200
    r = requests.get(f"{API}/jobs", timeout=15)
    assert r.status_code == 200
    assert all(j["id"] != jid for j in r.json())


# ------------- Proxy manager CRUD -------------

def test_proxy_crud(created_proxy_ids):
    payload = {"label": "TEST_proxy", "type": "socks5", "host": "127.0.0.1", "port": 1080}
    r = requests.post(f"{API}/proxies", json=payload, timeout=15)
    assert r.status_code == 200
    p = r.json()
    pid = p["id"]
    created_proxy_ids.append(pid)
    assert p["host"] == "127.0.0.1"

    r = requests.get(f"{API}/proxies", timeout=15)
    assert r.status_code == 200
    assert any(x["id"] == pid for x in r.json())

    r = requests.delete(f"{API}/proxies/{pid}", timeout=15)
    assert r.status_code == 200
    r = requests.get(f"{API}/proxies", timeout=15)
    assert all(x["id"] != pid for x in r.json())


# ------------- Proxy/direct test -------------

def test_direct_smtp_probe():
    r = requests.post(f"{API}/proxies/test", json={}, timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["port25"] is True
    assert "mx" in d
    assert isinstance(d.get("latency_ms"), int)


def test_bogus_proxy_fails():
    r = requests.post(f"{API}/proxies/test",
                      json={"host": "127.0.0.1", "port": 9, "type": "socks5"},
                      timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is False
