"""Утиліти для роботи з геолокацією та Google Maps посиланнями."""

MAPS_BASE_URL = "https://maps.google.com/maps?q={lat},{lon}"


def make_maps_link(lat: float, lon: float) -> str:
    """Генерує Google Maps посилання за координатами."""
    return MAPS_BASE_URL.format(lat=lat, lon=lon)


def format_location(
    lat: float | None,
    lon: float | None,
    address_text: str | None = None,
) -> str:
    """Форматує рядок локації для відображення у повідомленні.

    - Якщо є координати — повертає Maps-посилання (і адресу, якщо є).
    - Якщо є лише текстова адреса — повертає її.
    - Якщо нічого немає — повертає 'Не вказано'.
    """
    if lat is not None and lon is not None:
        link = make_maps_link(lat, lon)
        if address_text:
            return f"{link}\n{address_text}"
        return link

    if address_text:
        return address_text

    return "Не вказано"
