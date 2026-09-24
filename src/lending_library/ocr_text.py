"""Turn noisy cover-OCR text into a title/author search query.

Usage:
    from lending_library.ocr_text import parse_ocr_text

    parsed = parse_ocr_text(raw_tesseract_output)
    title = parsed["title"]
"""

import re

from typing import TypedDict


NOISE_PHRASES = (
    "new york times",
    "bestseller",
    "best-selling",
    "a novel",
    "a memoir",
    "a mystery",
    "now a major",
    "motion picture",
    "national bestseller",
    "pulitzer",
    "from the author",
    "over million",
    "#1",
    "number one",
    "oprah",
    "book club",
    "price",
    "isbn",
)

AUTHOR_PREFIX = re.compile(r"^\s*(by|author)\s+(.+)$", re.IGNORECASE)
LETTER_RE = re.compile(r"[A-Za-z]")


class OcrParse(TypedDict):
    """Structured guess extracted from cover OCR."""

    title: str
    author: str
    query: str


def _is_noise_line(line: str) -> bool:
    """Return True if a line looks like cover marketing text rather than a title.

    Parameters:
        line: A single OCR line, already stripped.

    Returns:
        Whether the line should be discarded.
    """
    lowered = line.casefold()
    for phrase in NOISE_PHRASES:
        if phrase in lowered:
            return True
    letters = LETTER_RE.findall(line)
    if len(letters) < 3:
        return True
    if line.startswith("$") or line.endswith("$"):
        return True
    return False


def parse_ocr_text(raw_text: str) -> OcrParse:
    """Extract a title guess and optional author from Tesseract output.

    Parameters:
        raw_text: Full OCR dump from a front-cover photograph.

    Returns:
        OcrParse with title, author, and a combined query string. Empty
        strings mean OCR did not yield a usable line.
    """
    lines = []
    for raw_line in raw_text.splitlines():
        line = " ".join(raw_line.split()).strip(" .-")
        if not line:
            continue
        if _is_noise_line(line):
            continue
        lines.append(line)
    title = ""
    author = ""
    remaining: list[str] = []
    for line in lines:
        match = AUTHOR_PREFIX.match(line)
        if match and not author:
            author = match.group(2).strip()
            continue
        remaining.append(line)
    if remaining:
        title = remaining[0]
    if not author and len(remaining) >= 2:
        second = remaining[1]
        if len(second.split()) <= 5 and len(second) <= 40:
            author = second
    query_parts = [part for part in (title, author) if part]
    return OcrParse(
        title=title,
        author=author,
        query=" ".join(query_parts),
    )
