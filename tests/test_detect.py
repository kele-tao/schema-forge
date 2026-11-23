"""Unit tests for the pure value detectors."""

from __future__ import annotations

import pytest

from schema_forge import detect


@pytest.mark.parametrize(
    "value,expected",
    [
        ("42", True),
        ("-7", True),
        ("+0", True),
        ("3.5", False),
        ("1,234", False),
        ("", False),
        ("12a", False),
    ],
)
def test_is_int(value: str, expected: bool) -> None:
    assert detect.is_int(value) is expected


@pytest.mark.parametrize(
    "value,expected",
    [("3.5", True), ("0.0", True), ("1e10", True), (".5", True), ("3", False), ("3,5", False)],
)
def test_is_float(value: str, expected: bool) -> None:
    assert detect.is_float(value) is expected


@pytest.mark.parametrize(
    "value,expected",
    [("true", True), ("FALSE", True), ("yes", True), ("N", True), ("1", False), ("maybe", False)],
)
def test_is_bool(value: str, expected: bool) -> None:
    assert detect.is_bool(value) is expected


def test_parse_bool_maps_families() -> None:
    assert detect.parse_bool("Y") is True
    assert detect.parse_bool("no") is False
    assert detect.parse_bool("2") is None


def test_date_formats_are_all_reported() -> None:
    assert "%Y-%m-%d" in detect.date_formats_of("2026-06-04")
    assert len(detect.date_formats_of("04/06/2026")) >= 2
    assert detect.is_date("Jun 04, 2026")
    assert not detect.is_date("2026-13-01")


def test_datetime_requires_time_component() -> None:
    assert detect.is_datetime("2026-06-04T10:00:00Z")
    assert detect.is_datetime("2026-06-04 10:00:00")
    assert not detect.is_datetime("2026-06-04")


def test_pattern_types() -> None:
    assert detect.is_email("ada@example.com")
    assert not detect.is_email("ada at example")
    assert detect.is_url("https://shop.example.com/item/1")
    assert not detect.is_url("shop.example.com")
    assert detect.is_uuid("3f2504e0-4f89-11d3-9a0c-0305e82c3301")
    assert not detect.is_uuid("3f2504e0-4f89-11d3-9a0c")


@pytest.mark.parametrize(
    "value,expected",
    [("$1,299.00", True), ("42.50 EUR", True), ("USD 10", True), ("42.50", False), ("$", False)],
)
def test_is_currency(value: str, expected: bool) -> None:
    assert detect.is_currency(value) is expected


def test_parse_currency_handles_symbols_and_codes() -> None:
    assert detect.parse_currency("$1,299.00") == 1299.0
    assert detect.parse_currency("42.50 EUR") == 42.5
    assert detect.parse_currency("EUR 42.00") == 42.0
    assert detect.parse_currency("plain") is None


def test_luhn_card_detection() -> None:
    assert detect.is_card_number("4242 4242 4242 4242")
    assert not detect.is_card_number("4242 4242 4242 4241")
    assert not detect.is_card_number("1234")


def test_iban_mod97_checksum() -> None:
    assert detect.is_iban("GB82WEST12345698765432")
    assert not detect.is_iban("GB82WEST12345698765431")
    assert not detect.is_iban("NOTANIBAN")


def test_phone_rejects_dates_and_short_numbers() -> None:
    assert detect.is_phone("+1 415 555 0101")
    assert not detect.is_phone("2026-06-04")
    assert not detect.is_phone("12345")


def test_ssn_shape() -> None:
    assert detect.is_ssn("123-45-6789")
    assert not detect.is_ssn("000-00-0000")


def test_mask_value_keeps_last_four_digits() -> None:
    masked = detect.mask_value("card", "4242 4242 4242 4242")
    assert masked.endswith("4242")
    assert masked.count("*") > 8
    assert detect.mask_value("email", "ada@example.com") == "a***@example.com"
    assert detect.mask_value("iban", "GB82WEST12345698765432").startswith("GB")


def test_induce_pattern_matches_only_when_structure_is_shared() -> None:
    pattern = detect.induce_pattern(["SKU-AB-0001", "SKU-CD-9999", "SKU-EF-1234"])
    assert pattern == r"^[A-Z]{3}\-[A-Z]{2}\-\d{4}$"
    assert detect.pattern_is_valid(pattern, ["SKU-ZZ-0000"])
    assert detect.induce_pattern(["a@b.com", "no", "x y"]) is None


def test_induce_pattern_needs_variety() -> None:
    assert detect.induce_pattern(["same", "same", "same"]) is None
    assert detect.induce_pattern(["one", "three"]) is None


def test_structural_matches_reports_every_family() -> None:
    matches = detect.structural_matches("2026-06-04")
    assert "date" in matches
    assert "phone" not in matches


def test_structural_matches_orders_specific_types_first() -> None:
    assert detect.structural_matches("true") == ["bool"]
    assert detect.structural_matches("42") == ["int"]


def test_luhn_check_digit_completes_payload() -> None:
    payload = "424242424242424"
    assert detect.luhn_check_digit(payload) == "2"


def test_parse_number_handles_all_numeric_forms() -> None:
    assert detect.parse_number("12") == 12.0
    assert detect.parse_number("1.5") == 1.5
    assert detect.parse_number("$2.00") == 2.0
    assert detect.parse_number("nope") is None
