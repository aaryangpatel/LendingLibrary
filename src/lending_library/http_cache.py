"""In-process cache and shared HTTP client for catalog APIs.

Usage:
    from lending_library.http_cache import cached_get_json, remember

    payload = cached_get_json("https://openlibrary.org/search.json?q=dune")
"""

from collections import OrderedDict
from typing import Any

import httpx

from lending_library.config import settings


_CACHE_LIMIT = 256
_cache: OrderedDict[str, Any] = OrderedDict()
_http = httpx.Client(
    timeout=12.0,
    follow_redirects=True,
    headers={"User-Agent": settings.open_library_user_agent},
)


def remember(key: str, value: Any) -> Any:
    """Store a JSON-serializable lookup result in the bounded memory cache.

    Parameters:
        key: Cache key, typically the request URL.
        value: Parsed JSON payload or normalized book record.

    Returns:
        The same value that was stored.
    """
    if key in _cache:
        _cache.move_to_end(key)
    _cache[key] = value
    while len(_cache) > _CACHE_LIMIT:
        _cache.popitem(last=False)
    return value


def cache_get(key: str) -> Any | None:
    """Return a cached payload or None on a miss.

    Parameters:
        key: Cache key, typically the request URL.

    Returns:
        Previously stored value, or None.
    """
    if key not in _cache:
        return None
    _cache.move_to_end(key)
    return _cache[key]


def cached_get_json(url: str) -> dict[str, Any] | list[Any] | None:
    """GET a URL and parse JSON, using the in-process cache.

    Parameters:
        url: Absolute HTTP URL.

    Returns:
        Parsed JSON object, or None when the server does not return 200 JSON.
    """
    cached = cache_get(url)
    if cached is not None:
        return cached
    response = _http.get(url)
    if response.status_code != 200:
        return remember(url, None)
    text = response.text.strip()
    if not text or text[0] not in "{[":
        return remember(url, None)
    payload = response.json()
    return remember(url, payload)
