"""Normalized bibliographic record shared across lookup APIs and Firestore.

Usage:
    from lending_library.models import BookRecord, authors_display
"""

from typing import Any, TypedDict


class BookRecord(TypedDict):
    """Canonical book metadata stored on a Firestore `books` document."""

    isbn: str | None
    title: str
    authors: list[str]
    cover_url: str | None
    openlibrary_id: str | None
    subjects: list[str]
    publish_year: int | None
    source: str


class CatalogBook(TypedDict):
    """Book record joined with copy counts for catalog templates."""

    id: str
    isbn: str | None
    title: str
    authors: list[str]
    cover_url: str | None
    openlibrary_id: str | None
    subjects: list[str]
    publish_year: int | None
    source: str
    available_count: int
    taken_count: int
    total_count: int
    hidden: bool


NOISE_SUBJECTS = (
    "reading level",
    "accessible book",
    "protected daisy",
    "in library",
    "overdrive",
    "open library staff",
    "nyt:",
    "large type books",
)


def clean_subjects(subjects: list[Any]) -> list[str]:
    """Keep short, useful subject labels and drop catalog-noise tags.

    Parameters:
        subjects: Raw subject strings from Open Library, Google Books, or Firestore.

    Returns:
        Up to eight cleaned subject labels.
    """
    cleaned: list[str] = []
    for item in subjects:
        label = str(item).strip()
        if not label:
            continue
        lowered = label.casefold()
        noisy = False
        for phrase in NOISE_SUBJECTS:
            if phrase in lowered:
                noisy = True
                break
        if noisy:
            continue
        if label not in cleaned:
            cleaned.append(label)
        if len(cleaned) >= 8:
            break
    return cleaned


def authors_display(authors: list[str]) -> str:
    """Format an author list for templates.

    Parameters:
        authors: Author names in catalog order.

    Returns:
        Comma-separated author string, or 'Unknown author' when the list is empty.
    """
    if not authors:
        return "Unknown author"
    return ", ".join(authors)


def record_from_mapping(data: dict[str, Any]) -> BookRecord:
    """Build a BookRecord from a Firestore document or JSON body.

    Parameters:
        data: Mapping that may contain a subset of BookRecord keys.

    Returns:
        A BookRecord with missing fields filled in.
    """
    isbn = data.get("isbn")
    title = data.get("title") or ""
    authors = data.get("authors") or []
    cover_url = data.get("cover_url")
    openlibrary_id = data.get("openlibrary_id")
    subjects = data.get("subjects") or []
    publish_year = data.get("publish_year")
    source = data.get("source") or ""
    return BookRecord(
        isbn=isbn if isbn else None,
        title=str(title).strip(),
        authors=[str(name).strip() for name in authors if str(name).strip()],
        cover_url=cover_url if cover_url else None,
        openlibrary_id=openlibrary_id if openlibrary_id else None,
        subjects=clean_subjects(subjects),
        publish_year=int(publish_year) if publish_year else None,
        source=str(source),
    )
