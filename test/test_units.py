"""エネルギー単位の換算表（ADR-0054）と、入力の境界でのその消費。

単位を変えても結果が変わらないことが、この一連の作業の主な検証軸になる。同じ物理系を
違う単位で書いた入力が、同一の系と同一のスペクトルを出すことを見る。
"""

from __future__ import annotations

import copy

import numpy as np
import pytest
from conftest import compute_quietly

from fcenvelope import FCEnvelopeInput, units
from fcenvelope.errors import UnsupportedUnitError


def _in_unit(value: float, unit: str) -> float:
    """cm^-1 の値を `unit` で書いたときの数値。"""
    return value / units.energy_conversion_factor(unit)


def _envelope(parsed: FCEnvelopeInput):
    return compute_quietly(
        parsed.to_system(),
        temperature=parsed.to_temperature(),
        broadening=parsed.to_broadening(),
        grid=parsed.to_grid(),
    )


def _assert_same_spectrum(left: FCEnvelopeInput, right: FCEnvelopeInput) -> None:
    """2 つの入力が同じスペクトルを出すこと。判定は ADR-0042 の形にする。"""
    expected = _envelope(right).density
    np.testing.assert_allclose(
        _envelope(left).density, expected, rtol=0.0, atol=1e-12 * float(expected.max())
    )


def test_the_canonical_unit_has_a_factor_of_one():
    assert units.CANONICAL_ENERGY_UNIT == "cm^-1"
    assert units.energy_conversion_factor("cm^-1") == 1.0


@pytest.mark.parametrize("unit", sorted(units.ENERGY_UNITS))
def test_round_trip_through_each_unit(unit):
    """cm^-1 -> X -> cm^-1 が元に戻ること。表の各行が逆数として整合している。"""
    factor = units.energy_conversion_factor(unit)
    value = 1234.5
    assert value / factor * factor == pytest.approx(value, rel=1e-14)


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        # CODATA の既知の値との照合。scipy から導出した係数が桁ごと合っていること。
        ("eV", 8065.543937),
        ("hartree", 219474.6314),
        ("THz", 33.35640952),
        ("kJ/mol", 83.59347229),
        ("kcal/mol", 349.7550879),
    ],
)
def test_known_values(unit, expected):
    assert units.energy_conversion_factor(unit) == pytest.approx(expected, rel=1e-8)


def test_the_conversions_are_consistent_with_each_other():
    """独立に知られている単位どうしの関係が再現されること。"""
    ev = units.energy_conversion_factor("eV")
    hartree = units.energy_conversion_factor("hartree")
    kj = units.energy_conversion_factor("kJ/mol")
    kcal = units.energy_conversion_factor("kcal/mol")

    assert hartree / ev == pytest.approx(27.211386, rel=1e-6)  # 1 hartree [eV]
    assert kcal / kj == pytest.approx(4.184, rel=1e-12)  # 熱化学カロリー


@pytest.mark.parametrize("unit", ["nm", "cm-1", "ev", "", None, 1.0, {"unit": "eV"}])
def test_an_unknown_unit_is_rejected(unit):
    """波長も、綴りや大小の違いも受けない。未知の型でも同じ形で報告する。"""
    with pytest.raises(UnsupportedUnitError, match="unsupported energy unit"):
        units.energy_conversion_factor(unit)


def test_the_error_names_the_known_units():
    with pytest.raises(UnsupportedUnitError, match="kcal/mol"):
        units.energy_conversion_factor("nm")


def test_the_default_frequency_unit_is_the_canonical_one(input_payload):
    """単位フィールドを省いた既存の入力が、そのまま cm^-1 として読まれること。"""
    payload = copy.deepcopy(input_payload)
    del payload["frequency_unit"]
    parsed = FCEnvelopeInput.from_obj(payload)

    assert parsed.frequency_unit == units.CANONICAL_ENERGY_UNIT
    assert parsed.to_system() == FCEnvelopeInput.from_obj(input_payload).to_system()


