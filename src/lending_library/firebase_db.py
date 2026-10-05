"""Firestore access for books, copies, and intake events.

Usage:
    from lending_library import firebase_db

    firebase_db.init_client()
    catalog = firebase_db.list_catalog(query="hobbit", available_only=True)
    book = firebase_db.get_book(book_id)

The FastAPI process is the only Firestore client. It authenticates with
FIREBASE_SERVICE_ACCOUNT (file path) or FIREBASE_SERVICE_ACCOUNT_JSON.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from google.oauth2 import service_account

from lending_library.config import PROJECT_ROOT, settings
from lending_library.models import BookRecord, CatalogBook, record_from_mapping


COLLECTION_BOOKS = "books"
COLLECTION_COPIES = "copies"
COLLECTION_EVENTS = "events"

STATUS_AVAILABLE = "available"
STATUS_TAKEN = "taken"
STATUS_REMOVED = "removed"

_client: firestore.Client | None = None
_connection: dict[str, str] = {
    "mode": "uninitialized",
    "project_id": settings.firebase_project_id,
}


def _service_account_path() -> Path:
    """Resolve FIREBASE_SERVICE_ACCOUNT to an absolute path.

    Returns:
        Path to the service-account JSON file.
    """
    raw = settings.firebase_service_account.strip().strip('"').strip("'")
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def connection_info() -> dict[str, str]:
    """Return the active Firestore backend for health checks.

    Returns:
        Dict with `mode` and `project_id`.
    """
    return dict(_connection)


def _service_account_info() -> dict:
    """Load the Firebase service-account dict from env JSON or a key file.

    Returns:
        Parsed service-account object, including project_id.
    """
    inline = settings.firebase_service_account_json.strip()
    if inline:
        return json.loads(inline)
    return json.loads(_service_account_path().read_text())


def init_client() -> firestore.Client:
    """Create the process-wide Firestore client from the service account.

    Prefers FIREBASE_SERVICE_ACCOUNT_JSON (for hosts such as Cloud Run),
    then FIREBASE_SERVICE_ACCOUNT as a local file path.

    Returns:
        Authenticated Firestore client for the Firebase project.
    """
    global _client
    if _client is not None:
        return _client
    info = _service_account_info()
    credentials = service_account.Credentials.from_service_account_info(info)
    project_id = str(info.get("project_id") or settings.firebase_project_id)
    _client = firestore.Client(project=project_id, credentials=credentials)
    _connection["mode"] = "cloud"
    _connection["project_id"] = project_id
    print(f"Firestore connected: cloud project {project_id}")
    return _client


def get_client() -> firestore.Client:
    """Return the initialized Firestore client, creating it if needed.

    Returns:
        Process-wide Firestore client.
    """
    if _client is None:
        return init_client()
    return _client


def _now() -> datetime:
    """Return a timezone-aware UTC timestamp for document fields.

    Returns:
        Current UTC datetime.
    """
    return datetime.now(timezone.utc)


def _book_from_snapshot(snapshot: firestore.DocumentSnapshot) -> CatalogBook:
    """Convert a books document snapshot into a CatalogBook with zeroed counts.

    Parameters:
        snapshot: Firestore document from the books collection.

    Returns:
        CatalogBook whose copy counts are filled later by list_catalog.
    """
    data = snapshot.to_dict() or {}
    record = record_from_mapping(data)
    return CatalogBook(
        id=snapshot.id,
        isbn=record["isbn"],
        title=record["title"],
        authors=record["authors"],
        cover_url=record["cover_url"],
        openlibrary_id=record["openlibrary_id"],
        subjects=record["subjects"],
        publish_year=record["publish_year"],
        source=record["source"],
        available_count=0,
        taken_count=0,
        total_count=0,
        hidden=bool(data.get("hidden", False)),
    )


def _matches_query(book: CatalogBook, query: str) -> bool:
    """Return True if the catalog search string appears in title, author, or ISBN.

    Parameters:
        book: Catalog row.
        query: Case-insensitive search text. Empty query matches everything.

    Returns:
        Whether the book should appear in filtered results.
    """
    needle = query.strip().casefold()
    if not needle:
        return True
    haystack_parts = [book["title"], book["isbn"] or ""]
    haystack_parts.extend(book["authors"])
    haystack_parts.extend(book["subjects"])
    haystack = " ".join(haystack_parts).casefold()
    return needle in haystack


def list_catalog(query: str = "", available_only: bool = False) -> list[CatalogBook]:
    """Load books and copies, then join copy counts in process.

    Parameters:
        query: Optional case-insensitive filter on title, author, ISBN, subject.
        available_only: When True, omit titles with zero available copies.

    Returns:
        Catalog rows with hidden books removed, sorted by title.
    """
    client = get_client()
    book_rows = [
        _book_from_snapshot(snapshot)
        for snapshot in client.collection(COLLECTION_BOOKS).stream()
    ]
    copies = [
        snapshot.to_dict() or {}
        for snapshot in client.collection(COLLECTION_COPIES).stream()
    ]
    counts: dict[str, dict[str, int]] = {}
    for copy in copies:
        book_id = str(copy.get("book_id") or "")
        status = str(copy.get("status") or "")
        if book_id not in counts:
            counts[book_id] = {"available": 0, "taken": 0, "total": 0}
        if status == STATUS_REMOVED:
            continue
        counts[book_id]["total"] += 1
        if status == STATUS_AVAILABLE:
            counts[book_id]["available"] += 1
        elif status == STATUS_TAKEN:
            counts[book_id]["taken"] += 1
    catalog: list[CatalogBook] = []
    for book in book_rows:
        if book["hidden"]:
            continue
        tally = counts.get(book["id"], {"available": 0, "taken": 0, "total": 0})
        book["available_count"] = tally["available"]
        book["taken_count"] = tally["taken"]
        book["total_count"] = tally["total"]
        if available_only and book["available_count"] < 1:
            continue
        if not _matches_query(book, query):
            continue
        catalog.append(book)
    catalog.sort(key=lambda row: (row["available_count"] == 0, row["title"].casefold()))
    return catalog


def get_book(book_id: str) -> CatalogBook | None:
    """Load one book and its copy counts.

    Parameters:
        book_id: Firestore books document id.

    Returns:
        CatalogBook, or None if the document does not exist or is hidden.
    """
    client = get_client()
    snapshot = client.collection(COLLECTION_BOOKS).document(book_id).get()
    if not snapshot.exists:
        return None
    book = _book_from_snapshot(snapshot)
    if book["hidden"]:
        return None
    copies = client.collection(COLLECTION_COPIES).where(
        filter=FieldFilter("book_id", "==", book_id)
    ).stream()
    available = 0
    taken = 0
    total = 0
    for copy_snapshot in copies:
        data = copy_snapshot.to_dict() or {}
        status = str(data.get("status") or "")
        if status == STATUS_REMOVED:
            continue
        total += 1
        if status == STATUS_AVAILABLE:
            available += 1
        elif status == STATUS_TAKEN:
            taken += 1
    book["available_count"] = available
    book["taken_count"] = taken
    book["total_count"] = total
    return book


def find_book_by_isbn(isbn: str) -> str | None:
    """Return the Firestore id of a non-hidden book with this ISBN.

    Parameters:
        isbn: Normalized ISBN-13.

    Returns:
        Document id, or None if no matching book exists.
    """
    client = get_client()
    query = (
        client.collection(COLLECTION_BOOKS)
        .where(filter=FieldFilter("isbn", "==", isbn))
        .limit(5)
        .stream()
    )
    for snapshot in query:
        data = snapshot.to_dict() or {}
        if not data.get("hidden"):
            return snapshot.id
    return None


def find_book_by_title_author(title: str, authors: list[str]) -> str | None:
    """Return an existing book id that matches title and first author.

    Parameters:
        title: Book title from the confirmed lookup.
        authors: Author list from the confirmed lookup.

    Returns:
        Document id, or None.
    """
    title_key = title.strip().casefold()
    author_key = authors[0].strip().casefold() if authors else ""
    client = get_client()
    for snapshot in client.collection(COLLECTION_BOOKS).stream():
        data = snapshot.to_dict() or {}
        if data.get("hidden"):
            continue
        stored_title = str(data.get("title") or "").strip().casefold()
        stored_authors = data.get("authors") or []
        stored_author = ""
        if stored_authors:
            stored_author = str(stored_authors[0]).strip().casefold()
        if stored_title == title_key and stored_author == author_key:
            return snapshot.id
    return None


def add_drop_off(record: BookRecord) -> dict[str, str]:
    """Create or reuse a book document and add one available copy.

    Parameters:
        record: Confirmed bibliographic metadata from a lookup.

    Returns:
        Dict with book_id and copy_id of the new drop-off.
    """
    client = get_client()
    book_id = None
    if record["isbn"]:
        book_id = find_book_by_isbn(record["isbn"])
    if book_id is None:
        book_id = find_book_by_title_author(record["title"], record["authors"])
    if book_id is None:
        book_ref = client.collection(COLLECTION_BOOKS).document()
        book_ref.set(
            {
                "isbn": record["isbn"],
                "title": record["title"],
                "authors": record["authors"],
                "cover_url": record["cover_url"],
                "openlibrary_id": record["openlibrary_id"],
                "subjects": record["subjects"],
                "publish_year": record["publish_year"],
                "source": record["source"],
                "hidden": False,
                "created_at": _now(),
            }
        )
        book_id = book_ref.id
    copy_ref = client.collection(COLLECTION_COPIES).document()
    copy_ref.set(
        {
            "book_id": book_id,
            "status": STATUS_AVAILABLE,
            "dropped_off_at": _now(),
            "taken_at": None,
        }
    )
    client.collection(COLLECTION_EVENTS).document().set(
        {
            "type": "drop_off",
            "book_id": book_id,
            "copy_id": copy_ref.id,
            "created_at": _now(),
        }
    )
    return {"book_id": book_id, "copy_id": copy_ref.id}


def take_available_copy(book_id: str) -> str | None:
    """Mark one available copy of a book as taken.

    Parameters:
        book_id: Firestore books document id.

    Returns:
        The copy document id that was taken, or None if none are available.
    """
    client = get_client()
    copies = (
        client.collection(COLLECTION_COPIES)
        .where(filter=FieldFilter("book_id", "==", book_id))
        .where(filter=FieldFilter("status", "==", STATUS_AVAILABLE))
        .limit(1)
        .stream()
    )
    copy_snapshot = None
    for snapshot in copies:
        copy_snapshot = snapshot
        break
    if copy_snapshot is None:
        return None
    copy_snapshot.reference.update(
        {
            "status": STATUS_TAKEN,
            "taken_at": _now(),
        }
    )
    client.collection(COLLECTION_EVENTS).document().set(
        {
            "type": "pickup",
            "book_id": book_id,
            "copy_id": copy_snapshot.id,
            "created_at": _now(),
        }
    )
    return copy_snapshot.id


def hide_book(book_id: str) -> bool:
    """Hide a book from the catalog and mark remaining copies removed.

    Parameters:
        book_id: Firestore books document id.

    Returns:
        True if the book existed and was hidden.
    """
    client = get_client()
    book_ref = client.collection(COLLECTION_BOOKS).document(book_id)
    snapshot = book_ref.get()
    if not snapshot.exists:
        return False
    book_ref.update({"hidden": True})
    copies = client.collection(COLLECTION_COPIES).where(
        filter=FieldFilter("book_id", "==", book_id)
    ).stream()
    for copy_snapshot in copies:
        copy_snapshot.reference.update({"status": STATUS_REMOVED})
    client.collection(COLLECTION_EVENTS).document().set(
        {
            "type": "removed",
            "book_id": book_id,
            "copy_id": None,
            "created_at": _now(),
        }
    )
    return True
