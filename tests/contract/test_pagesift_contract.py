"""Integration contract tests against live PageSift 1.6.x endpoints.

These tests run when a PageSift instance is listening on PAGESIFT_BASE_URL (defaults to http://127.0.0.1:3002).
"""

import os
import pytest
import requests

from lib.client import PageSiftClient

BASE_URL = os.environ.get("PAGESIFT_BASE_URL", "http://127.0.0.1:3002")
API_KEY = os.environ.get("PAGESIFT_API_KEY") or None


def is_server_online() -> bool:
    try:
        r = requests.get(f"{BASE_URL}/healthz", timeout=1.0)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not is_server_online(),
    reason=f"PageSift server is not running on {BASE_URL}",
)


def test_contract_healthz_and_auth_probe():
    with PageSiftClient(base_url=BASE_URL, api_key=API_KEY) as client:
        client.validate_connection()


def test_contract_parse_html_and_csv_with_parsers_and_chunking():
    html_bytes = b"<html><head><title>Contract</title></head><body><main><h1>Hello</h1><p>PageSift 1.6.3</p></main></body></html>"
    with PageSiftClient(base_url=BASE_URL, api_key=API_KEY) as client:
        res = client.parse_document(
            file_bytes=html_bytes,
            filename="contract.html",
            content_type="text/html",
            chunking={"type": "recursive", "size": 200},
            source_url="https://example.com/docs/contract.html",
        )
        assert res.get("success") is True
        assert "PageSift 1.6.3" in res["data"].get("markdown", "")
        assert isinstance(res["data"].get("chunks"), list)


def test_contract_context_pack_stateless():
    docs = [
        {
            "url": "https://docs.example.com/pricing",
            "title": "Pricing",
            "markdown": "# Pricing\n\nEnterprise plan costs $199/month unless billed annually ($159/month).",
        },
        {
            "url": "https://docs.example.com/limits",
            "title": "Limits",
            "markdown": "# Rate Limits\n\nEnterprise tier allows 600 requests per minute.",
        },
    ]
    with PageSiftClient(base_url=BASE_URL, api_key=API_KEY) as client:
        res = client.context_pack(
            {
                "query": "Enterprise plan price and annual discount",
                "documents": docs,
                "budgetTokens": 512,
                "selector": "submodularClosure",
                "ordering": "edgeSalience",
            }
        )
        assert res.get("success") is True
        pack = res.get("pack") or {}
        assert "199" in pack.get("compiledContext", "")
        assert isinstance(pack.get("provenanceManifest"), list)


def test_contract_context_learn_readonly():
    with PageSiftClient(base_url=BASE_URL, api_key=API_KEY) as client:
        res = client.context_learn_status()
        assert res.get("success") is True
        assert "learn" in res


def test_contract_graph_conflicts_and_sources_list():
    with PageSiftClient(base_url=BASE_URL, api_key=API_KEY) as client:
        conflicts = client.get_graph_conflicts(limit=10)
        assert conflicts.get("success") is True
        assert isinstance(conflicts.get("conflicts", []), list)

        sources = client.list_sources()
        assert sources.get("success") is True
        assert isinstance(sources.get("sources", []), list)
