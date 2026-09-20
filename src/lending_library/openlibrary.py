"""Open Library lookups by ISBN and by title or author.

Usage:
    from lending_library.openlibrary import lookup_isbn, search_books

    book = lookup_isbn("9780141439518")
    matches = search_books(title="Pride and Prejudice", author="Austen")

Open Library is free and does not require an API key. All requests send
the User-Agent configured in settings and are cached in process memory.
"""

from typing import Any
from urllib.parse import urlencode

from lending_library.http_cache import cached_get_json
from lending_library.isbn import pick_preferred_isbn
from lending_library.models import BookRecord, clean_subjects


COVER_BY_ISBN = "https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg"
COVER_BY_ID = "https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"
SEARCH_API = "https://openlibrary.org/search.json"


def _cover_from_isbn(isbn: str | None) -> str | None:
    """Build a medium Open Library cover URL for an ISBN.

    Parameters:
        isbn: ISBN-13, or None.

    Returns:
        Cover URL, or None when isbn is missing.
    """
    if isbn is None:
        return None
    return COVER_BY_ISBN.format(isbn=isbn)


def _year_from_value(value: Any) -> int | None:
    """Parse a publish year from Open Library string or int fields.

    Parameters:
        value: Year as int, string, or nested publish_date.

    Returns:
        Four-digit year, or None.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value)
    for token in text.replace(",", " ").split():
        if len(token) == 4 and token.isdigit():
            return int(token)
    return None


def _record_from_search_doc(doc: dict[str, Any]) -> BookRecord | None:
    """Convert an Open Library Search API document into a BookRecord.

    Parameters:
        doc: One element of the Search API `docs` array.

    Returns:
        BookRecord, or None when the document has no title.
    """
    title = str(doc.get("title") or "").strip()
    if not title:
        return None
    authors = [str(name) for name in (doc.get("author_name") or [])]
    isbn = pick_preferred_isbn([str(item) for item in (doc.get("isbn") or [])])
    cover_id = doc.get("cover_i")
    cover_url = None
    if cover_id:
        cover_url = COVER_BY_ID.format(cover_id=cover_id)
    elif isbn:
        cover_url = _cover_from_isbn(isbn)
    subjects = clean_subjects(doc.get("subject") or [])
    return BookRecord(
        isbn=isbn,
        title=title,
        authors=authors,
        cover_url=cover_url,
        openlibrary_id=str(doc.get("key") or "") or None,
        subjects=subjects,
        publish_year=_year_from_value(doc.get("first_publish_year")),
        source="openlibrary",
    )


def lookup_isbn(isbn: str) -> BookRecord | None:
    """Look up a single edition by ISBN using the Open Library Search API.

    Parameters:
        isbn: Normalized ISBN-13.

    Returns:
        BookRecord if Open Library knows the ISBN, otherwise None.
    """
    params = {
        "isbn": isbn,
        "limit": "1",
        "fields": "key,title,author_name,isbn,cover_i,first_publish_year,subject",
    }
    url = f"{SEARCH_API}?{urlencode(params)}"
    payload = cached_get_json(url)
    if not isinstance(payload, dict):
        return None
    docs = payload.get("docs") or []
    if not docs or not isinstance(docs[0], dict):
        return None
    record = _record_from_search_doc(docs[0])
    if record is None:
        return None
    record["isbn"] = isbn
    return record


def search_books(
    query: str = "",
    title: str = "",
    author: str = "",
    limit: int = 5,
) -> list[BookRecord]:
    """Search Open Library by free text, title, and/or author.

    Parameters:
        query: Unfielded search string, used when title is empty.
        title: Title words to require.
        author: Author name words to require.
        limit: Maximum number of records to return (1-8).

    Returns:
        A list of BookRecord values, possibly empty.
    """
    params: dict[str, str] = {
        "limit": str(max(1, min(limit, 8))),
        "fields": "key,title,author_name,isbn,cover_i,first_publish_year,subject",
    }
    if title.strip():
        params["title"] = title.strip()
    if author.strip():
        params["author"] = author.strip()
    if query.strip() and "title" not in params:
        params["q"] = query.strip()
    elif query.strip() and "title" in params:
        params["q"] = query.strip()
    if "q" not in params and "title" not in params:
        return []
    url = f"{SEARCH_API}?{urlencode(params)}"
    payload = cached_get_json(url)
    if not isinstance(payload, dict):
        return []
    docs = payload.get("docs") or []
    records: list[BookRecord] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        record = _record_from_search_doc(doc)
        if record is not None:
            records.append(record)
    return records
