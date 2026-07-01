"""Proxy string parsing tuned for Playwright's native proxy support.

Playwright accepts auth proxies directly, so unlike the extension-based
approach this only needs to split a proxy URL into Playwright's dict shape.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Proxy:
    scheme: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None

    @property
    def server(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"

    @property
    def url(self) -> str:
        """Full URL form, used for outbound geo lookups through the proxy."""
        if self.username and self.password:
            return f"{self.scheme}://{self.username}:{self.password}@{self.host}:{self.port}"
        return self.server

    def playwright(self) -> dict:
        """Playwright `proxy=` option dict."""
        cfg = {"server": self.server}
        if self.username and self.password:
            cfg["username"] = self.username
            cfg["password"] = self.password
        return cfg


def parse(proxy: str | None) -> Proxy | None:
    """Parse `scheme://user:pass@host:port` (scheme optional, defaults http)."""
    if not proxy:
        return None
    scheme, rest = proxy.split("://", 1) if "://" in proxy else ("http", proxy)
    username = password = None
    if "@" in rest:
        auth, rest = rest.rsplit("@", 1)
        if ":" in auth:
            username, password = auth.split(":", 1)
    host, port = rest.rsplit(":", 1)
    return Proxy(scheme=scheme, host=host, port=int(port),
                 username=username, password=password)
