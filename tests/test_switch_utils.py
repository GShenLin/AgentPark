import pytest

from src.switch_utils import parse_bool_switch
from src.switch_utils import parse_switch_mode
from src.switch_utils import require_bool_switch


def test_parse_switch_mode_accepts_canonical_values_and_auto():
    assert parse_switch_mode("enabled", default="disabled") == "enabled"
    assert parse_switch_mode("disabled", default="enabled") == "disabled"
    assert parse_switch_mode(True, default="disabled") == "disabled"
    assert parse_switch_mode("false", default="enabled") == "enabled"
    assert parse_switch_mode("auto", default="disabled") == "auto"
    assert parse_switch_mode("auto", default="disabled", allow_auto=False) == "disabled"
    assert parse_switch_mode("unknown", default=None) is None


def test_parse_bool_switch_accepts_booleans_only_and_default():
    assert parse_bool_switch(True, default=None) is True
    assert parse_bool_switch(False, default=True) is False
    assert parse_bool_switch("enabled", default=None) is None
    assert parse_bool_switch("false", default=True) is True
    assert parse_bool_switch("", default=False) is False
    assert parse_bool_switch("unknown", default=None) is None


def test_require_bool_switch_raises_with_prefixed_field_name():
    with pytest.raises(ValueError, match="Zhipu do_sample must be a boolean"):
        require_bool_switch("unknown", "do_sample", prefix="Zhipu")
