"""SSRF, URL and input boundary validation for PageSift Dify Plugin."""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urljoin, urlparse

import requests

from lib.errors import PageSiftDocumentError, PageSiftSSRFError

# Explicitly blocked CIDRs (RFC 1918, RFC 3927, RFC 6598 CGNAT, Loopback,
# Cloud Metadata, Benchmark, Multicast, Reserved, IPv6 private/local/multicast).
BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),        # RFC 6598 Shared Address Space (CGNAT)
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),       # Link-local & AWS/GCP/Azure Metadata
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),        # Benchmark testing
    ipaddress.ip_network("224.0.0.0/4"),          # Multicast
    ipaddress.ip_network("240.0.0.0/4"),          # Reserved
    ipaddress.ip_network("::/128"),               # IPv6 Unspecified
    ipaddress.ip_network("::1/128"),              # IPv6 Loopback
    ipaddress.ip_network("fc00::/7"),             # IPv6 Unique Local
    ipaddress.ip_network("fe80::/10"),            # IPv6 Link-Local
    ipaddress.ip_network("ff00::/8"),             # IPv6 Multicast
]


def _parse_ip(ip_str: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse an IP literal (stripping optional IPv6 scope IDs), or return None."""
    candidate = ip_str.strip().strip("[]")
    if "%" in candidate:
        candidate = candidate.split("%", 1)[0]
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


def is_ip_blocked(ip_str: str) -> bool:
    """Return True if ip_str is invalid or belongs to any blocked/private range."""
    ip = _parse_ip(ip_str)
    if ip is None:
        return True
    # Unwrap IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1 or ::ffff:169.254.169.254)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(ip in net for net in BLOCKED_NETWORKS)


def validate_target_url(url: str, allow_private: bool = False) -> str:
    """
    Validate target URL against SSRF and protocol manipulation.

    :param url: The target URL to validate.
    :param allow_private: True ONLY when validating the admin-configured PageSift Server URL
        or explicitly trusted internal resources.
    :return: Normalized sanitized URL.
    :raises PageSiftSSRFError: If the URL is invalid or targets a forbidden network address.
    """
    if not url or not isinstance(url, str):
        raise PageSiftSSRFError("URL parameter is missing or empty.")

    clean_url = url.strip()
    parsed = urlparse(clean_url)

    if parsed.scheme.lower() not in ("http", "https"):
        raise PageSiftSSRFError(
            f"Unsupported scheme '{parsed.scheme}'. Only HTTP and HTTPS are permitted."
        )

    hostname = parsed.hostname
    if not hostname:
        raise PageSiftSSRFError("Invalid URL: missing host component.")

    clean_host = hostname.strip("[]")

    if os.environ.get("PAGESIFT_ALLOW_PRIVATE_TARGETS") == "1":
        allow_private = True

    if not allow_private:
        # 1. If hostname is a literal IP address, check it directly without DNS resolution.
        literal_ip = _parse_ip(clean_host)
        if literal_ip is not None:
            if is_ip_blocked(clean_host):
                raise PageSiftSSRFError(
                    f"Access to private/internal network address '{clean_host}' is forbidden."
                )
            return clean_url

        # 2. Resolve hostname and check ALL returned IP addresses (prevents DNS rebinding).
        try:
            port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
            addr_info = socket.getaddrinfo(clean_host, port, proto=socket.IPPROTO_TCP)
            for _family, _socktype, _proto, _canonname, sockaddr in addr_info:
                ip_addr = sockaddr[0]
                if is_ip_blocked(ip_addr):
                    raise PageSiftSSRFError(
                        f"Resolved address '{ip_addr}' for host '{clean_host}' belongs to a private/forbidden network."
                    )
        except socket.gaierror as e:
            raise PageSiftSSRFError(f"Failed to resolve hostname '{clean_host}': {e}") from e

    return clean_url


def safe_download_file(
    url: str,
    max_size: int = 50 * 1024 * 1024,
    timeout: float = 30.0,
    max_redirects: int = 5,
    allow_private: bool = False,
) -> bytes:
    """
    Download file with strict per-hop redirect SSRF validation and stream size enforcement.

    :param url: Initial download URL.
    :param max_size: Maximum allowed file size in bytes (default 50MB).
    :param timeout: Network timeout per hop in seconds.
    :param max_redirects: Maximum allowed redirection hops.
    :param allow_private: Whether private/internal destinations are allowed.
    :return: File content bytes.
    :raises PageSiftSSRFError: If any hop targets a forbidden network address.
    :raises PageSiftDocumentError: If file exceeds max_size or network fails.
    """
    current_url = url
    with requests.Session() as session:
        for hop in range(max_redirects + 1):
            validated_url = validate_target_url(current_url, allow_private=allow_private)

            try:
                resp = session.get(
                    validated_url,
                    stream=True,
                    allow_redirects=False,
                    timeout=timeout,
                )
            except requests.RequestException as e:
                raise PageSiftDocumentError(f"Failed to connect to file URL: {e}") from e

            # Handle HTTP redirections hop-by-hop
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location")
                resp.close()
                if not location:
                    raise PageSiftDocumentError("Redirect status received without Location header.")
                if hop >= max_redirects:
                    raise PageSiftDocumentError(
                        f"Exceeded maximum redirection hops ({max_redirects})."
                    )
                current_url = urljoin(current_url, location)
                continue

            if resp.status_code != 200:
                resp.close()
                raise PageSiftDocumentError(
                    f"Failed to download file (HTTP status {resp.status_code})."
                )

            # Check Content-Length header preemptively if provided
            cl_header = resp.headers.get("Content-Length")
            if cl_header and cl_header.isdigit():
                expected_len = int(cl_header)
                if expected_len > max_size:
                    resp.close()
                    raise PageSiftDocumentError(
                        f"File size {expected_len / (1024 * 1024):.1f}MB exceeds maximum limit of "
                        f"{max_size // (1024 * 1024)}MB.",
                        code="TOO_LARGE",
                        status_code=413,
                    )

            # Stream download with byte-level truncation enforcement
            chunks: list[bytes] = []
            downloaded = 0
            try:
                for chunk in resp.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > max_size:
                        resp.close()
                        raise PageSiftDocumentError(
                            f"File download truncated: stream exceeded maximum size limit of "
                            f"{max_size // (1024 * 1024)}MB.",
                            code="TOO_LARGE",
                            status_code=413,
                        )
                    chunks.append(chunk)
            finally:
                resp.close()

            return b"".join(chunks)

    raise PageSiftDocumentError("Redirection loop detected or exceeded maximum hops.")
