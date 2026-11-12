"""Unit tests for SSRF and URL validation."""

from unittest.mock import MagicMock, patch
import pytest
from lib.errors import PageSiftDocumentError, PageSiftSSRFError
from lib.validation import is_ip_blocked, safe_download_file, validate_target_url


def test_blocked_ip_ranges():
    # Loopback
    assert is_ip_blocked("127.0.0.1")
    assert is_ip_blocked("127.0.0.2")
    assert is_ip_blocked("::1")

    # Private RFC 1918
    assert is_ip_blocked("10.0.0.1")
    assert is_ip_blocked("172.16.0.1")
    assert is_ip_blocked("172.31.255.255")
    assert is_ip_blocked("192.168.1.1")

    # Cloud metadata
    assert is_ip_blocked("169.254.169.254")

    # Public IP
    assert not is_ip_blocked("8.8.8.8")
    assert not is_ip_blocked("1.1.1.1")


def test_validate_target_url_valid():
    url = "https://example.com/articles/index.html?query=test"
    assert validate_target_url(url, allow_private=False) == url


def test_validate_target_url_scheme_blocking():
    with pytest.raises(PageSiftSSRFError, match="Unsupported scheme"):
        validate_target_url("ftp://example.com", allow_private=False)

    with pytest.raises(PageSiftSSRFError, match="Unsupported scheme"):
        validate_target_url("file:///etc/passwd", allow_private=False)


def test_validate_target_url_private_ip_blocking():
    with pytest.raises(PageSiftSSRFError):
        validate_target_url("http://127.0.0.1:8080/metrics", allow_private=False)

    with pytest.raises(PageSiftSSRFError):
        validate_target_url("http://169.254.169.254/latest/meta-data/", allow_private=False)

    with pytest.raises(PageSiftSSRFError):
        validate_target_url("http://192.168.1.100/admin", allow_private=False)


def test_validate_target_url_allow_private_for_server():
    server_url = "http://127.0.0.1:3002"
    assert validate_target_url(server_url, allow_private=True) == server_url


def test_safe_download_file_redirect_ssrf_blocked():
    mock_resp_redirect = MagicMock()
    mock_resp_redirect.status_code = 302
    mock_resp_redirect.headers = {"Location": "http://169.254.169.254/secret"}

    with patch("requests.Session.get", return_value=mock_resp_redirect):
        with pytest.raises(PageSiftSSRFError, match="forbidden"):
            safe_download_file("https://example.com/file.pdf")


def test_safe_download_file_content_length_exceeded():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Length": str(60 * 1024 * 1024)}

    with patch("requests.Session.get", return_value=mock_resp):
        with pytest.raises(PageSiftDocumentError, match="exceeds maximum limit"):
            safe_download_file("https://example.com/huge.pdf", max_size=50 * 1024 * 1024)


def test_safe_download_file_stream_truncation():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {}
    mock_resp.iter_content.return_value = [b"a" * 1024 * 1024, b"b" * 1024 * 1024]

    with patch("requests.Session.get", return_value=mock_resp):
        with pytest.raises(PageSiftDocumentError, match="stream exceeded maximum size limit"):
            safe_download_file("https://example.com/huge.pdf", max_size=1 * 1024 * 1024)

