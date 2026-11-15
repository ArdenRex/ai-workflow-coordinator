"""Client address behind reverse proxies (15.2).

With TRUSTED_PROXY_COUNT=0 (the default) only the direct peer is used and X-Forwarded-For is ignored, so a client can never choose its own
address. With N proxies in front, the address is the N-th entry from the RIGHT of X-Forwarded-For: the entries on the right were appended
by your own proxies, anything further left was supplied by the client and is ignored. If the header is missing, shorter than N or not an
IP address, the direct peer is used. Only set N when the app is reachable ONLY through those proxies.
"""
import ipaddress

from fastapi import Request


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    n = int(getattr(request.app.state, "trusted_proxy_count", 0) or 0)
    if n <= 0:
        return peer
    entries = [e.strip() for e in request.headers.get("x-forwarded-for", "").split(",") if e.strip()]
    if len(entries) < n:
        return peer
    try:
        return str(ipaddress.ip_address(entries[-n]))
    except ValueError:
        return peer
