"""save -> load の round-trip（合意文書 §8）。"""

from __future__ import annotations

import json

import numpy as np
import pytest
from conftest import compute_quietly

from fcenvelope import (
    Conditions,
    FCEnvelopeInput,
    SchemaVersionError,
    UnsupportedUnitError,
    VibrationalMode,
    load_result,
    save_result,
)
from fcenvelope.errors import InvalidInputError


@pytest.fixture
def result(multi_mode):
    conditions = Conditions(
        temperature=300.0, sigma=150.0, e_min=-6000.0, e_max=2000.0, de=5.0
    )
    return compute_quietly(multi_mode, conditions)


def test_round_trip_is_exact(result, tmp_path):
    path = tmp_path / "result.json"
    save_result(result, path)
    restored = load_result(path)

    np.testing.assert_array_equal(restored.energy, result.energy)
    np.testing.assert_array_equal(restored.intensity, result.intensity)
    assert restored.modes == result.modes
    assert restored.conditions == result.conditions
    assert restored.reorganization_energy == result.reorganization_energy
    assert restored.diagnostics == result.diagnostics
    assert restored.fcenvelope_version == result.fcenvelope_version
    assert restored.created_at == result.created_at
    assert restored.energy_unit == result.energy_unit
    assert restored.intensity_unit == result.intensity_unit


def test_save_load_save_leaves_the_file_byte_identical(result, tmp_path):
    """来歴は計算時に確定しているため、往復してもファイルは変化しない。"""
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    save_result(result, first)
    save_result(load_result(first), second)
    assert first.read_bytes() == second.read_bytes()


def test_written_input_echo_is_canonical(tmp_path):
    """入力エコーは常に huang_rhys 流儀で書き出される。"""
    parsed = FCEnvelopeInput.from_obj(
        {
            "schema_version": 1,
            "coupling_convention": "g",
            "modes": [{"frequency": 1200.0, "coupling": 0.5}],
            "conditions": {
                "temperature": 300.0,
                "sigma": 150.0,
                "e_min": -4000.0,
                "e_max": 1000.0,
                "de": 5.0,
            },
        }
    )
    path = tmp_path / "result.json"
    save_result(compute_quietly(parsed.to_modes(), parsed.conditions), path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["kind"] == "fcenvelope.result"
    assert payload["input"]["coupling_convention"] == "huang_rhys"
    assert payload["input"]["frequency_unit"] == "cm^-1"
    assert payload["input"]["modes"] == [{"frequency": 1200.0, "coupling": 0.25}]
    assert payload["energy_unit"] == "cm^-1"
    assert payload["intensity_unit"] == "1/cm^-1"
    assert payload["derived"]["reorganization_energy"] == 300.0
    assert payload["created_at"].endswith("Z")


def test_spectrum_arrays_match_the_result(result, tmp_path):
    path = tmp_path / "result.json"
    save_result(result, path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert len(payload["spectrum"]["energy"]) == result.energy.size
    assert payload["spectrum"]["energy"][0] == result.energy[0]
    assert payload["spectrum"]["intensity"][-1] == result.intensity[-1]


def test_nested_output_directory_is_created(result, tmp_path):
    path = tmp_path / "deep" / "nested" / "result.json"
    save_result(result, path)
    assert path.is_file()


def _corrupt(path, mutate):
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_schema_version_mismatch(result, tmp_path):
    path = tmp_path / "result.json"
    save_result(result, path)
    _corrupt(path, lambda p: p.update(schema_version=2))
    with pytest.raises(SchemaVersionError):
        load_result(path)


def test_unsupported_energy_unit(result, tmp_path):
    path = tmp_path / "result.json"
    save_result(result, path)
    _corrupt(path, lambda p: p.update(energy_unit="eV"))
    with pytest.raises(UnsupportedUnitError):
        load_result(path)


def test_unexpected_kind(result, tmp_path):
    path = tmp_path / "result.json"
    save_result(result, path)
    _corrupt(path, lambda p: p.update(kind="something.else"))
    with pytest.raises(InvalidInputError):
        load_result(path)


def test_missing_section(result, tmp_path):
    path = tmp_path / "result.json"
    save_result(result, path)
    _corrupt(path, lambda p: p.pop("spectrum"))
    with pytest.raises(InvalidInputError):
        load_result(path)


def test_invalid_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(InvalidInputError):
        load_result(path)


def test_missing_file(tmp_path):
    with pytest.raises(InvalidInputError):
        load_result(tmp_path / "absent.json")


def test_load_input_file(tmp_path, input_payload):
    path = tmp_path / "input.json"
    path.write_text(json.dumps(input_payload), encoding="utf-8")
    parsed = FCEnvelopeInput.from_path(path)
    assert parsed.to_modes()[0] == VibrationalMode(frequency=1200.0, huang_rhys=0.25)
    assert parsed.conditions.temperature == 300.0
