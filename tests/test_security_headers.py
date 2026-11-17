"""安全响应头回归：D24 要求的 CSP/反嗅探/反嵌入/Referrer 策略与 HTTPS HSTS。"""
from __future__ import annotations


def test_api_response_has_security_headers(client) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "microphone=(self)" in r.headers["permissions-policy"]
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "img-src 'self' data: blob:;" in csp
    assert "connect-src 'self' https:" in csp


def test_spa_response_has_csp_and_no_cache(client) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "content-security-policy" in r.headers
    assert r.headers.get("cache-control") == "no-cache"


def test_hsts_only_when_https(client) -> None:
    plain = client.get("/api/health")
    assert "strict-transport-security" not in plain.headers
    forwarded = client.get("/api/health", headers={"X-Forwarded-Proto": "https"})
    assert forwarded.headers["strict-transport-security"].startswith("max-age=31536000")


def test_docs_exempt_from_csp(client) -> None:
    r = client.get("/docs")
    assert r.status_code == 200
    assert "content-security-policy" not in r.headers
