"""Unit tests for bot/utils/validators.py."""
import pytest
from bot.utils.validators import validate_description, validate_media_count


# --- validate_description ---

class TestValidateDescription:
    def test_valid_10_chars(self):
        assert validate_description("1234567890") is True

    def test_valid_more_than_10_chars(self):
        assert validate_description("This is a valid description") is True

    def test_exactly_10_chars_with_spaces(self):
        # 10 non-whitespace chars surrounded by spaces
        assert validate_description("  1234567890  ") is True

    def test_9_chars_after_strip(self):
        assert validate_description("123456789") is False

    def test_whitespace_only(self):
        assert validate_description("          ") is False

    def test_empty_string(self):
        assert validate_description("") is False

    def test_none(self):
        assert validate_description(None) is False

    def test_9_chars_with_surrounding_spaces(self):
        assert validate_description("  123456789  ") is False

    def test_unicode_chars(self):
        assert validate_description("Тварина поранена") is True


# --- validate_media_count ---

class TestValidateMediaCount:
    def test_zero(self):
        assert validate_media_count(0) is True

    def test_one(self):
        assert validate_media_count(1) is True

    def test_five(self):
        assert validate_media_count(5) is True

    def test_six(self):
        assert validate_media_count(6) is False

    def test_large_count(self):
        assert validate_media_count(100) is False
