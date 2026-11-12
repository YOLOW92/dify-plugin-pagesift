"""SSRF, URL and input boundary validation for PageSift Dify Plugin."""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse

from lib.errors import PageSiftSSRFError

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
