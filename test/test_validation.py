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
)


def test_valid_payload_parses(input_payload):
    parsed = FCEnvelopeInput.from_obj(input_payload)
    modes = parsed.to_modes()
    assert modes == [
        VibrationalMode(frequency=1200.0, huang_rhys=0.25),
        VibrationalMode(frequency=450.0, huang_rhys=0.6400000000000001),
    ]


def test_unsupported_frequency_unit(input_payload):
    payload = copy.deepcopy(input_payload)
    payload["frequency_unit"] = "eV"
    with pytest.raises(UnsupportedUnitError):
        FCEnvelopeInput.from_obj(payload)


@pytest.mark.parametrize("version", [1, 3, "2"])
def test_schema_version_mismatch(input_payload, version):
    """v1 の互換層は置かない。明示的に拒否する（ADR-0040）。"""
    payload = copy.deepcopy(input_payload)
    payload["schema_version"] = version
    with pytest.raises(SchemaVersionError):
        FCEnvelopeInput.from_obj(payload)


def test_empty_modes(input_payload):
    payload = copy.deepcopy(input_payload)
    payload["modes"] = []
    with pytest.raises(InvalidInputError):
        FCEnvelopeInput.from_obj(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("frequency", 0.0),
        ("frequency", -1200.0),
        ("coupling", -0.5),
    ],
)
def test_invalid_mode_values(input_payload, field, value):
    payload = copy.deepcopy(input_payload)
    payload["modes"][0][field] = value
    with pytest.raises(InvalidInputError):
        FCEnvelopeInput.from_obj(payload)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        (None, "temperature", -1.0),
        ("broadening", "sigma", 0.0),
        ("broadening", "sigma", -150.0),
        ("broadening", "gamma", -1.0),
        ("grid", "de", 0.0),
        ("grid", "de", -5.0),
    ],
)
def test_invalid_condition_values(input_payload, section, field, value):
    payload = copy.deepcopy(input_payload)
    target = payload if section is None else payload[section]
    target[field] = value
    with pytest.raises(InvalidInputError):
        FCEnvelopeInput.from_obj(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [("min_weight", 0.0), ("min_weight", 1.5), ("max_lines", 0), ("max_quanta", -1)],
)
def test_invalid_selection_values(input_payload, field, value):
    payload = copy.deepcopy(input_payload)
    payload["selection"][field] = value
    with pytest.raises(InvalidInputError):
        FCEnvelopeInput.from_obj(payload)


def test_selection_section_is_optional(input_payload):
    """`lines` を使わない入力でも節を書かずに済む。既定は `Selection()`。"""
    payload = copy.deepcopy(input_payload)
    del payload["selection"]
    assert FCEnvelopeInput.from_obj(payload).selection.min_weight == 1e-4


def test_zero_temperature_is_allowed(input_payload):
    payload = copy.deepcopy(input_payload)
    payload["temperature"] = 0.0
    assert FCEnvelopeInput.from_obj(payload).temperature == 0.0


@pytest.mark.parametrize(("e_min", "e_max"), [(1000.0, 1000.0), (1000.0, -4000.0)])
def test_window_must_be_ordered(input_payload, e_min, e_max):
    payload = copy.deepcopy(input_payload)
    payload["grid"]["e_min"] = e_min
    payload["grid"]["e_max"] = e_max
    with pytest.raises(InvalidInputError):
        FCEnvelopeInput.from_obj(payload)


def test_value_models_raise_the_package_error_on_direct_construction():
    """公開 API から漏れる例外は `FCEnvelopeError` の一族に揃える（ADR-0013）。"""
    with pytest.raises(FCEnvelopeError):
        Broadening(sigma=-1.0)


def test_all_broken_sections_are_reported_at_once(input_payload):
    """節をまたいだ誤りを 1 度に報告する（直接構築の例外変換で潰さない）。"""
    payload = copy.deepcopy(input_payload)
    payload["temperature"] = -1.0
    payload["broadening"]["sigma"] = -1.0
    payload["grid"]["de"] = -5.0
    with pytest.raises(InvalidInputError) as excinfo:
        FCEnvelopeInput.from_obj(payload)
    message = str(excinfo.value)
    assert "temperature" in message
    assert "sigma" in message
    assert "de" in message


def test_energy_grid_rejects_a_bad_window():
    with pytest.raises(InvalidInputError) as excinfo:
        EnergyGrid(e_min=10.0, e_max=-10.0, de=1.0)
    assert "e_min" in str(excinfo.value)


def test_broadening_defaults_to_a_pure_gaussian():
    assert Broadening(sigma=150.0).gamma == 0.0


@pytest.mark.parametrize("section", ["temperature", "broadening", "grid"])
def test_missing_required_section(input_payload, section):
    payload = copy.deepcopy(input_payload)
    del payload[section]
    with pytest.raises(InvalidInputError):
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
        parsed.grid.de = 10.0


def test_from_json_accepts_text(input_payload):
    parsed = FCEnvelopeInput.from_json(json.dumps(input_payload))
    assert len(parsed.modes) == 2
