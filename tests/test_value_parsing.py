import pytest

from src.value_parsing import (
    parse_bool_value,
    parse_float_value,
    parse_int_value,
    parse_json_value,
    parse_optional_bool_value,
    parse_optional_float_value,
    parse_optional_int_value,
)


def test_parse_bool_value_supports_explicit_aliases():
    assert parse_bool_value("yes") is True
    assert parse_bool_value("off") is False
    assert parse_bool_value("maybe", default=True) is True


def test_parse_int_value_clamps_bounds():
    assert parse_int_value("5.2", default=0, minimum=1, maximum=4) == 4
    assert parse_int_value("0", default=3, minimum=1) == 1
    assert parse_int_value("bad", default=7) == 7


def test_parse_float_value_uses_default_on_invalid_input():
    assert parse_float_value("1.5", default=0.0) == 1.5
    assert parse_float_value("bad", default=2.5) == 2.5


def test_parse_json_value_returns_raw_objects_or_fallback():
    payload = {"a": [1]}
    assert parse_json_value(payload, {}) is payload
    assert parse_json_value("[1, 2]", []) == [1, 2]
    assert parse_json_value("", {"x": 1}) == {"x": 1}


def test_parse_optional_bool_value_rejects_unknown_text():
    assert parse_optional_bool_value("enabled", "enable") is True
    assert parse_optional_bool_value("enabled", "disabled") is False
    assert parse_optional_bool_value("enabled", "") is None
    with pytest.raises(ValueError, match="enabled must be a boolean value"):
        parse_optional_bool_value("enabled", "maybe")


def test_parse_optional_int_value_supports_allowed_value_before_bounds():
    assert parse_optional_int_value("seed", "-1", allowed_values=(-1,), minimum=0) == -1
    assert parse_optional_int_value("seed", "42", allowed_values=(-1,), minimum=0, maximum=100) == 42
    with pytest.raises(ValueError, match="seed must be an integer"):
        parse_optional_int_value("seed", True)
    with pytest.raises(ValueError, match="seed must be >= 0"):
        parse_optional_int_value("seed", "-2", allowed_values=(-1,), minimum=0)
    with pytest.raises(ValueError, match="seed must be <= 100"):
        parse_optional_int_value("seed", "101", maximum=100)


def test_parse_optional_float_value_enforces_exclusive_minimum():
    assert parse_optional_float_value("poll", "0.5", minimum_exclusive=0) == 0.5
    assert parse_optional_float_value("poll", "") is None
    with pytest.raises(ValueError, match="poll must be a number"):
        parse_optional_float_value("poll", False)
    with pytest.raises(ValueError, match="poll must be greater than 0"):
        parse_optional_float_value("poll", 0, minimum_exclusive=0)
