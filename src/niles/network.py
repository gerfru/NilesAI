# SPDX-License-Identifier: AGPL-3.0-only
"""Shared network security utilities (SSRF protection).

Extracted from mcp/fetch/server.py for reuse across the application.
"""

import ipaddress
import socket

# Private/reserved IP networks (SSRF protection)
PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def is_private_host(hostname: str) -> bool:
    """Check if a hostname resolves to a private/reserved IP address.

    Returns True if any resolved address is in a private/reserved network.
    Returns True if DNS resolution fails (fail-closed: block unknown hosts
    rather than allowing potential SSRF via DNS rebinding).
    """
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return True
    for _family, _type, _proto, _canonname, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if any(ip in net for net in PRIVATE_NETWORKS):
            return True
    return False


def resolve_public_ip(hostname: str) -> str | None:
    """Resolve a hostname to one validated public IP (DNS-rebinding safe).

    Performs a SINGLE DNS resolution and returns the first address only if
    EVERY resolved address is public. Returns None if any address is
    private/reserved or resolution fails (fail closed).

    Callers must then connect to the returned IP literal (not re-resolve the
    hostname) to close the TOCTOU window an attacker-controlled DNS could use
    to return a public IP for validation and a private IP for the connection.
    """
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return None
    first: str | None = None
    for _family, _type, _proto, _canonname, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if any(ip in net for net in PRIVATE_NETWORKS):
            return None
        if first is None:
            first = str(ip)
    return first
