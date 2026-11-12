"""Unit tests for PageSiftClient."""

from unittest.mock import MagicMock, patch
import pytest

from lib.client import PageSiftClient
from lib.errors import (
    PageSiftAuthError,
    PageSiftDocumentError,
    PageSiftRateLimitError,
    PageSiftServiceError,
    PageSiftTimeoutError,
)


def test_client_init_headers():
    client = PageSiftClient(base_url="http://127.0.0.1:3002", api_key="sk-test-secret")
    headers = client._get_headers()
    assert headers["Authorization"] == "Bearer sk-test-secret"
    assert "dify-plugin-pagesift" in headers["User-Agent"]


@patch("requests.Session.post")
def test_scrape_success(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "success": True,
        "data": {
            "markdown": "# Header\n\nContent paragraph",
            "metadata": {"title": "Test Page"}
        }
    }
    mock_post.return_value = mock_resp

    client = PageSiftClient(base_url="http://127.0.0.1:3002")
    res = client.scrape(url="https://example.com/test", only_main_content=True)
    assert res["success"] is True
    assert res["data"]["markdown"] == "# Header\n\nContent paragraph"


@patch("requests.Session.post")
def test_scrape_auth_error(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.json.return_value = {"success": False, "error": "Unauthorized"}
    mock_post.return_value = mock_resp

    client = PageSiftClient(base_url="http://127.0.0.1:3002", api_key="bad-key")
    with pytest.raises(PageSiftAuthError):
        client.scrape("https://example.com/article")


@patch("requests.Session.post")
def test_scrape_rate_limit_error(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.headers = {"Retry-After": "5"}
    mock_resp.json.return_value = {"success": False, "error": "Too Many Requests"}
    mock_post.return_value = mock_resp

    client = PageSiftClient(base_url="http://127.0.0.1:3002")
    with pytest.raises(PageSiftRateLimitError) as exc_info:
        client.scrape("https://example.com/article")
    assert exc_info.value.retry_after == 5.0


def test_parse_document_empty_bytes():
    client = PageSiftClient(base_url="http://127.0.0.1:3002")
    with pytest.raises(PageSiftDocumentError, match="empty"):
        client.parse_document(file_bytes=b"")
