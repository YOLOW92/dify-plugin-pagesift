"""Unit tests for SSRF and URL validation."""

import pytest
from lib.errors import PageSiftSSRFError
from lib.validation import is_ip_blocked, validate_target_url


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
