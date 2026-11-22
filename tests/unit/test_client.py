"""Unit tests for PageSiftClient (PageSift 1.6.3 HTTP API contracts)."""

import json
from unittest.mock import MagicMock, patch
import pytest

from lib.client import PageSiftClient
from lib.errors import (
    PageSiftAuthError,
    PageSiftDocumentError,
    PageSiftForbiddenError,
    PageSiftInvalidRequestError,
    PageSiftNotFoundError,
    PageSiftRateLimitError,
    PageSiftServiceError,
    PageSiftSSRFError,
    PageSiftTimeoutError,
    PageSiftUnsupportedError,
)


def _mock_response(status_code=200, body=None, headers=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.text = text or (json.dumps(body) if body is not None else "")
    if body is not None:
        resp.json.return_value = body
    else:
        resp.json.side_effect = ValueError("not json")
    return resp


def test_client_init_headers_with_session_id():
    with PageSiftClient(
        base_url="http://127.0.0.1:3002/",
        api_key="sk-test-secret",
        session_id="ws-tenant-1",
    ) as client:
        headers = client._get_headers()
        assert client.base_url == "http://127.0.0.1:3002"
        assert headers["Authorization"] == "Bearer sk-test-secret"
        assert headers["X-Session-Id"] == "ws-tenant-1"
        assert headers["User-Agent"] == "dify-plugin-pagesift/0.2.0"


@patch("requests.Session.get")
def test_validate_connection_uses_healthz_and_crawl_active(mock_get):
    mock_get.side_effect = [
        _mock_response(200, text="ok"),
        _mock_response(200, {"success": True, "crawls": []}),
    ]
    with PageSiftClient(base_url="http://127.0.0.1:3002") as client:
        client.validate_connection()

    assert mock_get.call_count == 2
    assert mock_get.call_args_list[0].args[0].endswith("/healthz")
    assert mock_get.call_args_list[1].args[0].endswith("/v2/crawl/active")


@patch("requests.Session.get")
def test_validate_connection_rejects_missing_api_key_when_server_requires_auth(mock_get):
    mock_get.side_effect = [
        _mock_response(200, text="ok"),
        _mock_response(401, {"success": False, "code": "UNAUTHORIZED", "error": "missing key"}),
    ]
    with PageSiftClient(base_url="http://127.0.0.1:3002", api_key=None) as client:
        with pytest.raises(PageSiftAuthError, match="requires an API Key"):
            client.validate_connection()


@patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))])
@patch("requests.Session.request")
def test_scrape_1_6_3_payload(mock_request, _mock_dns):
    mock_request.return_value = _mock_response(
        200,
        {
            "success": True,
            "data": {
                "markdown": "# Header\n\nContent",
                "metadata": {"title": "Test Page", "url": "https://example.com/test"},
                "chunks": [{"text": "Content", "headingPath": ["Header"], "start": 0, "end": 7, "tokens": 2}],
                "extract": [{"name": "Item A"}],
                "graph": {"node": {"id": "n1"}},
            },
        },
    )

    schema = {"baseSelector": ".item", "fields": [{"name": "name", "selector": "h2", "type": "text"}]}
    with PageSiftClient(base_url="http://127.0.0.1:3002") as client:
        res = client.scrape(
            url="https://example.com/test",
            formats=["markdown", "links"],
            only_main_content=True,
            engine="http",
            include_tags=["main"],
            exclude_tags=["nav"],
            max_age=0,
            query_filter={"query": "pricing", "maxTokens": 500},
            chunking={"type": "recursive", "size": 400},
            extract_schema=schema,
            image_assets="embed",
            graph=True,
        )

    assert res["success"] is True
    call_kwargs = mock_request.call_args.kwargs
    sent = call_kwargs["json"]
    assert call_kwargs["method"] == "POST"
    assert call_kwargs["url"].endswith("/v2/scrape")
    assert sent["engine"] == "http"
    assert sent["maxAge"] == 0
    assert sent["includeTags"] == ["main"]
    assert sent["excludeTags"] == ["nav"]
    assert sent["queryFilter"] == {"query": "pricing", "maxTokens": 500}
    assert sent["chunking"] == {"type": "recursive", "size": 400}
    assert sent["imageAssets"] == "embed"
    assert sent["graph"] is True
    assert {"type": "extract", "schema": schema} in sent["formats"]


@patch("requests.Session.post")
def test_parse_document_uses_standard_parsers_not_ignored_ocr_key(mock_post):
    mock_post.return_value = _mock_response(
        200,
        {"success": True, "data": {"markdown": "# Scanned PDF", "metadata": {"numPages": 2}}},
    )

    with PageSiftClient(base_url="http://127.0.0.1:3002") as client:
        res = client.parse_document(
            file_bytes=b"%PDF-1.7 dummy",
            filename="scan.pdf",
            content_type="application/pdf",
            ocr=True,
            max_pages=25,
            per_page=True,
            query_filter="revenue",
            chunking={"type": "headings"},
            graph=True,
            source_url="https://docs.example.com/report.html",
        )

    assert res["success"] is True
    kwargs = mock_post.call_args.kwargs
    assert "options" in kwargs["data"]
    assert kwargs["data"]["url"] == "https://docs.example.com/report.html"
    opts = json.loads(kwargs["data"]["options"])
    assert "ocr" not in opts  # Must NOT send the legacy ignored key
    assert opts["parsers"] == [
        {"type": "pdf", "mode": "ocr", "maxPages": 25, "pages": True},
        "image",
    ]
    assert opts["queryFilter"] == "revenue"
    assert opts["chunking"] == {"type": "headings"}
    assert opts["graph"] is True
    assert kwargs["files"]["file"][0] == "scan.pdf"
    assert kwargs["files"]["file"][2] == "application/pdf"


