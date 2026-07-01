"""Geolocation lookup for a proxy's exit IP.

Aligns the browser's timezone / geolocation with the proxy so the two signals
don't contradict each other during scoring. Uses ipwho.is: HTTPS, keyless, and
returns the current UTC offset directly (so no local DST recomputation).
"""
from __future__ import annotations

import logging

import requests

log = logging.getLogger("recap.location")

_ENDPOINT = "https://ipwho.is/?fields=success,latitude,longitude,timezone"


def lookup(proxy_url: str | None, timeout: float = 8.0) -> dict | None:
    """Return {lat, lon, timezone, tz_offset} for the proxy's exit IP.

    tz_offset is in JS `getTimezoneOffset()` form (minutes, sign inverted).
    Returns None on any failure; the caller proceeds without geo alignment.
    """
    try:
        proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
        data = requests.get(_ENDPOINT, proxies=proxies, timeout=timeout).json()
    except Exception as exc:
        log.warning("geo lookup failed (%s); continuing without alignment", exc)
        return None

    if not data.get("success"):
        log.warning("geo lookup unsuccessful; continuing without alignment")
        return None

    tz = data.get("timezone") or {}
    offset_seconds = tz.get("offset")
    return {
        "lat": data.get("latitude"),
        "lon": data.get("longitude"),
        "timezone": tz.get("id"),
        "tz_offset": -int(offset_seconds / 60) if offset_seconds is not None else None,
    }
