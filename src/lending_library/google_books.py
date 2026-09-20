"""Google Books fallback lookup used only when Open Library has no match.

Usage:
    from lending_library.google_books import lookup_isbn, search_books

    book = lookup_isbn("9780141439518")

The API is free. An API key is optional; when GOOGLE_BOOKS_API_KEY is set
it is appended to requests to raise the daily quota.
"""

from typing import Any
from urllib.parse import urlencode

from lending_library.config import settings
from lending_library.http_cache import cached_get_json
from lending_library.isbn import pick_preferred_isbn
from lending_library.models import BookRecord, clean_subjects


VOLUMES_API = "https://www.googleapis.com/books/v1/volumes"


def _with_key(url: str) -> str:
    """Append the optional Google Books API key to a request URL.

    Parameters:
        url: Fully built Google Books URL without a key.

    Returns:
        URL with `&key=` when a key is configured, otherwise the original URL.
    """
    if not settings.google_books_api_key:
        return url
    return f"{url}&key={settings.google_books_api_key}"


def _https_cover(url: str | None) -> str | None:
    """Upgrade a Google Books thumbnail URL to HTTPS and a larger zoom.

    Parameters:
        url: Thumbnail URL from volumeInfo.imageLinks, or None.

    Returns:
        HTTPS cover URL, or None.
    """
    if not url:
        return None
    upgraded = url.replace("http://", "https://")
    upgraded = upgraded.replace("zoom=1", "zoom=2")
    upgraded = upgraded.replace("&edge=curl", "")
    return upgraded


def _record_from_volume(item: dict[str, Any]) -> BookRecord | None:
    """Convert a Google Books volume into a BookRecord.

    Parameters:
        item: One element of the `items` array from the Volumes API.

    Returns:
        BookRecord, or None when the volume has no title.
    """
    info = item.get("volumeInfo") or {}
    title = str(info.get("title") or "").strip()
    if not title:
        return None
    authors = [str(name) for name in (info.get("authors") or [])]
    industry = info.get("industryIdentifiers") or []
    isbn_candidates = [
        str(entry.get("identifier", ""))
        for entry in industry
        if isinstance(entry, dict)
    ]
    isbn = pick_preferred_isbn(isbn_candidates)
    image_links = info.get("imageLinks") or {}
    cover_url = _https_cover(
        image_links.get("thumbnail") or image_links.get("smallThumbnail")
    )
    subjects = clean_subjects(info.get("categories") or [])
    published = str(info.get("publishedDate") or "")
    year = None
    if len(published) >= 4 and published[:4].isdigit():
        year = int(published[:4])
    return BookRecord(
        isbn=isbn,
        title=title,
        authors=authors,
        cover_url=cover_url,
        openlibrary_id=None,
        subjects=subjects,
        publish_year=year,
        source="google_books",
    )


def _volumes(query: str, limit: int) -> list[BookRecord]:
    """Run a Google Books volumes search and normalize results.

    Parameters:
        query: Google Books `q` parameter, including fielded prefixes.
        limit: Maximum number of records to return.

    Returns:
        A list of BookRecord values, possibly empty.
    """
    params = {
        "q": query,
        "maxResults": str(max(1, min(limit, 8))),
        "printType": "books",
    }
    url = _with_key(f"{VOLUMES_API}?{urlencode(params)}")
    payload = cached_get_json(url)
    if not isinstance(payload, dict):
        return []
    items = payload.get("items") or []
    records: list[BookRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        record = _record_from_volume(item)
        if record is not None:
            records.append(record)
    return records


def lookup_isbn(isbn: str) -> BookRecord | None:
    """Look up a volume by ISBN on Google Books.

    Parameters:
        isbn: Normalized ISBN-13.

    Returns:
        The first matching BookRecord, or None.
    """
    records = _volumes(f"isbn:{isbn}", limit=1)
    if not records:
        return None
    record = records[0]
    if record["isbn"] is None:
        record["isbn"] = isbn
    return record


def search_books(
    query: str = "",
    title: str = "",
    author: str = "",
    limit: int = 5,
) -> list[BookRecord]:
    """Search Google Books by title, author, or free text.

    Parameters:
        query: Unfielded search string.
        title: Title words, mapped to intitle:.
        author: Author words, mapped to inauthor:.
        limit: Maximum number of records to return.

    Returns:
        A list of BookRecord values, possibly empty.
    """
    parts: list[str] = []
    if title.strip():
        parts.append(f"intitle:{title.strip()}")
    if author.strip():
        parts.append(f"inauthor:{author.strip()}")
    if query.strip():
        parts.append(query.strip())
    if not parts:
        return []
    return _volumes(" ".join(parts), limit=limit)
