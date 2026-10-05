"""Combine Open Library and Google Books into a single lookup pipeline.

Usage:
    from lending_library.catalog_lookup import lookup_by_isbn, lookup_by_search

    book = lookup_by_isbn("9780141439518")
    matches, has_more = lookup_by_search(title="The Hobbit", offset=0)
"""

from lending_library import google_books, openlibrary
from lending_library.isbn import normalize_isbn
from lending_library.models import BookRecord


PAGE_SIZE = 5
MAX_FETCH = 40


def lookup_by_isbn(raw_isbn: str) -> BookRecord | None:
    """Resolve an ISBN through Google Books, then Open Library.

    Parameters:
        raw_isbn: ISBN-10, ISBN-13, or hyphenated barcode text.

    Returns:
        BookRecord from the first successful source, or None.
    """
    isbn = normalize_isbn(raw_isbn)
    if isbn is None:
        return None
    record = google_books.lookup_isbn(isbn)
    if record is not None:
        if record["isbn"] is None:
            record["isbn"] = isbn
        return record
    record = openlibrary.lookup_isbn(isbn)
    if record is not None:
        if record["isbn"] is None:
            record["isbn"] = isbn
        return record
    return None


def lookup_by_search(
    query: str = "",
    title: str = "",
    author: str = "",
    limit: int = PAGE_SIZE,
    offset: int = 0,
) -> tuple[list[BookRecord], bool]:
    """Search Open Library and Google Books, then return one result page.

    Both catalogs are queried and merged. Duplicate editions are skipped.
    Results are sliced with offset so the client can load additional pages.

    Parameters:
        query: Free-text query used for manual search.
        title: Title words when known.
        author: Author words when known.
        limit: Maximum number of records to return for this page.
        offset: Number of merged records to skip from the start of the list.

    Returns:
        A tuple of (deduplicated BookRecord page, has_more).
    """
    start = max(offset, 0)
    page_limit = max(1, limit)
    fetch_limit = min(MAX_FETCH, start + page_limit + 1)
    primary = openlibrary.search_books(
        query=query, title=title, author=author, limit=fetch_limit, offset=0
    )
    fallback = google_books.search_books(
        query=query, title=title, author=author, limit=fetch_limit, offset=0
    )
    seen: set[str] = set()
    merged: list[BookRecord] = []
    for record in primary + fallback:
        key = _record_key(record)
        if key in seen:
            continue
        seen.add(key)
        merged.append(record)
    page = merged[start : start + page_limit]
    has_more = len(merged) > start + page_limit
    return page, has_more


def _record_key(record: BookRecord) -> str:
    """Build a dedupe key for a lookup result.

    Parameters:
        record: Normalized book record.

    Returns:
        ISBN when present, otherwise title plus first author.
    """
    if record["isbn"]:
        return record["isbn"]
    author = ""
    if record["authors"]:
        author = record["authors"][0].casefold()
    return record["title"].casefold() + "|" + author
