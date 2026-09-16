"""save -> load の round-trip（合意文書 §8）。"""

from __future__ import annotations

import json

import numpy as np
import pytest
from conftest import compute_quietly, conditions, lines_quietly

from fcenvelope import (
    FCEnvelopeInput,
    SchemaVersionError,
    Selection,
    UnsupportedUnitError,
    VibrationalMode,
    load_envelope,
    load_lines,
    save_envelope,
    save_lines,
)
from fcenvelope.errors import InvalidInputError
from fcenvelope.io import load_any


@pytest.fixture
def result(multi_mode):
    return compute_quietly(
        multi_mode,
        **conditions(temperature=300.0, sigma=150.0, e_min=-6000.0, e_max=2000.0, de=5.0),
    )


def test_round_trip_is_exact(result, tmp_path):
    path = tmp_path / "result.json"
    save_envelope(result, path)
    restored = load_envelope(path)

    np.testing.assert_array_equal(restored.energy, result.energy)
    np.testing.assert_array_equal(restored.density, result.density)
    assert restored.modes == result.modes
    assert restored.temperature == result.temperature
    assert restored.broadening == result.broadening
    assert restored.grid == result.grid
    assert restored.reorganization_energy == result.reorganization_energy
    assert restored.diagnostics == result.diagnostics
    assert restored.fcenvelope_version == result.fcenvelope_version
    assert restored.created_at == result.created_at
    assert restored.energy_unit == result.energy_unit
    assert restored.density_unit == result.density_unit


def test_save_load_save_leaves_the_file_byte_identical(result, tmp_path):
    """来歴は計算時に確定しているため、往復してもファイルは変化しない。"""
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    save_envelope(result, first)
    save_envelope(load_envelope(first), second)
    assert first.read_bytes() == second.read_bytes()


