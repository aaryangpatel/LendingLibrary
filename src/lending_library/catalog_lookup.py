"""Combine Open Library and Google Books into a single lookup pipeline.

Usage:
    from lending_library.catalog_lookup import lookup_by_isbn, lookup_by_search

    book = lookup_by_isbn("9780141439518")
    matches = lookup_by_search(title="The Hobbit")
"""

from lending_library import google_books, openlibrary
from lending_library.isbn import normalize_isbn
from lending_library.models import BookRecord


def lookup_by_isbn(raw_isbn: str) -> BookRecord | None:
    """Resolve an ISBN through Open Library, then Google Books.

    Parameters:
        raw_isbn: ISBN-10, ISBN-13, or hyphenated barcode text.

    Returns:
        BookRecord from the first successful source, or None.
    """
    isbn = normalize_isbn(raw_isbn)
    if isbn is None:
        return None
    record = openlibrary.lookup_isbn(isbn)
    if record is not None:
        if record["isbn"] is None:
            record["isbn"] = isbn
        return record
    return google_books.lookup_isbn(isbn)


def lookup_by_search(
    query: str = "",
    title: str = "",
    author: str = "",
    limit: int = 5,
) -> list[BookRecord]:
    """Search Open Library, then fill remaining slots from Google Books.

    Parameters:
        query: Free-text query, used for OCR output and manual search.
        title: Title words when known.
        author: Author words when known.
        limit: Maximum number of records to return.

    Returns:
        Deduplicated BookRecord list, possibly empty.
    """
    primary = openlibrary.search_books(
        query=query, title=title, author=author, limit=limit
    )
    if len(primary) >= limit:
        return primary
    seen: set[str] = set()
    merged: list[BookRecord] = []
    for record in primary:
        key = record["isbn"] or record["title"].casefold()
        seen.add(key)
        merged.append(record)
    remaining = limit - len(merged)
    if remaining <= 0:
        return merged
    fallback = google_books.search_books(
        query=query, title=title, author=author, limit=remaining + 2
    )
    for record in fallback:
        key = record["isbn"] or record["title"].casefold()
        if key in seen:
            continue
        seen.add(key)
        merged.append(record)
        if len(merged) >= limit:
            break
    return merged
