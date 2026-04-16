"""Unit-тести для bot/utils/maps.py."""

import pytest
from bot.utils.maps import make_maps_link, format_location


class TestMakeMapsLink:
    def test_basic(self):
        assert make_maps_link(50.45, 30.52) == "https://maps.google.com/maps?q=50.45,30.52"

    def test_negative_coordinates(self):
        assert make_maps_link(-33.87, 151.21) == "https://maps.google.com/maps?q=-33.87,151.21"

    def test_zero_coordinates(self):
        assert make_maps_link(0.0, 0.0) == "https://maps.google.com/maps?q=0.0,0.0"

    def test_contains_lat_lon(self):
        lat, lon = 48.3794, 31.1656
        link = make_maps_link(lat, lon)
        assert str(lat) in link
        assert str(lon) in link

    def test_starts_with_maps_url(self):
        link = make_maps_link(1.0, 2.0)
        assert link.startswith("https://maps.google.com/maps?q=")


class TestFormatLocation:
    def test_coords_only(self):
        result = format_location(50.45, 30.52)
        assert result == "https://maps.google.com/maps?q=50.45,30.52"

    def test_coords_with_address(self):
        result = format_location(50.45, 30.52, "вул. Хрещатик, 1")
        assert "https://maps.google.com/maps?q=50.45,30.52" in result
        assert "вул. Хрещатик, 1" in result

    def test_address_only(self):
        result = format_location(None, None, "вул. Хрещатик, 1")
        assert result == "вул. Хрещатик, 1"

    def test_nothing_provided(self):
        result = format_location(None, None)
        assert result == "Не вказано"

    def test_nothing_provided_explicit_none_address(self):
        result = format_location(None, None, None)
        assert result == "Не вказано"

    def test_coords_with_empty_address(self):
        # Порожній рядок адреси — повертаємо лише посилання
        result = format_location(50.45, 30.52, "")
        assert result == "https://maps.google.com/maps?q=50.45,30.52"

    def test_lat_none_lon_provided_address_fallback(self):
        # Якщо лише одна координата None — адреса як fallback
        result = format_location(None, 30.52, "Київ")
        assert result == "Київ"
