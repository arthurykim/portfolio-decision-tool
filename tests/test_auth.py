from fastapi.testclient import TestClient

from auth import create_token, hash_password, verify_password, verify_token
from main import app


def fresh_client():
    return TestClient(app)


def test_password_hash_roundtrip():
    h = hash_password("correct horse battery")
    assert verify_password("correct horse battery", h)
    assert not verify_password("wrong password!", h)
    assert hash_password("x" * 8) != hash_password("x" * 8)  # salted


def test_token_roundtrip_and_tamper():
    token = create_token(42)
    assert verify_token(token) == 42
    assert verify_token(token[:-4] + "beef") is None
    assert verify_token("garbage") is None


def test_register_login_me_logout():
    c = fresh_client()
    r = c.post("/api/auth/register", json={"username": "arthur", "password": "s3cret-pass"})
    assert r.status_code == 200
    assert r.json()["is_admin"] is True  # first user is admin

    assert c.get("/api/auth/me").json()["user"]["username"] == "arthur"

    c.post("/api/auth/logout")
    c.cookies.clear()
    assert c.get("/api/auth/me").json()["user"] is None

    r = c.post("/api/auth/login", json={"username": "arthur", "password": "s3cret-pass"})
    assert r.status_code == 200
    assert c.get("/api/auth/me").json()["user"]["is_admin"] is True


def test_second_user_is_not_admin_and_duplicates_rejected():
    c = fresh_client()
    r = c.post("/api/auth/register", json={"username": "guest", "password": "guest-pass-1"})
    assert r.status_code == 200
    assert r.json()["is_admin"] is False
    assert c.post("/api/auth/register",
                  json={"username": "GUEST", "password": "guest-pass-1"}).status_code == 409


def test_login_rejects_bad_credentials():
    c = fresh_client()
    assert c.post("/api/auth/login",
                  json={"username": "arthur", "password": "wrong-password"}).status_code == 401
    assert c.post("/api/auth/login",
                  json={"username": "nobody", "password": "whatever-123"}).status_code == 401


def test_register_validates_username_and_password():
    c = fresh_client()
    assert c.post("/api/auth/register",
                  json={"username": "bad name!", "password": "long-enough-1"}).status_code == 422
    assert c.post("/api/auth/register",
                  json={"username": "okname", "password": "short"}).status_code == 422


def test_watchlist_requires_auth():
    c = fresh_client()
    assert c.get("/api/watchlist").status_code == 401
    assert c.post("/api/watchlist", json={"symbol": "NVDA"}).status_code == 401


def test_watchlist_pin_unpin():
    c = fresh_client()
    c.post("/api/auth/register", json={"username": "pinner", "password": "pinner-pass"})
    assert c.post("/api/watchlist", json={"symbol": "nvda"}).json()["symbols"] == ["NVDA"]
    c.post("/api/watchlist", json={"symbol": "NVDA"})  # idempotent
    r = c.post("/api/watchlist", json={"symbol": "AAPL"})
    assert r.json()["symbols"] == ["NVDA", "AAPL"]
    assert c.post("/api/watchlist", json={"symbol": "ZZZZ"}).status_code == 422
    assert c.delete("/api/watchlist/NVDA").json()["symbols"] == ["AAPL"]


def test_about_read_public_edit_admin_only():
    c = fresh_client()
    assert "educational" in c.get("/api/about").json()["content"]

    assert c.put("/api/about", json={"content": "hacked"}).status_code == 401

    c.post("/api/auth/register", json={"username": "viewer", "password": "viewer-pass"})
    assert c.put("/api/about", json={"content": "still no"}).status_code == 403

    admin = fresh_client()
    admin.post("/api/auth/login", json={"username": "arthur", "password": "s3cret-pass"})
    r = admin.put("/api/about", json={"content": "# Hello\nUpdated by admin."})
    assert r.status_code == 200
    assert c.get("/api/about").json()["content"].startswith("# Hello")