def test_written_input_echo_is_canonical(tmp_path):
    """入力エコーは常に huang_rhys 流儀で書き出される。"""
    parsed = FCEnvelopeInput.from_obj(
        {
            "schema_version": 2,
            "coupling_convention": "g",
            "modes": [{"frequency": 1200.0, "coupling": 0.5}],
            "temperature": 300.0,
            "broadening": {"sigma": 150.0},
            "grid": {"e_min": -4000.0, "e_max": 1000.0, "de": 5.0},
        }
    )
    path = tmp_path / "result.json"
    save_envelope(
        compute_quietly(
            parsed.to_modes(),
            temperature=parsed.temperature,
            broadening=parsed.broadening,
            grid=parsed.grid,
        ),
        path,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["kind"] == "fcenvelope.envelope"
    assert payload["input"]["coupling_convention"] == "huang_rhys"
    assert payload["input"]["frequency_unit"] == "cm^-1"
    assert payload["input"]["modes"] == [{"frequency": 1200.0, "coupling": 0.25}]
    assert payload["input"]["temperature"] == 300.0
    assert payload["input"]["broadening"] == {"sigma": 150.0, "gamma": 0.0}
    assert payload["input"]["grid"] == {"e_min": -4000.0, "e_max": 1000.0, "de": 5.0}
    assert payload["energy_unit"] == "cm^-1"
    assert payload["density_unit"] == "1/cm^-1"
    assert payload["derived"]["reorganization_energy"] == 300.0
    assert payload["created_at"].endswith("Z")


def test_spectrum_arrays_match_the_result(result, tmp_path):
    path = tmp_path / "result.json"
    save_envelope(result, path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert len(payload["spectrum"]["energy"]) == result.energy.size
    assert payload["spectrum"]["energy"][0] == result.energy[0]
    assert payload["spectrum"]["density"][-1] == result.density[-1]


def test_nested_output_directory_is_created(result, tmp_path):
    path = tmp_path / "deep" / "nested" / "result.json"
    save_envelope(result, path)
    assert path.is_file()


def _corrupt(path, mutate):
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_schema_version_mismatch(result, tmp_path):
    path = tmp_path / "result.json"
    save_envelope(result, path)
    _corrupt(path, lambda p: p.update(schema_version=1))
    with pytest.raises(SchemaVersionError):
        load_envelope(path)


def test_unsupported_energy_unit(result, tmp_path):
    path = tmp_path / "result.json"
    save_envelope(result, path)
    _corrupt(path, lambda p: p.update(energy_unit="eV"))
    with pytest.raises(UnsupportedUnitError):
        load_envelope(path)


def test_unexpected_kind(result, tmp_path):
    path = tmp_path / "result.json"
    save_envelope(result, path)
    _corrupt(path, lambda p: p.update(kind="something.else"))
    with pytest.raises(InvalidInputError):
        load_envelope(path)


def test_missing_section(result, tmp_path):
    path = tmp_path / "result.json"
    save_envelope(result, path)
    _corrupt(path, lambda p: p.pop("spectrum"))
    with pytest.raises(InvalidInputError):
        load_envelope(path)


def test_invalid_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(InvalidInputError):
        load_envelope(path)


def test_missing_file(tmp_path):
    with pytest.raises(InvalidInputError):
        load_envelope(tmp_path / "absent.json")


def test_load_input_file(tmp_path, input_payload):
    path = tmp_path / "input.json"
    path.write_text(json.dumps(input_payload), encoding="utf-8")
    parsed = FCEnvelopeInput.from_path(path)
    assert parsed.to_modes()[0] == VibrationalMode(frequency=1200.0, huang_rhys=0.25)
    assert parsed.temperature == 300.0


# --- 離散 FC 因子の save -> load ---


@pytest.fixture
def lines_result(multi_mode):
    return lines_quietly(multi_mode, temperature=300.0, min_weight=1e-4)


def test_fc_lines_round_trip_is_exact(lines_result, tmp_path):
    path = tmp_path / "lines.json"
    save_lines(lines_result, path)
    assert load_lines(path) == lines_result


def test_fc_lines_save_load_save_is_byte_identical(lines_result, tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    save_lines(lines_result, first)
    save_lines(load_lines(first), second)
    assert first.read_bytes() == second.read_bytes()


def test_fc_lines_payload_shape(lines_result, tmp_path):
    path = tmp_path / "lines.json"
    save_lines(lines_result, path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["kind"] == "fcenvelope.fc_lines"
    assert payload["schema_version"] == 2
    assert payload["energy_unit"] == "cm^-1"
    assert payload["input"]["coupling_convention"] == "huang_rhys"
    assert payload["input"]["temperature"] == 300.0
    assert payload["selection"] == {
        "min_weight": 1e-4,
        "max_lines": 10000,
        "max_quanta": None,
    }
    assert len(payload["lines"]) == lines_result.diagnostics.n_lines
    first = payload["lines"][0]
    assert set(first) == {"energy", "fc_factor", "weight", "transitions"}
    assert first["energy"] == lines_result.lines[0].energy


def test_fc_lines_reject_the_envelope_kind(result, tmp_path):
    path = tmp_path / "result.json"
    save_envelope(result, path)
    with pytest.raises(InvalidInputError):
        load_lines(path)


def test_load_envelope_rejects_the_fc_lines_kind(lines_result, tmp_path):
    path = tmp_path / "lines.json"
    save_lines(lines_result, path)
    with pytest.raises(InvalidInputError):
        load_envelope(path)


def test_load_any_dispatches_on_kind(result, lines_result, tmp_path):
    envelope_path = tmp_path / "result.json"
    lines_path = tmp_path / "lines.json"
    save_envelope(result, envelope_path)
    save_lines(lines_result, lines_path)

    restored = load_any(envelope_path)
    assert type(restored) is type(result)
    np.testing.assert_array_equal(restored.density, result.density)
    assert load_any(lines_path) == lines_result


def test_fc_lines_schema_version_mismatch(lines_result, tmp_path):
    path = tmp_path / "lines.json"
    save_lines(lines_result, path)
    _corrupt(path, lambda p: p.update(schema_version=1))
    with pytest.raises(SchemaVersionError):
        load_lines(path)


def test_fc_lines_unsupported_energy_unit(lines_result, tmp_path):
    path = tmp_path / "lines.json"
    save_lines(lines_result, path)
    _corrupt(path, lambda p: p.update(energy_unit="eV"))
    with pytest.raises(UnsupportedUnitError):
        load_lines(path)


def test_fc_lines_non_canonical_echo_is_rejected(lines_result, tmp_path):
    """エコーは常に huang_rhys 流儀。他の流儀は曖昧なので受け付けない。"""
    path = tmp_path / "lines.json"
    save_lines(lines_result, path)
    _corrupt(path, lambda p: p["input"].update(coupling_convention="g"))
    with pytest.raises(InvalidInputError):
        load_lines(path)


@pytest.mark.parametrize("section", ["lines", "selection", "diagnostics", "input"])
def test_fc_lines_missing_section(lines_result, tmp_path, section):
    path = tmp_path / "lines.json"
    save_lines(lines_result, path)
    _corrupt(path, lambda p: p.pop(section))
    with pytest.raises(InvalidInputError):
        load_lines(path)


def test_fc_lines_malformed_transition(lines_result, tmp_path):
    path = tmp_path / "lines.json"
    save_lines(lines_result, path)
    _corrupt(path, lambda p: p["lines"][1].update(transitions=[{"mode": 0}]))
    with pytest.raises(InvalidInputError):
        load_lines(path)


def test_fc_lines_round_trip_carries_max_quanta(multi_mode, tmp_path):
    """`Selection` を丸ごと持つので max_quanta も結果から再現できる（ADR-0035）。"""
    result = lines_quietly(
        multi_mode,
        temperature=300.0,
        selection=Selection(min_weight=1e-4, max_lines=5000, max_quanta=9),
    )
    path = tmp_path / "lines.json"
    save_lines(result, path)
    assert load_lines(path).selection == result.selection