@pytest.mark.parametrize("unit", sorted(set(units.ENERGY_UNITS) - {"cm^-1"}))
def test_the_same_system_written_in_another_unit(input_payload, unit):
    """cm^-1 で書いた系と、同じ系を別の単位で書いたものが一致すること。"""
    canonical = FCEnvelopeInput.from_obj(input_payload)

    payload = copy.deepcopy(input_payload)
    payload["frequency_unit"] = unit
    for mode in payload["modes"]:
        mode["frequency"] = _in_unit(mode["frequency"], unit)
    converted = FCEnvelopeInput.from_obj(payload)

    for got, want in zip(converted.to_system().modes, canonical.to_system().modes):
        assert got.frequency == pytest.approx(want.frequency, rel=1e-14)
        assert got.huang_rhys == pytest.approx(want.huang_rhys, rel=1e-14)
    _assert_same_spectrum(converted, canonical)


def test_the_frequency_unit_does_not_leak_past_the_boundary(input_payload):
    """正準化の後に単位は残らない。結果は cm^-1 の値だけを持つ（ADR-0054）。"""
    payload = copy.deepcopy(input_payload)
    payload["frequency_unit"] = "eV"
    payload["modes"] = [{"frequency": _in_unit(1200.0, "eV"), "coupling": 0.5}]

    mode = FCEnvelopeInput.from_obj(payload).to_system().modes[0]

    assert mode.frequency == pytest.approx(1200.0, rel=1e-14)


def test_sigma_and_grid_in_another_unit(input_payload):
    """eV で書いた sigma とグリッドが、cm^-1 の等価な入力と同じ結果を出すこと。"""
    canonical = FCEnvelopeInput.from_obj(input_payload)

    payload = copy.deepcopy(input_payload)
    payload["broadening"] = {"sigma": _in_unit(150.0, "eV"), "unit": "eV"}
    payload["grid"] = {
        "e_min": _in_unit(-4000.0, "eV"),
        "e_max": _in_unit(1000.0, "eV"),
        "de": _in_unit(5.0, "eV"),
        "unit": "eV",
    }
    converted = FCEnvelopeInput.from_obj(payload)

    assert converted.to_broadening().sigma == pytest.approx(150.0, rel=1e-14)
    grid = converted.to_grid()
    assert grid.e_min == pytest.approx(-4000.0, rel=1e-14)
    assert grid.e_max == pytest.approx(1000.0, rel=1e-14)
    assert grid.de == pytest.approx(5.0, rel=1e-14)
    _assert_same_spectrum(converted, canonical)


def test_the_unit_axes_are_independent(input_payload):
    """broadening だけ eV、grid は cm^-1 という混在が通ること（ADR-0053）。"""
    payload = copy.deepcopy(input_payload)
    payload["broadening"] = {"sigma": _in_unit(150.0, "eV"), "unit": "eV"}
    mixed = FCEnvelopeInput.from_obj(payload)

    assert mixed.grid.unit == units.CANONICAL_ENERGY_UNIT
    assert mixed.to_broadening().sigma == pytest.approx(150.0, rel=1e-14)
    _assert_same_spectrum(mixed, FCEnvelopeInput.from_obj(input_payload))


def test_the_block_units_default_to_the_canonical_one(input_payload):
    """単位を書いていない既存の入力が、そのまま cm^-1 として読まれること。"""
    parsed = FCEnvelopeInput.from_obj(input_payload)

    assert parsed.broadening.unit == units.CANONICAL_ENERGY_UNIT
    assert parsed.grid.unit == units.CANONICAL_ENERGY_UNIT
    assert parsed.to_broadening().sigma == 150.0
    assert parsed.to_grid().de == 5.0


@pytest.mark.parametrize("block", ["broadening", "grid"])
def test_an_unknown_block_unit_is_rejected(input_payload, block):
    payload = copy.deepcopy(input_payload)
    payload[block] = {**payload[block], "unit": "nm"}
    with pytest.raises(UnsupportedUnitError):
        FCEnvelopeInput.from_obj(payload)
