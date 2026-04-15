"""Backend and frontend reachability (no PDF fixtures required)."""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.integration


def test_backend_health(http_client: httpx.Client, backend_url: str) -> None:
    r = http_client.get(f"{backend_url}/api/health")
    r.raise_for_status()
    data = r.json()
    assert data.get("status") == "ok"


def test_frontend_root(http_client: httpx.Client, frontend_url: str) -> None:
    r = http_client.get(f"{frontend_url}/")
    assert r.status_code == 200


def test_frontend_api_proxy_health(http_client: httpx.Client, frontend_url: str) -> None:
    r = http_client.get(f"{frontend_url}/api/health")
    r.raise_for_status()
    assert r.json().get("status") == "ok"
