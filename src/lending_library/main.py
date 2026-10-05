"""FastAPI application for the Exeter lending library catalog.

Usage:
    source .venv/bin/activate
    export PYTHONPATH=src
    uvicorn lending_library.main:app --reload --host 127.0.0.1 --port 8000

Pages:
    GET  /              catalog
    GET  /pickup        available titles
    GET  /drop-off      barcode, OCR, and manual intake
    GET  /book/{id}     detail, pickup, staff hide

JSON API:
    GET  /api/lookup/isbn/{isbn}
    GET  /api/lookup/search
    POST /api/lookup/ocr
    POST /api/drop-off
    POST /api/books/{id}/pickup
    POST /api/books/{id}/hide
"""

import hashlib
import hmac

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from lending_library import firebase_db
from lending_library.catalog_lookup import lookup_by_isbn, lookup_by_search, lookup_from_ocr
from lending_library.config import PACKAGE_DIR, settings
from lending_library.models import authors_display, record_from_mapping
from lending_library.ocr_text import parse_ocr_text


app = FastAPI(title="Exeter Lending Library", version="0.1.0")
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
templates.env.globals["authors_display"] = authors_display
app.mount(
    "/static",
    StaticFiles(directory=str(PACKAGE_DIR / "static")),
    name="static",
)


class OcrLookupBody(BaseModel):
    """JSON body for cover-OCR lookup.

    Parameters:
        text: Raw Tesseract output from a front-cover photograph.
    """

    text: str = Field(min_length=1, max_length=8000)


class DropOffBody(BaseModel):
    """JSON body for a confirmed drop-off.

    Parameters:
        isbn: Optional ISBN-13.
        title: Confirmed title. Required.
        authors: Confirmed author names.
        cover_url: Optional cover image URL.
        openlibrary_id: Optional Open Library work or edition key.
        subjects: Optional subject list.
        publish_year: Optional four-digit year.
        source: openlibrary or google_books.
    """

    isbn: str | None = None
    title: str = Field(min_length=1, max_length=400)
    authors: list[str] = Field(default_factory=list)
    cover_url: str | None = None
    openlibrary_id: str | None = None
    subjects: list[str] = Field(default_factory=list)
    publish_year: int | None = None
    source: str = "openlibrary"


class StaffHideBody(BaseModel):
    """JSON body for hiding a bad catalog entry.

    Parameters:
        password: Shared staff password from STAFF_PASSWORD.
    """

    password: str = Field(min_length=1, max_length=200)


def staff_password_matches(given: str) -> bool:
    """Compare a submitted staff password to STAFF_PASSWORD.

    Parameters:
        given: Password from the hide form or JSON body.

    Returns:
        True when the password matches the configured staff password.
    """
    if not settings.staff_password:
        return False
    given_digest = hashlib.sha256(given.encode("utf-8")).digest()
    expected_digest = hashlib.sha256(settings.staff_password.encode("utf-8")).digest()
    return hmac.compare_digest(given_digest, expected_digest)


def _page_context(
    request: Request,
    extra: dict | None = None,
) -> dict:
    """Build the base template context shared by HTML pages.

    Parameters:
        request: Incoming FastAPI request.
        extra: Page-specific keys to merge in.

    Returns:
        Jinja context dictionary.
    """
    context = {
        "request": request,
        "staff_enabled": bool(settings.staff_password),
    }
    if extra:
        context.update(extra)
    return context


@app.on_event("startup")
def on_startup() -> None:
    """Initialize the Firestore client when the API process starts."""
    firebase_db.init_client()


@app.get("/api/health")
def api_health() -> JSONResponse:
    """Report which Firestore backend the process is using.

    Returns:
        JSON `{ok, firestore: {mode, project_id}}`. `mode` is `cloud`,
        `emulator`, or `adc`.
    """
    return JSONResponse({"ok": True, "firestore": firebase_db.connection_info()})


@app.get("/", response_class=HTMLResponse)
def catalog_page(
    request: Request,
    q: str = "",
    available: str = "",
) -> HTMLResponse:
    """Render the catalog, or a results fragment for HTMX search.

    Parameters:
        request: Incoming request. HTMX requests receive a partial template.
        q: Search string for title, author, ISBN, or subject.
        available: When "1" or "on", only titles with a copy on the shelf.

    Returns:
        Catalog HTML page or book-grid partial.
    """
    available_only = available in {"1", "on", "true", "yes"}
    books = firebase_db.list_catalog(query=q, available_only=available_only)
    context = _page_context(
        request,
        {
            "books": books,
            "q": q,
            "available_only": available_only,
            "active": "catalog",
        },
    )
    template_name = "catalog.html"
    if request.headers.get("HX-Request") == "true":
        template_name = "partials/book_grid.html"
    return templates.TemplateResponse(request, template_name, context)


@app.get("/pickup", response_class=HTMLResponse)
def pickup_page(request: Request, q: str = "") -> HTMLResponse:
    """Render titles that currently have at least one copy on the shelf.

    Parameters:
        request: Incoming request.
        q: Optional search filter.

    Returns:
        Pickup HTML page.
    """
    books = firebase_db.list_catalog(query=q, available_only=True)
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(
            request,
            "partials/book_grid.html",
            _page_context(
                request,
                {
                    "books": books,
                    "q": q,
                    "available_only": True,
                    "pickup_mode": True,
                },
            ),
        )
    return templates.TemplateResponse(
        request,
        "pickup.html",
        _page_context(
            request,
            {
                "books": books,
                "q": q,
                "available_only": True,
                "pickup_mode": True,
                "active": "pickup",
            },
        ),
    )


