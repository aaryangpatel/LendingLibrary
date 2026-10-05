"""Combine Open Library and Google Books into a single lookup pipeline.

Usage:
    from lending_library.catalog_lookup import lookup_by_isbn, lookup_by_search

    book = lookup_by_isbn("9780141439518")
    matches = lookup_by_search(title="The Hobbit")
"""

from lending_library import google_books, openlibrary
from lending_library.isbn import find_isbn_in_text, normalize_isbn
from lending_library.models import BookRecord
from lending_library.ocr_text import OcrParse


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


def lookup_from_ocr(parsed: OcrParse, raw_text: str = "", limit: int = 8) -> list[BookRecord]:
    """Build a ranked list of likely titles from cover OCR.

    Tries ISBN text if present, then title plus author, then each extra
    OCR title line, then a free-text query. Duplicate editions are skipped.

    Parameters:
        parsed: Structured OCR guesses from parse_ocr_text.
        raw_text: Original Tesseract dump, used to hunt for a printed ISBN.
        limit: Maximum number of options to return.

    Returns:
        Deduplicated BookRecord list for the student to choose from.
    """
    merged: list[BookRecord] = []
    seen: set[str] = set()

    def add(records: list[BookRecord]) -> bool:
        """Append unseen records until the limit is reached.

        Parameters:
            records: Lookup hits to merge.

        Returns:
            True when merged is already at the limit.
        """
        for record in records:
            key = _record_key(record)
            if key in seen:
                continue
            seen.add(key)
            merged.append(record)
            if len(merged) >= limit:
                return True
        return False

    isbn = find_isbn_in_text(raw_text)
    if isbn is None:
        isbn = find_isbn_in_text(parsed["query"])
    if isbn is not None:
        exact = lookup_by_isbn(isbn)
        if exact is not None and add([exact]):
            return merged

    searches: list[dict[str, str]] = []
    if parsed["title"] and parsed["author"]:
        searches.append({"title": parsed["title"], "author": parsed["author"]})
    if parsed["title"]:
        searches.append({"title": parsed["title"]})
    for extra_title in parsed["titles"]:
        if extra_title and extra_title != parsed["title"]:
            searches.append({"title": extra_title})
    if parsed["query"]:
        searches.append({"query": parsed["query"]})

    for search in searches:
        hits = lookup_by_search(
            query=search.get("query", ""),
            title=search.get("title", ""),
            author=search.get("author", ""),
            limit=5,
        )
        if add(hits):
            return merged
    return merged
