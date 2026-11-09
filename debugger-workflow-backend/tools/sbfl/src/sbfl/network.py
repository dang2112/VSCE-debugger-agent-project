"""Best-effort Python socket guard; subprocess/native networking is out of scope."""
from __future__ import annotations

import ipaddress
import socket
from contextlib import ExitStack
from unittest.mock import patch
import pytest


class ExternalNetworkBlocked(pytest.skip.Exception):
    """Skip the test without being caught by ordinary application handlers."""
    pass


def is_local(host: str | bytes) -> bool:
    """Allow only explicit loopback addresses/names, without resolving DNS.

    Private LAN addresses are intentionally external to this policy: they may
    depend on services unavailable in another developer's environment.
    """
    if isinstance(host, bytes):
        host = host.decode("ascii", errors="replace")
    if isinstance(host, str) and host.lower().removesuffix(".") == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
        return address.is_loopback or bool(
            getattr(address, "ipv4_mapped", None)
            and address.ipv4_mapped.is_loopback
        )
    except (ValueError, TypeError):
        return False


class NetworkGuard:
    def __init__(self):
        self.attempts = []
        self.stack = ExitStack()

    def check(self, operation, host):
        if not is_local(host):
            self.attempts.append({"operation": operation, "host": str(host)})
            raise ExternalNetworkBlocked(f"External network blocked: {host}")

    def __enter__(self):
        for name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr"):
            original = getattr(socket, name)
            def resolve(host, *args, _name=name, _original=original, **kwargs):
                # None asks getaddrinfo for local bind/loopback addresses; it
                # does not identify an external DNS destination.
                if not (_name == "getaddrinfo" and host is None):
                    self.check(_name, host)
                return _original(host, *args, **kwargs)
            self.stack.enter_context(patch.object(socket, name, resolve))
        for name in ("connect", "connect_ex", "sendto"):
            original = getattr(socket.socket, name)
            def operation(sock, *args, _name=name, _original=original, **kwargs):
                if sock.family in (socket.AF_INET, socket.AF_INET6):
                    address = args[-1] if _name == "sendto" else args[0]
                    self.check(_name, address[0])
                return _original(sock, *args, **kwargs)
            self.stack.enter_context(patch.object(socket.socket, name, operation))
        # A fixture or imported module may have connected a socket before the
        # guard started. Check its peer before allowing connected writes.
        for name in ("send", "sendall", "sendmsg"):
            if not hasattr(socket.socket, name):
                continue
            original = getattr(socket.socket, name)
            def send(sock, *args, _name=name, _original=original, **kwargs):
                if sock.family in (socket.AF_INET, socket.AF_INET6):
                    # sendmsg may specify an unconnected UDP destination.
                    destination = None
                    if _name == "sendmsg":
                        destination = args[3] if len(args) > 3 else kwargs.get("address")
                    if destination is not None:
                        self.check(_name, destination[0])
                    else:
                        try:
                            peer = sock.getpeername()
                        except OSError:
                            pass  # Preserve the normal unconnected-socket error.
                        else:
                            self.check(_name, peer[0])
                return _original(sock, *args, **kwargs)
            self.stack.enter_context(patch.object(socket.socket, name, send))
        return self

    def __exit__(self, *exc):
        return self.stack.__exit__(*exc)
