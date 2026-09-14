"""Tests for the TYPO_DOMAIN bug fix: misspelled domains must be invalid."""
import os
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"
HEADERS = {"X-Client-Id": "TEST_typo_client"}


def _validate(emails, smtp_check=False, name="TEST_typo"):
    r = requests.post(f"{API}/validate",
                      json={"emails": emails, "smtp_check": smtp_check,
                            "name": name, "dedupe": True},
                      headers=HEADERS, timeout=60)
    assert r.status_code == 200, r.text
    return r.json()


def test_typo_gmial_is_invalid():
    data = _validate(["user@gmial.com"])
    res = data["results"][0]
    assert res["category"] == "invalid", res
    assert res["status"] == "typo", res
    assert "Possible Typo" in res["tags"], res
    assert res["suggestion"] == "user@gmail.com", res
    assert data["invalid_count"] == 1
    assert data["deliverable_count"] == 0
    # cleanup
    requests.delete(f"{API}/history/{data['id']}", headers=HEADERS, timeout=15)


def test_other_typo_domains_invalid():
    data = _validate(["x@yaho.com", "a@hotmial.com", "b@outlok.com"])
    by = {r["email"]: r for r in data["results"]}
    expect = {
        "x@yaho.com": "x@yahoo.com",
        "a@hotmial.com": "a@hotmail.com",
        "b@outlok.com": "b@outlook.com",
    }
    for email, sugg in expect.items():
        r = by[email]
        assert r["category"] == "invalid", r
        assert r["status"] == "typo", r
        assert r["suggestion"] == sugg, r
        assert "Possible Typo" in r["tags"], r
    assert data["invalid_count"] == 3
    requests.delete(f"{API}/history/{data['id']}", headers=HEADERS, timeout=15)


def test_correct_domain_still_deliverable():
    data = _validate(["good@gmail.com"])
    r = data["results"][0]
    # With smtp_check=False, MX-only path -> deliverable
    assert r["category"] == "deliverable", r
    assert data["deliverable_count"] == 1
    requests.delete(f"{API}/history/{data['id']}", headers=HEADERS, timeout=15)


def test_regression_invalid_categories():
    data = _validate(["bad-email", "t@mailinator.com", "z@nodomxyz-abc123.com"])
    by = {r["email"]: r for r in data["results"]}
    assert by["bad-email"]["category"] == "invalid"
    assert by["bad-email"]["status"] == "invalid_syntax"
    assert by["t@mailinator.com"]["category"] == "invalid"
    assert by["t@mailinator.com"]["status"] == "disposable"
    assert by["z@nodomxyz-abc123.com"]["category"] == "invalid"
    assert by["z@nodomxyz-abc123.com"]["status"] == "no_mx"
    assert data["invalid_count"] == 3
    requests.delete(f"{API}/history/{data['id']}", headers=HEADERS, timeout=15)


def test_client_isolation():
    """History must be filtered per X-Client-Id."""
    other = {"X-Client-Id": "TEST_other_client_xyz"}
    r = requests.post(f"{API}/validate",
                      json={"emails": ["iso@gmail.com"], "smtp_check": False,
                            "name": "TEST_iso"},
                      headers=other, timeout=30)
    bid = r.json()["id"]
    # Different client shouldn't see it
    hist = requests.get(f"{API}/history",
                        headers={"X-Client-Id": "TEST_different_client"},
                        timeout=15).json()
    assert not any(h["id"] == bid for h in hist)
    # Original client should
    hist2 = requests.get(f"{API}/history", headers=other, timeout=15).json()
    assert any(h["id"] == bid for h in hist2)
    requests.delete(f"{API}/history/{bid}", headers=other, timeout=15)
