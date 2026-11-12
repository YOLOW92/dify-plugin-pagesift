"""SSRF, URL and input boundary validation for PageSift Dify Plugin."""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urljoin, urlparse

import requests
from lib.errors import PageSiftDocumentError, PageSiftSSRFError

# Explicitly blocked CIDRs (RFC 1918, RFC 3927, Loopback, Cloud Metadata, Multicast)
BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),       # Link-local & AWS/GCP/Azure Metadata
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("224.0.0.0/4"),         # Multicast
    ipaddress.ip_network("240.0.0.0/4"),         # Reserved
    ipaddress.ip_network("::1/128"),             # IPv6 Loopback
    ipaddress.ip_network("fc00::/7"),            # IPv6 Unique Local
    ipaddress.ip_network("fe80::/10"),           # IPv6 Link-Local
]


def is_ip_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        return any(ip in net for net in BLOCKED_NETWORKS)
    except ValueError:
        return True


def validate_target_url(url: str, allow_private: bool = False) -> str:
    """
    Validate target URL against SSRF and protocol manipulation.

    :param url: The target URL to validate.
    :param allow_private: True ONLY when validating the admin-configured PageSift Server URL.
    :return: Normalized sanitized URL.
    :raises PageSiftSSRFError: If the URL is invalid or targets a forbidden network address.
    """
    if not url or not isinstance(url, str):
        raise PageSiftSSRFError("URL parameter is missing or empty.")

    clean_url = url.strip()
    parsed = urlparse(clean_url)

    if parsed.scheme.lower() not in ("http", "https"):
        raise PageSiftSSRFError(f"Unsupported scheme '{parsed.scheme}'. Only HTTP and HTTPS are permitted.")

    hostname = parsed.hostname
    if not hostname:
        raise PageSiftSSRFError("Invalid URL: missing host component.")

    # Normalize literal IPv6 brackets if present
    clean_host = hostname.strip("[]")

    if os.environ.get("PAGESIFT_ALLOW_PRIVATE_TARGETS") == "1":
        allow_private = True

    if not allow_private:
        # Check if the hostname is a direct blocked IP literal
        try:
            if is_ip_blocked(clean_host):
                raise PageSiftSSRFError(f"Access to private/internal network address '{clean_host}' is forbidden.")
        except Exception:
            pass

        # Resolve hostname to check all destination IP addresses (prevent DNS Rebinding)
        try:
            port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
            addr_info = socket.getaddrinfo(clean_host, port, proto=socket.IPPROTO_TCP)
            for family, socktype, proto, canonname, sockaddr in addr_info:
                ip_addr = sockaddr[0]
                if is_ip_blocked(ip_addr):
                    raise PageSiftSSRFError(
                        f"Resolved address '{ip_addr}' for host '{clean_host}' belongs to a private/forbidden network."
                    )
        except socket.gaierror as e:
            raise PageSiftSSRFError(f"Failed to resolve hostname '{clean_host}': {e}")

    return clean_url


def safe_download_file(
    url: str,
    max_size: int = 50 * 1024 * 1024,
    timeout: float = 30.0,
    max_redirects: int = 5,
    allow_private: bool = False,
) -> bytes:
    """
    Download file with strict redirect SSRF validation and stream size enforcement.

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
    session = requests.Session()

    for hop in range(max_redirects + 1):
        # 1. Validate destination before initiating connection (prevents DNS Rebinding)
        validated_url = validate_target_url(current_url, allow_private=allow_private)

        try:
            resp = session.get(
                validated_url,
                stream=True,
                allow_redirects=False,
                timeout=timeout,
            )
        except requests.RequestException as e:
            raise PageSiftDocumentError(f"Failed to connect to file URL: {e}")

        # 2. Check for HTTP Redirections (301, 302, 303, 307, 308)
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location")
            resp.close()
            if not location:
                raise PageSiftDocumentError("Redirect status received without Location header.")
            if hop >= max_redirects:
                raise PageSiftDocumentError(f"Exceeded maximum redirection hops ({max_redirects}).")

            # Resolve relative redirect URLs safely
            current_url = urljoin(current_url, location)
            continue

        # 3. Handle successful response
        if resp.status_code != 200:
            resp.close()
            raise PageSiftDocumentError(f"Failed to download file (HTTP status {resp.status_code}).")

        # 4. Check Content-Length header preemptively if provided
        cl_header = resp.headers.get("Content-Length")
        if cl_header and cl_header.isdigit():
            expected_len = int(cl_header)
            if expected_len > max_size:
                resp.close()
                raise PageSiftDocumentError(
                    f"File size {expected_len / (1024*1024):.1f}MB exceeds maximum limit of {max_size // (1024*1024)}MB."
                )

        # 5. Stream download with byte-level chunk truncation
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
                        f"File download truncated: stream exceeded maximum size limit of {max_size // (1024*1024)}MB."
                    )
                chunks.append(chunk)
        finally:
            resp.close()

        return b"".join(chunks)

    raise PageSiftDocumentError("Redirection loop detected or exceeded maximum hops.")
