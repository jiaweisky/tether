"""Network-address helpers shared across layers."""

from __future__ import annotations

import ipaddress
import socket

from tether.util.logging import get_logger

log = get_logger("tether.net")


def is_public_host(host: str) -> bool:
    """Whether every address ``host`` resolves to is public.

    Rejects private, loopback, link-local and reserved addresses, so a
    bridge-initiated fetch cannot be steered at the internal network (SSRF).
    A host that does not resolve is treated as not public.
    """
    if not host:
        return False

    try:
        addresses = socket.getaddrinfo(host, None)
    except OSError:
        return False

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            log.warning("ssrf_blocked", host=host)
            return False

    return True
