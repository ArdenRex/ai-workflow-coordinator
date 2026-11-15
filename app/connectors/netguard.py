"""Outbound-host guard (SSRF defence). Users supply connector base URLs, so the server must
never be steerable at internal infrastructure (cloud metadata 169.254.169.254, localhost,
RFC1918 ranges, ...). A host passes only if EVERY address it resolves to is globally routable.

Known limit: resolve-then-connect leaves a DNS-rebinding window. Closing it needs a pinned
transport or an egress proxy (Step 14).
"""
import ipaddress
import socket
from urllib.parse import urlparse

from app.connectors.errors import ConnectorConfigError

_getaddrinfo = socket.getaddrinfo      # looked up at call time so tests can substitute it


def _ip_ok(ip: ipaddress._BaseAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def assert_public_host(url: str, *, allow_private: bool = False, resolve_dns: bool = True) -> None:
    host = urlparse(url).hostname
    if not host:
        raise ConnectorConfigError("base_url has no host")
    if allow_private:
        return
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not _ip_ok(literal):
            raise ConnectorConfigError("Host is not allowed")
        return
    if host.lower() in {"localhost"} or host.lower().endswith((".localhost", ".local", ".internal")):
        raise ConnectorConfigError("Host is not allowed")
    if not resolve_dns:
        return
    try:
        infos = _getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError:
        raise ConnectorConfigError("Host could not be resolved") from None
    addrs = {i[4][0].split("%")[0] for i in infos}
    if not addrs or not all(_ip_ok(ipaddress.ip_address(a)) for a in addrs):
        raise ConnectorConfigError("Host is not allowed")