def test_parse_document_empty_bytes():
    with PageSiftClient(base_url="http://127.0.0.1:3002") as client:
        with pytest.raises(PageSiftDocumentError, match="empty"):
            client.parse_document(file_bytes=b"")


@patch("requests.Session.request")
def test_crawl_pagination_and_errors_without_success_field(mock_request):
    mock_request.side_effect = [
        _mock_response(200, {"success": True, "status": "completed", "data": [{"metadata": {"url": "https://a/2"}}]}),
        _mock_response(200, {"errors": [{"url": "https://a/bad", "code": "TIMEOUT"}], "robotsBlocked": ["https://a/priv"]}),
    ]

    with PageSiftClient(base_url="http://127.0.0.1:3002") as client:
        first = {
            "success": True,
            "status": "completed",
            "next": "http://127.0.0.1:3002/v2/crawl/j1?skip=1",
            "data": [{"metadata": {"url": "https://a/1"}}],
        }
        pages = client.collect_all_job_pages(
            lambda skip: client.get_crawl_status("j1", skip=skip),
            first,
            max_pages=10,
        )
        errs = client.get_crawl_errors("j1")

    assert len(pages) == 2
    assert pages[1]["metadata"]["url"] == "https://a/2"
    assert errs["robotsBlocked"] == ["https://a/priv"]


@patch("requests.Session.request")
def test_context_fixed_routes_strip_conflicting_op_and_use_readonly_get_learn(mock_request):
    mock_request.side_effect = [
        _mock_response(200, {"success": True, "sourceId": "kb", "liveUnitCount": 4}),
        _mock_response(200, {"success": True, "learn": {"enabled": True, "frozen": False}}),
        _mock_response(200, {"success": True, "driftTriggered": False, "learn": {"frozen": True}}),
    ]
    with PageSiftClient(base_url="http://127.0.0.1:3002") as client:
        client.context_ingest({"action": "wrong", "op": "bad", "sourceId": "kb", "documents": []})
        client.context_learn_status()
        client.context_learn_update({"frozen": True})

    ingest_call = mock_request.call_args_list[0].kwargs
    assert ingest_call["url"].endswith("/v2/context/ingest")
    assert "action" not in ingest_call["json"]
    assert "op" not in ingest_call["json"]

    learn_get = mock_request.call_args_list[1].kwargs
    assert learn_get["method"] == "GET"
    assert learn_get["url"].endswith("/v2/context/learn")

    learn_post = mock_request.call_args_list[2].kwargs
    assert learn_post["method"] == "POST"
    assert learn_post["json"] == {"frozen": True}


@pytest.mark.parametrize(
    "status,code,exc_cls",
    [
        (401, "UNAUTHORIZED", PageSiftAuthError),
        (429, "QUOTA_EXCEEDED", PageSiftRateLimitError),
        (429, "CONCURRENCY_LIMIT_EXCEEDED", PageSiftRateLimitError),
        (429, "RATE_LIMIT_EXCEEDED", PageSiftRateLimitError),
        (408, "TIMEOUT", PageSiftTimeoutError),
        (403, "ROBOTS_DISALLOWED", PageSiftForbiddenError),
        (403, "ACCESS_BARRIER", PageSiftForbiddenError),
        (403, "FORBIDDEN", PageSiftForbiddenError),
        (400, "SSRF_BLOCKED", PageSiftSSRFError),
        (400, "UNSUPPORTED_OPTION", PageSiftUnsupportedError),
        (400, "INVALID_REQUEST", PageSiftInvalidRequestError),
        (413, "TOO_LARGE", PageSiftDocumentError),
        (404, "NOT_FOUND", PageSiftNotFoundError),
        (410, "SESSION_GONE", PageSiftNotFoundError),
        (500, "INTERNAL_ERROR", PageSiftServiceError),
        (503, "HOST_COOLDOWN", PageSiftServiceError),
    ],
)
@patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))])
@patch("requests.Session.request")
def test_1_6_3_error_code_mapping(mock_request, _mock_dns, status, code, exc_cls):
    mock_request.return_value = _mock_response(
        status,
        {"success": False, "code": code, "error": f"err {code}", "details": {"needsHuman": True}},
        headers={"Retry-After": "7"} if status == 429 else None,
    )
    with PageSiftClient(base_url="http://127.0.0.1:3002") as client:
        with pytest.raises(exc_cls) as exc_info:
            client.scrape("https://example.com/page")
    assert exc_info.value.code == code
    if status == 429:
        assert exc_info.value.retry_after == 7.0
    if code == "ACCESS_BARRIER":
        assert exc_info.value.details == {"needsHuman": True}
