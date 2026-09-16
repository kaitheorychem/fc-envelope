"""save -> load の round-trip（合意文書 §8）。"""

from __future__ import annotations

import json

import numpy as np
import pytest
from conftest import compute_quietly, lines_quietly

from fcenvelope import (
    Conditions,
    FCEnvelopeInput,
    SchemaVersionError,
    UnsupportedUnitError,
    VibrationalMode,
    load_fc_lines,
    load_result,
    save_fc_lines,
    save_result,
)
from fcenvelope.errors import InvalidInputError
from fcenvelope.io import load_any


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


# --- 離散 FC 因子の save -> load ---


@pytest.fixture
def lines_result(multi_mode):
    return lines_quietly(multi_mode, temperature=300.0, min_intensity=1e-4)


def test_fc_lines_round_trip_is_exact(lines_result, tmp_path):
    path = tmp_path / "lines.json"
    save_fc_lines(lines_result, path)
    assert load_fc_lines(path) == lines_result


def test_fc_lines_save_load_save_is_byte_identical(lines_result, tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    save_fc_lines(lines_result, first)
    save_fc_lines(load_fc_lines(first), second)
    assert first.read_bytes() == second.read_bytes()


def test_fc_lines_payload_shape(lines_result, tmp_path):
    path = tmp_path / "lines.json"
    save_fc_lines(lines_result, path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["kind"] == "fcenvelope.fc_lines"
    assert payload["schema_version"] == 1
    assert payload["energy_unit"] == "cm^-1"
    assert payload["input"]["coupling_convention"] == "huang_rhys"
    assert payload["input"]["temperature"] == 300.0
    assert payload["selection"] == {"min_intensity": 1e-4, "max_lines": 10000}
    assert len(payload["lines"]) == lines_result.diagnostics.n_lines
    first = payload["lines"][0]
    assert set(first) == {"energy", "fc_factor", "intensity", "transitions"}
    assert first["energy"] == lines_result.lines[0].energy


def test_fc_lines_reject_the_envelope_kind(result, tmp_path):
    path = tmp_path / "result.json"
    save_result(result, path)
    with pytest.raises(InvalidInputError):
        load_fc_lines(path)


def test_load_result_rejects_the_fc_lines_kind(lines_result, tmp_path):
    path = tmp_path / "lines.json"
    save_fc_lines(lines_result, path)
    with pytest.raises(InvalidInputError):
        load_result(path)


def test_load_any_dispatches_on_kind(result, lines_result, tmp_path):
    envelope_path = tmp_path / "result.json"
    lines_path = tmp_path / "lines.json"
    save_result(result, envelope_path)
    save_fc_lines(lines_result, lines_path)

    restored = load_any(envelope_path)
    assert type(restored) is type(result)
    np.testing.assert_array_equal(restored.intensity, result.intensity)
    assert load_any(lines_path) == lines_result


def test_fc_lines_schema_version_mismatch(lines_result, tmp_path):
    path = tmp_path / "lines.json"
    save_fc_lines(lines_result, path)
    _corrupt(path, lambda p: p.update(schema_version=2))
    with pytest.raises(SchemaVersionError):
        load_fc_lines(path)


def test_fc_lines_unsupported_energy_unit(lines_result, tmp_path):
    path = tmp_path / "lines.json"
    save_fc_lines(lines_result, path)
    _corrupt(path, lambda p: p.update(energy_unit="eV"))
    with pytest.raises(UnsupportedUnitError):
        load_fc_lines(path)


def test_fc_lines_non_canonical_echo_is_rejected(lines_result, tmp_path):
    """エコーは常に huang_rhys 流儀。他の流儀は曖昧なので受け付けない。"""
    path = tmp_path / "lines.json"
    save_fc_lines(lines_result, path)
    _corrupt(path, lambda p: p["input"].update(coupling_convention="g"))
    with pytest.raises(InvalidInputError):
        load_fc_lines(path)


@pytest.mark.parametrize("section", ["lines", "selection", "diagnostics", "input"])
def test_fc_lines_missing_section(lines_result, tmp_path, section):
    path = tmp_path / "lines.json"
    save_fc_lines(lines_result, path)
    _corrupt(path, lambda p: p.pop(section))
    with pytest.raises(InvalidInputError):
        load_fc_lines(path)


def test_fc_lines_malformed_transition(lines_result, tmp_path):
    path = tmp_path / "lines.json"
    save_fc_lines(lines_result, path)
    _corrupt(path, lambda p: p["lines"][1].update(transitions=[{"mode": 0}]))
    with pytest.raises(InvalidInputError):
        load_fc_lines(path)
