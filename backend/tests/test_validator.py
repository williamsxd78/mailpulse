import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://mail-sorter-17.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="session")
def created_batch_ids():
    ids = []
    yield ids
    # cleanup
    for bid in ids:
        try:
            requests.delete(f"{API}/history/{bid}", timeout=15)
        except Exception:
            pass


# --- Root health ---
def test_root():
    r = requests.get(f"{API}/", timeout=15)
    assert r.status_code == 200
    assert "Mail Pulse" in r.json().get("message", "")


# --- /api/validate categorization ---
def test_validate_mixed_categorization(created_batch_ids):
    payload = {
        "emails": [
            "john.doe@gmail.com",           # deliverable
            "bad-email",                    # invalid_syntax
            "test@mailinator.com",          # disposable
            "support@microsoft.com",        # risky/role but deliverable
            "info@nonexistentdomain-xyz-123.com",  # no_mx
        ],
        "name": "TEST_mixed",
        "dedupe": True,
    }
    r = requests.post(f"{API}/validate", json=payload, timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    created_batch_ids.append(data["id"])
    assert data["total"] == 5
    by_email = {x["email"]: x for x in data["results"]}
    assert by_email["john.doe@gmail.com"]["status"] == "deliverable"
    assert by_email["john.doe@gmail.com"]["category"] == "deliverable"
    assert by_email["bad-email"]["status"] == "invalid_syntax"
    assert by_email["bad-email"]["category"] == "invalid"
    assert by_email["test@mailinator.com"]["status"] == "disposable"
    assert by_email["test@mailinator.com"]["category"] == "invalid"
    assert by_email["support@microsoft.com"]["status"] == "risky"
    assert by_email["support@microsoft.com"]["category"] == "deliverable"
    assert by_email["info@nonexistentdomain-xyz-123.com"]["status"] == "no_mx"
    assert by_email["info@nonexistentdomain-xyz-123.com"]["category"] == "invalid"
    assert data["deliverable_count"] == 2
    assert data["invalid_count"] == 3


# --- Empty list validation error ---
def test_validate_empty_list():
    r = requests.post(f"{API}/validate", json={"emails": []}, timeout=15)
    assert r.status_code in (400, 422)


def test_validate_only_blank_lines():
    r = requests.post(f"{API}/validate", json={"emails": ["   ", ""]}, timeout=15)
    assert r.status_code == 400


# --- Dedupe ---
def test_dedupe_collapses(created_batch_ids):
    payload = {
        "emails": ["a@gmail.com", "a@gmail.com", "A@GMAIL.COM", "b@gmail.com"],
        "name": "TEST_dedupe",
        "dedupe": True,
    }
    r = requests.post(f"{API}/validate", json=payload, timeout=60)
    assert r.status_code == 200
    data = r.json()
    created_batch_ids.append(data["id"])
    assert data["total"] == 2


def test_no_dedupe(created_batch_ids):
    payload = {
        "emails": ["a@gmail.com", "a@gmail.com"],
        "name": "TEST_no_dedupe",
        "dedupe": False,
    }
    r = requests.post(f"{API}/validate", json=payload, timeout=60)
    assert r.status_code == 200
    data = r.json()
    created_batch_ids.append(data["id"])
    assert data["total"] == 2


# --- History listing & detail ---
def test_history_list_and_detail(created_batch_ids):
    # ensure we have a batch first
    r = requests.post(f"{API}/validate", json={"emails": ["hist@gmail.com"], "name": "TEST_hist"}, timeout=60)
    assert r.status_code == 200
    bid = r.json()["id"]
    created_batch_ids.append(bid)

    r = requests.get(f"{API}/history", timeout=15)
    assert r.status_code == 200
    hist = r.json()
    assert isinstance(hist, list)
    assert any(h["id"] == bid for h in hist)
    # summary shape (no results key)
    top = next(h for h in hist if h["id"] == bid)
    assert "results" not in top
    assert top["name"] == "TEST_hist"

    # detail
    r = requests.get(f"{API}/history/{bid}", timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert d["id"] == bid
    assert len(d["results"]) == 1


# --- Delete ---
def test_delete_batch(created_batch_ids):
    r = requests.post(f"{API}/validate", json={"emails": ["del@gmail.com"], "name": "TEST_del"}, timeout=60)
    bid = r.json()["id"]
    r = requests.delete(f"{API}/history/{bid}", timeout=15)
    assert r.status_code == 200
    assert r.json().get("deleted") is True
    # verify gone
    r = requests.get(f"{API}/history/{bid}", timeout=15)
    assert r.status_code == 404


def test_delete_invalid_id():
    r = requests.delete(f"{API}/history/not-a-real-id", timeout=15)
    assert r.status_code in (400, 404)


def test_history_detail_invalid_id():
    r = requests.get(f"{API}/history/not-a-real-id", timeout=15)
    assert r.status_code in (400, 404)
