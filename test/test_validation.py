"""入力検証と例外階層（合意文書 §4, §10.2）。"""

from __future__ import annotations

import copy
import json

import pytest

from fcenvelope import (
    Conditions,
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


def test_schema_version_mismatch(input_payload):
    payload = copy.deepcopy(input_payload)
    payload["schema_version"] = 2
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
    ("field", "value"),
    [
        ("temperature", -1.0),
        ("sigma", 0.0),
        ("sigma", -150.0),
        ("de", 0.0),
        ("de", -5.0),
    ],
)
def test_invalid_condition_values(input_payload, field, value):
    payload = copy.deepcopy(input_payload)
    payload["conditions"][field] = value
    with pytest.raises(InvalidInputError):
        FCEnvelopeInput.from_obj(payload)


def test_zero_temperature_is_allowed(input_payload):
    payload = copy.deepcopy(input_payload)
    payload["conditions"]["temperature"] = 0.0
    assert FCEnvelopeInput.from_obj(payload).conditions.temperature == 0.0


@pytest.mark.parametrize(("e_min", "e_max"), [(1000.0, 1000.0), (1000.0, -4000.0)])
def test_window_must_be_ordered(input_payload, e_min, e_max):
    payload = copy.deepcopy(input_payload)
    payload["conditions"]["e_min"] = e_min
    payload["conditions"]["e_max"] = e_max
    with pytest.raises(InvalidInputError):
        FCEnvelopeInput.from_obj(payload)


def test_conditions_model_validate_rejects_bad_window():
    with pytest.raises(Exception) as excinfo:
        Conditions(temperature=0.0, sigma=1.0, e_min=10.0, e_max=-10.0, de=1.0)
    assert "e_min" in str(excinfo.value)


def test_missing_conditions(input_payload):
    payload = copy.deepcopy(input_payload)
    del payload["conditions"]
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
        parsed.conditions.temperature = 10.0


def test_from_json_accepts_text(input_payload):
    parsed = FCEnvelopeInput.from_json(json.dumps(input_payload))
    assert len(parsed.modes) == 2
