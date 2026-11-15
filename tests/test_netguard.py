import socket

import pytest

from app.connectors import netguard
from app.connectors.errors import ConnectorConfigError


def fake_dns(*addrs):
    return lambda host, port, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 0)) for a in addrs]


@pytest.mark.parametrize("url", [
    "https://127.0.0.1", "https://10.0.0.5/x", "https://192.168.1.1", "https://172.16.0.1",
    "https://169.254.169.254/latest/meta-data", "https://[::1]/", "https://[fd00::1]/", "https://0.0.0.0",
    "https://100.64.0.1", "https://[::ffff:127.0.0.1]/", "https://localhost", "https://db.internal",
    "https://printer.local", "https://224.0.0.1"])
def test_blocks_internal_literals_and_names(url):
    with pytest.raises(ConnectorConfigError):
        netguard.assert_public_host(url)


def test_allows_public_literal():
    netguard.assert_public_host("https://93.184.216.34")


def test_dns_all_addresses_must_be_public(monkeypatch):
    monkeypatch.setattr(netguard, "_getaddrinfo", fake_dns("93.184.216.34"))
    netguard.assert_public_host("https://ok.example")
    monkeypatch.setattr(netguard, "_getaddrinfo", fake_dns("93.184.216.34", "10.0.0.1"))   # one bad address is enough
    with pytest.raises(ConnectorConfigError):
        netguard.assert_public_host("https://mixed.example")
    monkeypatch.setattr(netguard, "_getaddrinfo", fake_dns("169.254.169.254"))
    with pytest.raises(ConnectorConfigError):
        netguard.assert_public_host("https://rebind.example")


def test_unresolvable_host_rejected(monkeypatch):
    def boom(*a, **k):
        raise socket.gaierror("nope")
    monkeypatch.setattr(netguard, "_getaddrinfo", boom)
    with pytest.raises(ConnectorConfigError):
        netguard.assert_public_host("https://nowhere.example")


def test_allow_private_for_dev_and_no_dns_mode():
    netguard.assert_public_host("http://localhost:8000", allow_private=True)
    netguard.assert_public_host("https://anything.example", resolve_dns=False)      # create-time: no DNS
    with pytest.raises(ConnectorConfigError):
        netguard.assert_public_host("https://127.0.0.1", resolve_dns=False)
