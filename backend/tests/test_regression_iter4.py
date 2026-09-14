"""Iteration 4 regression tests:
- Quick Check mixed categorization (typo/syntax/disposable/no_mx/deliverable)
- email:pass combo parsing
- Clear-all history endpoint
- Per-browser isolation for /api/history, /api/jobs, /api/proxies
- Bulk CSV download honors client_id query param
- Proxy CRUD + direct SMTP probe + bogus proxy
"""
import os
import time
import uuid
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

CID_A = f"TEST_A_{uuid.uuid4().hex[:8]}"
CID_B = f"TEST_B_{uuid.uuid4().hex[:8]}"
HA = {"X-Client-Id": CID_A}
HB = {"X-Client-Id": CID_B}


# ------------ Quick Check mixed categorization ------------

def test_quick_mixed_categorization():
    payload = {
        "emails": [
            "good@gmail.com",
            "user@gmial.com",
            "bad-email",
            "t@mailinator.com",
            "z@nodomxyz-abc123.com",
        ],
        "smtp_check": False,
        "name": "TEST_iter4_mixed",
        "dedupe": True,
    }
    r = requests.post(f"{API}/validate", json=payload, headers=HA, timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    by = {x["email"]: x for x in d["results"]}
    assert by["good@gmail.com"]["category"] == "deliverable"
    assert by["user@gmial.com"]["category"] == "invalid"
    assert by["user@gmial.com"]["status"] == "typo"
    assert by["user@gmial.com"]["suggestion"] == "user@gmail.com"
    assert by["bad-email"]["status"] == "invalid_syntax"
    assert by["t@mailinator.com"]["status"] == "disposable"
    assert by["z@nodomxyz-abc123.com"]["status"] == "no_mx"
    assert d["deliverable_count"] == 1
    assert d["invalid_count"] == 4
    requests.delete(f"{API}/history/{d['id']}", headers=HA, timeout=15)


def test_email_pass_combo_parsed():
    payload = {"emails": ["jane@company.io:secret"], "smtp_check": False,
               "name": "TEST_combo"}
    r = requests.post(f"{API}/validate", json=payload, headers=HA, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["results"][0]["email"] == "jane@company.io"
    requests.delete(f"{API}/history/{d['id']}", headers=HA, timeout=15)


# ------------ Clear all history ------------

def test_clear_all_history():
    cid = f"TEST_clear_{uuid.uuid4().hex[:8]}"
    H = {"X-Client-Id": cid}
    for i in range(3):
        requests.post(f"{API}/validate",
                      json={"emails": [f"c{i}@gmail.com"], "smtp_check": False,
                            "name": f"TEST_clear_{i}"},
                      headers=H, timeout=30)
    hist = requests.get(f"{API}/history", headers=H, timeout=15).json()
    assert len(hist) >= 3
    r = requests.delete(f"{API}/history", headers=H, timeout=15)
    assert r.status_code == 200
    assert r.json()["deleted"] >= 3
    hist2 = requests.get(f"{API}/history", headers=H, timeout=15).json()
    assert hist2 == []


# ------------ Per-browser isolation: history ------------

def test_history_isolation():
    ra = requests.post(f"{API}/validate",
                       json={"emails": ["iso@gmail.com"], "smtp_check": False,
                             "name": "TEST_iso_A"}, headers=HA, timeout=30)
    bid = ra.json()["id"]
    hb = requests.get(f"{API}/history", headers=HB, timeout=15).json()
    assert not any(h["id"] == bid for h in hb)
    # Client B can't fetch A's detail
    r = requests.get(f"{API}/history/{bid}", headers=HB, timeout=15)
    assert r.status_code == 404
    # Client B can't delete A's batch
    r = requests.delete(f"{API}/history/{bid}", headers=HB, timeout=15)
    assert r.status_code == 404
    # Cleanup as A
    requests.delete(f"{API}/history/{bid}", headers=HA, timeout=15)


# ------------ Bulk isolation + download client_id ------------

def _create_job(headers, text, name, smtp_check=False):
    data = {"name": name, "dedupe": "true",
            "smtp_check": str(smtp_check).lower(), "text": text}
    r = requests.post(f"{API}/jobs", data=data, headers=headers, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def _wait(job_id, headers, statuses={"completed"}, timeout=90):
    dl = time.time() + timeout
    while time.time() < dl:
        r = requests.get(f"{API}/jobs/{job_id}", headers=headers, timeout=15).json()
        if r["status"] in statuses:
            return r
        time.sleep(0.4)
    raise AssertionError(f"timeout for {statuses}; last={r}")


def test_jobs_isolation_and_download_client_id():
    job = _create_job(HA, "a1@gmail.com\nbad-syntax\nd@mailinator.com",
                      "TEST_iso_job_A")
    jid = job["id"]
    _wait(jid, HA)

    # B cannot see it
    listb = requests.get(f"{API}/jobs", headers=HB, timeout=15).json()
    assert not any(j["id"] == jid for j in listb)
    r = requests.get(f"{API}/jobs/{jid}", headers=HB, timeout=15)
    assert r.status_code == 404
    # B cannot pause/resume/cancel/delete A's job
    for path in ("pause", "resume", "cancel"):
        r = requests.post(f"{API}/jobs/{jid}/{path}", headers=HB, timeout=15)
        assert r.status_code == 404
    r = requests.delete(f"{API}/jobs/{jid}", headers=HB, timeout=15)
    assert r.status_code == 404

    # download with client_id=A works, with B fails
    r = requests.get(f"{API}/jobs/{jid}/download?category=all&client_id={CID_A}", timeout=30)
    assert r.status_code == 200
    lines = [l for l in r.text.splitlines() if l.strip()]
    assert lines[0] == "email,status,category,reason,mx"
    assert len(lines) >= 4  # header + 3

    r = requests.get(f"{API}/jobs/{jid}/download?category=all&client_id={CID_B}", timeout=30)
    assert r.status_code == 404

    # invalid-only filter
    r = requests.get(f"{API}/jobs/{jid}/download?category=invalid&client_id={CID_A}", timeout=30)
    assert r.status_code == 200
    for row in [l for l in r.text.splitlines() if l.strip()][1:]:
        assert row.split(",")[2] == "invalid", row

    # cleanup
    requests.delete(f"{API}/jobs/{jid}", headers=HA, timeout=15)


# ------------ Proxy isolation + direct + bogus ------------

def test_proxy_isolation_direct_and_bogus():
    p = requests.post(f"{API}/proxies",
                      json={"label": "TEST_iso_prox", "type": "socks5",
                            "host": "127.0.0.1", "port": 1080},
                      headers=HA, timeout=15).json()
    pid = p["id"]
    listb = requests.get(f"{API}/proxies", headers=HB, timeout=15).json()
    assert not any(x["id"] == pid for x in listb)
    r = requests.delete(f"{API}/proxies/{pid}", headers=HB, timeout=15)
    assert r.status_code == 404
    # A can delete
    r = requests.delete(f"{API}/proxies/{pid}", headers=HA, timeout=15)
    assert r.status_code == 200

    # direct probe (no proxy)
    r = requests.post(f"{API}/proxies/test", json={}, timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True and d["port25"] is True

    # bogus
    r = requests.post(f"{API}/proxies/test",
                      json={"host": "127.0.0.1", "port": 9, "type": "socks5"},
                      timeout=30)
    assert r.status_code == 200
    assert r.json()["ok"] is False
