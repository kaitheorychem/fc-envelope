"""save -> load の round-trip（合意文書 §8）。"""

from __future__ import annotations

import json

import numpy as np
import pytest
from conftest import compute_quietly, lines_quietly

from fcenvelope import (
    Broadening,
    EnergyGrid,
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
from fcenvelope import inputs as inputs_module
from fcenvelope.errors import FCEnvelopeError, InvalidInputError
from fcenvelope.io import SCHEMA_VERSION, load_any


@pytest.fixture
def result(multi_mode):
    return compute_quietly(
        multi_mode,
        temperature=300.0,
        broadening=Broadening(sigma=150.0),
        grid=EnergyGrid.from_spacing(e_min=-6000.0, e_max=2000.0, de=5.0),
    )


def test_the_result_file_counts_its_version_on_its_own():
    """結果ファイルは入力ファイルの形を写さないので、版も別に数える（ADR-0080）。

    `io` は `inputs` に依存しない（ADR-0041）ので、両者の関係はここで確かめる。
    """
    assert (SCHEMA_VERSION, inputs_module.SCHEMA_VERSION) == (4, 4)


def test_round_trip_is_exact(result, tmp_path):
    path = tmp_path / "result.json"
    save_envelope(result, path)
    restored = load_envelope(path)

    np.testing.assert_array_equal(restored.energy, result.energy)
    np.testing.assert_array_equal(restored.density, result.density)
    assert restored.system == result.system
    assert restored.temperature == result.temperature
    assert restored.broadening == result.broadening
    assert restored.grid == result.grid
    assert restored.diagnostics == result.diagnostics
    assert restored.provenance == result.provenance


def test_save_load_save_leaves_the_file_byte_identical(result, tmp_path):
    """来歴は計算時に確定しているため、往復してもファイルは変化しない。"""
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    save_envelope(result, first)
    save_envelope(load_envelope(first), second)
    assert first.read_bytes() == second.read_bytes()


def test_written_conditions_hold_the_huang_rhys_factor(tmp_path):
    """計算条件のモードは流儀によらず振動数と S で書き出される（ADR-0080）。"""
    parsed = FCEnvelopeInput.from_obj(
        {
            "schema_version": 4,
            "modes": {
                "coupling_convention": "g",
                "rows": [{"frequency": 1200.0, "coupling": 0.5}],
            },
            "temperature": 300.0,
            "broadening": {"sigma": 150.0},
            "grid": {"e_min": -4000.0, "e_max": 1000.0, "points": {"de": 5.0}},
        }
    )
    path = tmp_path / "result.json"
    save_envelope(
        compute_quietly(
            parsed.to_system(),
            temperature=parsed.to_temperature(),
            broadening=parsed.to_broadening(),
            grid=parsed.to_grid(),
        ),
        path,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["kind"] == "fcenvelope.envelope"
    assert payload["conditions"]["modes"] == {
        "frequency_unit": "cm^-1",
        "rows": [{"frequency": 1200.0, "huang_rhys": 0.25}],
    }
    assert payload["conditions"]["temperature"] == 300.0
    assert payload["conditions"]["broadening"] == {"sigma": [150.0, "cm^-1"]}
    assert payload["conditions"]["grid"] == {
        "e_min": [-4000.0, "cm^-1"],
        "e_max": [1000.0, "cm^-1"],
        "de": [5.0, "cm^-1"],
        "n_fft": 2048,
    }
    assert payload["spectrum"]["energy_unit"] == "cm^-1"
    assert payload["spectrum"]["density_unit"] == "1/cm^-1"
    assert payload["derived"]["reorganization_energy"] == [300.0, "cm^-1"]
    assert payload["diagnostics"]["d_tau"][1] == "cm"
    assert "energy_unit" not in payload  # 単位は値か表の側に書く（ADR-0081）
    assert payload["created_at"].endswith("Z")


def test_conditions_do_not_carry_the_input_file_vocabulary(result, lines_result, tmp_path):
    """単位と流儀の欄を持たないので、入力ファイルの書き方が変わっても形は変わらない（ADR-0080）。"""
    for name, save, value in (
        ("envelope.json", save_envelope, result),
        ("lines.json", save_lines, lines_result),
    ):
        path = tmp_path / name
        save(value, path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert "input" not in payload
        conditions = payload["conditions"]
        assert not {"frequency_unit", "coupling_convention", "coupling_unit"} & set(conditions)
        rows = conditions["modes"]["rows"]
        assert all(set(mode) == {"frequency", "huang_rhys"} for mode in rows)


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


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda p: p["conditions"]["broadening"].update(sigma=[150.0, "eV"]),
        lambda p: p["conditions"]["grid"].update(de=[5.0, "eV"]),
        lambda p: p["conditions"]["modes"].update(frequency_unit="eV"),
        lambda p: p["spectrum"].update(energy_unit="eV"),
        lambda p: p["spectrum"].update(density_unit="1/eV"),
        lambda p: p["diagnostics"].update(d_tau=[p["diagnostics"]["d_tau"][0], "fs"]),
    ],
    ids=["sigma", "grid.de", "modes", "spectrum.energy", "spectrum.density", "d_tau"],
)
def test_unsupported_unit(result, tmp_path, corrupt):
    """単位は書いた値や表の側で確かめ、正準単位以外は受けない（ADR-0081）。"""
    path = tmp_path / "result.json"
    save_envelope(result, path)
    _corrupt(path, corrupt)
    with pytest.raises(UnsupportedUnitError):
        load_envelope(path)


def test_a_bare_number_where_a_pair_belongs_is_rejected(result, tmp_path):
    path = tmp_path / "result.json"
    save_envelope(result, path)
    _corrupt(path, lambda p: p["conditions"]["broadening"].update(sigma=150.0))
    with pytest.raises(InvalidInputError, match="conditions.broadening.sigma"):
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


def test_derived_is_written_but_skipped_when_loading(result, tmp_path):
    """lambda は系から決まるので結果クラスは持たない（ADR-0047）。"""
    path = tmp_path / "result.json"
    save_envelope(result, path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["derived"]["reorganization_energy"] == [
        result.system.reorganization_energy,
        "cm^-1",
    ]

    _corrupt(path, lambda p: p.pop("derived"))
    restored = load_envelope(path)
    assert restored.system.reorganization_energy == result.system.reorganization_energy


def test_a_stale_derived_block_does_not_reach_the_result(result, tmp_path):
    path = tmp_path / "result.json"
    save_envelope(result, path)
    _corrupt(path, lambda p: p["derived"].update(reorganization_energy=-1.0))
    assert load_envelope(path).system.reorganization_energy > 0.0


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
    assert parsed.to_system().modes[0] == VibrationalMode(
        frequency=1200.0, huang_rhys=0.25
    )
    assert parsed.to_temperature() == 300.0


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
    assert payload["schema_version"] == 4
    assert payload["conditions"]["modes"]["rows"][0].keys() == {"frequency", "huang_rhys"}
    assert payload["conditions"]["temperature"] == 300.0
    assert payload["conditions"]["selection"] == {
        "min_weight": 1e-4,
        "max_lines": 10000,
        "max_quanta": None,
    }
    assert payload["lines"]["energy_unit"] == "cm^-1"
    assert payload["diagnostics"]["mean_energy"][1] == "cm^-1"
    assert len(payload["lines"]["rows"]) == lines_result.diagnostics.n_lines
    first = payload["lines"]["rows"][0]
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
    _corrupt(path, lambda p: p["lines"].update(energy_unit="eV"))
    with pytest.raises(UnsupportedUnitError):
        load_lines(path)


def test_fc_lines_mode_without_the_huang_rhys_factor_is_rejected(lines_result, tmp_path):
    """モードは S を `huang_rhys` の名前で持つ。別の名前の値は流儀が曖昧なので受けない。"""
    path = tmp_path / "lines.json"
    save_lines(lines_result, path)
    def rename(payload):
        mode = payload["conditions"]["modes"]["rows"][0]
        mode["coupling"] = mode.pop("huang_rhys")

    _corrupt(path, rename)
    with pytest.raises(InvalidInputError):
        load_lines(path)


@pytest.mark.parametrize("section", ["lines", "diagnostics", "conditions"])
def test_fc_lines_missing_section(lines_result, tmp_path, section):
    path = tmp_path / "lines.json"
    save_lines(lines_result, path)
    _corrupt(path, lambda p: p.pop(section))
    with pytest.raises(InvalidInputError):
        load_lines(path)


def test_fc_lines_missing_selection_echo(lines_result, tmp_path):
    path = tmp_path / "lines.json"
    save_lines(lines_result, path)
    _corrupt(path, lambda p: p["conditions"].pop("selection"))
    with pytest.raises(InvalidInputError, match="conditions.selection"):
        load_lines(path)


def test_max_quanta_round_trips(multi_mode, tmp_path):
    """`Selection` を丸ごとエコーするので `max_quanta` も往復する（ADR-0035）。"""
    result = lines_quietly(multi_mode, temperature=300.0, min_weight=1e-3, max_quanta=4)
    path = tmp_path / "lines.json"
    save_lines(result, path)
    assert load_lines(path).selection == Selection(
        min_weight=1e-3, max_lines=10000, max_quanta=4
    )


def test_out_of_range_echo_is_rejected_with_its_location(lines_result, tmp_path):
    """結果ファイル側でも範囲は値の型が見る（ADR-0051）。"""
    path = tmp_path / "lines.json"
    save_lines(lines_result, path)
    _corrupt(path, lambda p: p["conditions"]["selection"].update(min_weight=0.0))
    with pytest.raises(InvalidInputError, match="conditions.selection"):
        load_lines(path)


def test_fc_lines_malformed_transition(lines_result, tmp_path):
    path = tmp_path / "lines.json"
    save_lines(lines_result, path)
    _corrupt(path, lambda p: p["lines"]["rows"][1].update(transitions=[{"mode": 0}]))
    with pytest.raises(InvalidInputError):
        load_lines(path)


# --- 壊れた結果ファイルは必ず FCEnvelopeError になる（ADR-0013） ---


#: 位置 -> そこに置くと不正になる値。JSON は型を保証しないので、数を期待する場所に
#: 辞書やリストが来ることも、真偽値が来ることもある。
_CORRUPTIONS = {
    "kind": [None, 1, "x", [], {}, True],
    "diagnostics.messages": [None, 1, "x", {}, True, [1], ["ok", 2]],
    "spectrum.density": [None, 1, "x", {}, True, ["x"], [None]],
    "conditions.grid.de": [None, "x", [], {}, True, [1, 2]],
}

_SETTERS = {
    "kind": lambda p, v: p.update(kind=v),
    "diagnostics.messages": lambda p, v: p["diagnostics"].update(messages=v),
    "spectrum.density": lambda p, v: p["spectrum"].update(density=v),
    "conditions.grid.de": lambda p, v: p["conditions"]["grid"].update(de=v),
}


def _mutations():
    for location, bad_values in _CORRUPTIONS.items():
        for bad in bad_values:
            yield (
                f"{location}={bad!r}",
                lambda p, loc=location, v=bad: _SETTERS[loc](p, v),
            )


@pytest.mark.parametrize(
    ("label", "mutate"), list(_mutations()), ids=lambda x: x if isinstance(x, str) else ""
)
def test_corrupt_envelope_file_raises_a_package_error(result, tmp_path, label, mutate):
    """JSON は型を保証しないので、どの位置に何が入っていても素の例外を漏らさない。"""
    path = tmp_path / "result.json"
    save_envelope(result, path)
    _corrupt(path, mutate)
    with pytest.raises(FCEnvelopeError):
        load_any(path)


@pytest.mark.parametrize("bad", [None, "x", [], {}, 1.5, True])
def test_corrupt_selection_echo_raises_a_package_error(lines_result, tmp_path, bad):
    path = tmp_path / "lines.json"
    save_lines(lines_result, path)
    _corrupt(path, lambda p: p["conditions"]["selection"].update(max_lines=bad))
    with pytest.raises(FCEnvelopeError):
        load_any(path)
