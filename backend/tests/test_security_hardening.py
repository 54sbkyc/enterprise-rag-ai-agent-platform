from app.auth import hash_password, verify_password


def test_password_hash_uses_salted_pbkdf2():
    first = hash_password("same-password")
    second = hash_password("same-password")

    assert first.startswith("pbkdf2_sha256$")
    assert first != second
    assert verify_password(first, "same-password")
    assert not verify_password(first, "wrong-password")


def test_frontend_responses_disable_browser_cache(client):
    index = client.get("/")
    script = client.get("/static/app.js")

    assert index.headers["cache-control"] == "no-store"
    assert script.headers["cache-control"] == "no-store"
