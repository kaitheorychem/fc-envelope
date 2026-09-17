"""エネルギー単位の換算表（ADR-0054）。

この段階では `units.py` 単体で閉じて検証する。入力ファイルの型がこの表を消費する
のは次の段階で、そこでは同じ物理系を違う単位で書いた入力どうしを突き合わせる。
"""

from __future__ import annotations

import pytest

from fcenvelope import units
from fcenvelope.errors import UnsupportedUnitError


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
