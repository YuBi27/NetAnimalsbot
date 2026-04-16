"""Validators for FSM input data."""


def validate_description(text: str | None) -> bool:
    """Return True if text has at least 10 non-whitespace characters."""
    if not text:
        return False
    return len(text.strip()) >= 10


def validate_media_count(count: int) -> bool:
    """Return True if count does not exceed the 5-file limit."""
    return count <= 5
