from __future__ import annotations

from services.location_normalization import normalize_location_text


def test_normalize_province_only_location() -> None:
    location = normalize_location_text("福建")

    assert location.raw_value == "福建"
    assert location.normalized_country == "中国"
    assert location.normalized_province == "福建"
    assert location.normalized_city is None
    assert location.is_unknown is False


def test_normalize_province_and_city_location() -> None:
    location = normalize_location_text("福建 福州")

    assert location.normalized_province == "福建"
    assert location.normalized_city == "福州"


def test_normalize_municipality_location() -> None:
    location = normalize_location_text("上海")

    assert location.normalized_province == "上海"
    assert location.normalized_city == "上海"


def test_unknown_overseas_and_empty_locations_are_unknown() -> None:
    assert normalize_location_text("").is_unknown is True
    assert normalize_location_text("未知").is_unknown is True
    assert normalize_location_text("海外").is_unknown is True
