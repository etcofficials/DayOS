from __future__ import annotations

from typing import Any

from src.database import Database
from src.services.dates import ValidationError


class Repository:
    def __init__(self, db: Database) -> None:
        self.db = db


def clean_text(value: Any, *, field: str, required: bool = False, max_len: int = 200) -> str:
    text = "" if value is None else str(value).strip()
    if required and not text:
        raise ValidationError(f"{field} cannot be empty.")
    if len(text) > max_len:
        raise ValidationError(f"{field} is too long (maximum {max_len} characters).")
    return text


def optional_id(value: Any) -> int | None:
    if value in (None, "", 0):
        return None
    return int(value)


def positive_int(value: Any, *, field: str) -> int | None:
    if value in (None, "", 0):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be a whole number.") from None
    if number <= 0:
        raise ValidationError(f"{field} must be greater than zero.")
    return number
