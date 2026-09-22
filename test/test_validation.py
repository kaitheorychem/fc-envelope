"""入力検証と例外階層（合意文書 §4, §10.2）。"""

from __future__ import annotations

import copy
import json

import pytest

from fcenvelope import (
    Broadening,
    EnergyGrid,
    FCEnvelopeError,
    FCEnvelopeInput,
    InvalidInputError,
    SchemaVersionError,
    UnsupportedUnitError,
    VibrationalMode,
    VibrationalSystem,
)


def test_valid_payload_parses(input_payload):
    parsed = FCEnvelopeInput.from_obj(input_payload)
    assert parsed.to_system() == VibrationalSystem(
        [
            VibrationalMode(frequency=1200.0, huang_rhys=0.25),
            VibrationalMode(frequency=450.0, huang_rhys=0.6400000000000001),
        ]
    )
    assert parsed.to_broadening() == Broadening(sigma=150.0)
    assert parsed.to_grid() == EnergyGrid.from_spacing(e_min=-4500.0, e_max=1000.0, de=4.0)
    assert parsed.to_temperature() == 300.0


def test_unsupported_frequency_unit(input_payload):
    """換算表にない単位は受けない。波長は表に載せていない（ADR-0054）。"""
    payload = copy.deepcopy(input_payload)
    payload["frequency_unit"] = "nm"
    with pytest.raises(UnsupportedUnitError):
        FCEnvelopeInput.from_obj(payload)


def test_schema_version_mismatch(input_payload):
    payload = copy.deepcopy(input_payload)
    payload["schema_version"] = 1
    with pytest.raises(SchemaVersionError):
        FCEnvelopeInput.from_obj(payload)


def test_empty_modes(input_payload):
    payload = copy.deepcopy(input_payload)
    payload["modes"] = []
    with pytest.raises(InvalidInputError):
        FCEnvelopeInput.from_obj(payload)


@pytest.mark.parametrize(
    ("convention", "field", "value"),
    [
        ("g", "frequency", 0.0),
        ("g", "frequency", -1200.0),
        ("huang_rhys", "coupling", -0.5),
    ],
)
def test_invalid_mode_values(input_payload, convention, field, value):
    """範囲の検査は値の型が行い、エラーにフィールドの位置が付く（ADR-0051）。"""
    payload = copy.deepcopy(input_payload)
    payload["coupling_convention"] = convention
    payload["modes"][0][field] = value
    parsed = FCEnvelopeInput.from_obj(payload)
    with pytest.raises(InvalidInputError, match=r"modes\[0\]"):
        parsed.to_system()


def test_negative_g_is_accepted_because_its_sign_is_meaningless(input_payload):
    """S = g^2 なので g の符号は FC 因子に効かない（ADR-0003）。"""
    payload = copy.deepcopy(input_payload)
    payload["coupling_convention"] = "g"
    payload["modes"][0]["coupling"] = -0.5
    assert FCEnvelopeInput.from_obj(payload).to_system().modes[0].huang_rhys == 0.25


@pytest.mark.parametrize(
    ("block", "field", "value", "reader"),
    [
        (None, "temperature", -1.0, "to_temperature"),
        ("broadening", "sigma", 0.0, "to_broadening"),
        ("broadening", "sigma", -150.0, "to_broadening"),
        ("grid.points", "de", 0.0, "to_grid"),
        ("grid.points", "de", -5.0, "to_grid"),
        ("selection", "min_weight", 0.0, "to_selection"),
        ("selection", "max_lines", 0, "to_selection"),
        ("selection", "max_quanta", -1, "to_selection"),
    ],
)
def test_invalid_condition_values(input_payload, block, field, value, reader):
    """範囲違反のエラーには、入力ファイル中のどこかが書いてある（ADR-0051）。"""
    payload = copy.deepcopy(input_payload)
    if block is None:
        payload[field] = value
        location = field
    else:
        target = payload
        for name in block.split("."):
            target = target.setdefault(name, {})
        target[field] = value
        location = block.split(".")[0]
    parsed = FCEnvelopeInput.from_obj(payload)
    with pytest.raises(InvalidInputError, match=location):
        getattr(parsed, reader)()


def test_zero_temperature_is_allowed(input_payload):
    payload = copy.deepcopy(input_payload)
    payload["temperature"] = 0.0
    assert FCEnvelopeInput.from_obj(payload).to_temperature() == 0.0


def test_selection_defaults_come_from_the_value_type(input_payload):
    """入力ファイルで省略したつまみは `Selection` の既定値になる（ADR-0050）。"""
    from fcenvelope import Selection

    assert FCEnvelopeInput.from_obj(input_payload).to_selection() == Selection()


@pytest.mark.parametrize(("e_min", "e_max"), [(1000.0, 1000.0), (1000.0, -4000.0)])
def test_window_must_be_ordered(input_payload, e_min, e_max):
    payload = copy.deepcopy(input_payload)
    payload["grid"]["e_min"] = e_min
    payload["grid"]["e_max"] = e_max
    with pytest.raises(InvalidInputError, match="grid"):
        FCEnvelopeInput.from_obj(payload).to_grid()


def test_value_types_reject_bad_values_when_built_directly():
    """ライブラリから直接作った場合も同じように止まる（ADR-0051）。"""
    with pytest.raises(InvalidInputError, match="e_min"):
        EnergyGrid.from_spacing(e_min=10.0, e_max=-10.0, de=1.0)
    with pytest.raises(InvalidInputError, match="sigma"):
        Broadening(sigma=-1.0)
    with pytest.raises(InvalidInputError, match="frequency"):
        VibrationalMode(frequency=0.0, huang_rhys=0.5)


# `broadening` / `grid` を書かなかった場合は構造の誤りではなく、それを読む副命令から見た
# 不足である。その扱いは `test_optional_blocks.py` にある（ADR-0075）。


@pytest.mark.parametrize(
    "convention", [{"a": 1}, ["g"], 5, None, True]
)
def test_non_string_convention_is_an_input_error(input_payload, convention):
    """名前でない値も、未知の名前と同じ形で報告される。

    辞書やリストは辞書のキーにできないので、素朴に引くと `TypeError` が漏れる。
    本パッケージが送出する例外はすべて `FCEnvelopeError` の派生である（ADR-0013）。
    """
    payload = copy.deepcopy(input_payload)
    payload["coupling_convention"] = convention
    with pytest.raises(InvalidInputError, match="coupling_convention"):
        FCEnvelopeInput.from_obj(payload)


def test_invalid_json_text():
    with pytest.raises(InvalidInputError):
        FCEnvelopeInput.from_json("{oops")


def test_missing_input_file(tmp_path):
    with pytest.raises(InvalidInputError):
        FCEnvelopeInput.from_path(tmp_path / "absent.json")


@pytest.mark.parametrize(
    "error", [InvalidInputError, UnsupportedUnitError, SchemaVersionError]
)
def test_exception_hierarchy(error):
    assert issubclass(error, FCEnvelopeError)


def test_models_are_frozen(input_payload):
    parsed = FCEnvelopeInput.from_obj(input_payload)
    with pytest.raises(Exception):
        parsed.broadening.sigma = 10.0
    with pytest.raises(Exception):
        parsed.to_grid().de = 1.0


def test_from_json_accepts_text(input_payload):
    parsed = FCEnvelopeInput.from_json(json.dumps(input_payload))
    assert len(parsed.modes) == 2
