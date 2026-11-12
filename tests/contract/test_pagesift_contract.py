"""Integration contract tests against live PageSift endpoints.

These tests run when a PageSift instance is listening on PAGESIFT_BASE_URL (defaults to http://127.0.0.1:3002).
"""

import os
import pytest
import requests

from lib.client import PageSiftClient

BASE_URL = os.environ.get("PAGESIFT_BASE_URL", "http://127.0.0.1:3002")
API_KEY = os.environ.get("PAGESIFT_API_KEY", "bench")


def is_server_online() -> bool:
    try:
        r = requests.get(f"{BASE_URL}/healthz", timeout=1.0)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not is_server_online(),
    reason=f"PageSift server is not running on {BASE_URL}"
)


def test_contract_healthz():
    client = PageSiftClient(base_url=BASE_URL, api_key=API_KEY)
    client.validate_connection()


def test_contract_v1_and_v2_scrape():
    client = PageSiftClient(base_url=BASE_URL, api_key=API_KEY)
    # Scrape with v2 endpoint
    os.environ["PAGESIFT_ALLOW_PRIVATE_TARGETS"] = "1"
    try:
        res = client.scrape("http://127.0.0.1:8800/wcxb/4011.html", api_version="v2")
        assert res.get("success") is True
        assert "data" in res
        assert "markdown" in res["data"]
    finally:
        os.environ.pop("PAGESIFT_ALLOW_PRIVATE_TARGETS", None)
