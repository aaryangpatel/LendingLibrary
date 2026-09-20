"""ISBN normalization helpers used by intake and catalog lookup.

Usage:
    from lending_library.isbn import normalize_isbn, is_isbn13

    isbn = normalize_isbn("978-0-14-143951-8")
"""

import re


ISBN_NOISE = re.compile(r"[^0-9Xx]")


def strip_isbn_characters(raw: str) -> str:
    """Remove hyphens, spaces, and other separators from an ISBN string.

    Parameters:
        raw: User or barcode input that may contain hyphens or spaces.

    Returns:
        The compact ISBN string containing only digits and X.
    """
    return ISBN_NOISE.sub("", raw.strip())


def isbn10_check_digit(body9: str) -> str:
    """Compute the ISBN-10 check digit for a 9-digit body.

    Parameters:
        body9: First nine digits of an ISBN-10.

    Returns:
        Check digit as a string, using X for 10.
    """
    total = 0
    weight = 10
    for character in body9:
        total += int(character) * weight
        weight -= 1
    remainder = total % 11
    check = (11 - remainder) % 11
    if check == 10:
        return "X"
    return str(check)


def isbn13_check_digit(body12: str) -> str:
    """Compute the ISBN-13 check digit for a 12-digit body.

    Parameters:
        body12: First twelve digits of an ISBN-13.

    Returns:
        Check digit as a single-character string.
    """
    total = 0
    for index, character in enumerate(body12):
        digit = int(character)
        if index % 2 == 0:
            total += digit
        else:
            total += digit * 3
    check = (10 - (total % 10)) % 10
    return str(check)


def isbn10_to_isbn13(isbn10: str) -> str:
    """Convert a validated ISBN-10 string to ISBN-13.

    Parameters:
        isbn10: Ten-character ISBN-10, with X allowed as the check digit.

    Returns:
        Thirteen-digit ISBN-13 string.
    """
    body12 = "978" + isbn10[:9]
    return body12 + isbn13_check_digit(body12)


def is_isbn13(value: str) -> bool:
    """Return True if value is a 13-digit ISBN with a valid check digit.

    Parameters:
        value: Compact ISBN string with no separators.

    Returns:
        Whether the string is a well-formed ISBN-13.
    """
    if len(value) != 13 or not value.isdigit():
        return False
    if value[:3] not in {"978", "979"}:
        return False
    return isbn13_check_digit(value[:12]) == value[12]


def is_isbn10(value: str) -> bool:
    """Return True if value is a 10-character ISBN with a valid check digit.

    Parameters:
        value: Compact ISBN string with no separators.

    Returns:
        Whether the string is a well-formed ISBN-10.
    """
    if len(value) != 10:
        return False
    body = value[:9]
    if not body.isdigit():
        return False
    check = value[9].upper()
    return isbn10_check_digit(body) == check


def normalize_isbn(raw: str) -> str | None:
    """Normalize barcode or typed input into an ISBN-13 when possible.

    Parameters:
        raw: ISBN, EAN-13, or ISBN-10 as typed or decoded from a barcode.

    Returns:
        ISBN-13 string, or None if the input is not a usable ISBN.
    """
    compact = strip_isbn_characters(raw).upper()
    if is_isbn13(compact):
        return compact
    if is_isbn10(compact):
        return isbn10_to_isbn13(compact)
    return None


def pick_preferred_isbn(candidates: list[str]) -> str | None:
    """Choose the best ISBN-13 from a list of identifiers.

    Parameters:
        candidates: ISBN-10 and ISBN-13 values from a catalog API.

    Returns:
        A normalized ISBN-13, preferring 978/979 codes, or None.
    """
    for candidate in candidates:
        normalized = normalize_isbn(str(candidate))
        if normalized is not None:
            return normalized
    return None