@app.get("/drop-off", response_class=HTMLResponse)
def drop_off_page(request: Request) -> HTMLResponse:
    """Render the camera, OCR, and manual drop-off page.

    Parameters:
        request: Incoming request.

    Returns:
        Drop-off HTML page.
    """
    return templates.TemplateResponse(
        request,
        "drop_off.html",
        _page_context(request, {"active": "drop-off"}),
    )


@app.get("/book/{book_id}", response_class=HTMLResponse)
def book_detail_page(request: Request, book_id: str) -> HTMLResponse:
    """Render one title with copy counts, pickup, and staff hide.

    Parameters:
        request: Incoming request.
        book_id: Firestore books document id.

    Returns:
        Detail page, or a redirect to the catalog when the book is missing.
    """
    book = firebase_db.get_book(book_id)
    if book is None:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request,
        "book.html",
        _page_context(
            request,
            {"book": book, "active": "catalog"},
        ),
    )


@app.get("/api/lookup/isbn/{isbn}")
def api_lookup_isbn(isbn: str) -> JSONResponse:
    """Look up a single book by ISBN for the drop-off confirmation card.

    Parameters:
        isbn: ISBN-10, ISBN-13, or hyphenated barcode value.

    Returns:
        JSON `{ok, book}` where book is null when nothing matched.
    """
    record = lookup_by_isbn(isbn)
    return JSONResponse({"ok": record is not None, "book": record})


@app.get("/api/lookup/search")
def api_lookup_search(
    q: str = "",
    title: str = "",
    author: str = "",
) -> JSONResponse:
    """Search bibliographic APIs for drop-off candidate cards.

    Parameters:
        q: Free-text query.
        title: Title words.
        author: Author words.

    Returns:
        JSON `{ok, books}` with up to five BookRecord objects.
    """
    if not q.strip() and not title.strip():
        return JSONResponse({"ok": False, "books": [], "error": "Enter a title or ISBN."})
    records = lookup_by_search(query=q, title=title, author=author, limit=5)
    return JSONResponse({"ok": True, "books": records})


@app.post("/api/lookup/ocr")
def api_lookup_ocr(body: OcrLookupBody) -> JSONResponse:
    """Parse cover OCR text, then search bibliographic APIs.

    Parameters:
        body: Raw Tesseract text from the browser.

    Returns:
        JSON `{ok, parse, books}` with the guessed title/author and matches.
    """
    parsed = parse_ocr_text(body.text)
    if not parsed["query"] and not parsed["titles"]:
        return JSONResponse(
            {
                "ok": False,
                "parse": parsed,
                "books": [],
                "error": "The cover photo did not yield a readable title.",
            }
        )
    records = lookup_from_ocr(parsed, raw_text=body.text, limit=8)
    return JSONResponse({"ok": bool(records), "parse": parsed, "books": records})


@app.post("/api/drop-off")
def api_drop_off(body: DropOffBody) -> JSONResponse:
    """Save a confirmed book as one available copy in Firestore.

    Parameters:
        body: Bibliographic fields from the confirmation UI.

    Returns:
        JSON `{ok, book_id, copy_id}`.
    """
    record = record_from_mapping(body.model_dump())
    if not record["title"]:
        return JSONResponse(
            {"ok": False, "error": "A title is required."},
            status_code=400,
        )
    created = firebase_db.add_drop_off(record)
    return JSONResponse({"ok": True, **created})


@app.post("/api/books/{book_id}/pickup")
def api_pickup(book_id: str) -> JSONResponse:
    """Mark one available copy as taken.

    Parameters:
        book_id: Firestore books document id.

    Returns:
        JSON `{ok, copy_id}` or 409 when no copy remains.
    """
    copy_id = firebase_db.take_available_copy(book_id)
    if copy_id is None:
        return JSONResponse(
            {"ok": False, "error": "No copies are on the shelf."},
            status_code=409,
        )
    return JSONResponse({"ok": True, "copy_id": copy_id})


@app.post("/api/books/{book_id}/hide")
def api_hide(book_id: str, body: StaffHideBody) -> JSONResponse:
    """Hide a title from the catalog after checking the staff password.

    Parameters:
        book_id: Firestore books document id.
        body: Shared staff password.

    Returns:
        JSON `{ok}` or 403 when the password does not match.
    """
    if not settings.staff_password:
        return JSONResponse(
            {"ok": False, "error": "Staff tools are not configured."},
            status_code=403,
        )
    if not staff_password_matches(body.password):
        return JSONResponse(
            {"ok": False, "error": "Incorrect staff password."},
            status_code=403,
        )
    hidden = firebase_db.hide_book(book_id)
    if not hidden:
        return JSONResponse(
            {"ok": False, "error": "Book not found."},
            status_code=404,
        )
    return JSONResponse({"ok": True})


@app.post("/book/{book_id}/pickup")
def form_pickup(book_id: str) -> RedirectResponse:
    """Handle the HTML pickup form and return to the book page.

    Parameters:
        book_id: Firestore books document id.

    Returns:
        Redirect to the book page.
    """
    firebase_db.take_available_copy(book_id)
    return RedirectResponse(url=f"/book/{book_id}", status_code=303)


@app.post("/book/{book_id}/hide")
def form_hide(
    book_id: str,
    password: str = Form(...),
) -> RedirectResponse:
    """Handle the HTML staff-hide form.

    Parameters:
        book_id: Firestore books document id.
        password: Shared staff password from the form.

    Returns:
        Redirect to the catalog after a successful hide, otherwise the book page.
    """
    if not settings.staff_password:
        return RedirectResponse(url=f"/book/{book_id}", status_code=303)
    if not staff_password_matches(password):
        return RedirectResponse(url=f"/book/{book_id}?staff=1", status_code=303)
    firebase_db.hide_book(book_id)
    return RedirectResponse(url="/", status_code=303)
