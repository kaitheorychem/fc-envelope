"""振電相互作用の流儀の正準化（ADR-0033、`docs/theory/vcc.md`）。

5 つの流儀はすべて同じ物理を指す。したがって検証は「どの流儀で書いても同じ S に
なる」「無次元かどうかを流儀自身が知っている」の 2 本になる。
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from conftest import compute_quietly

from fcenvelope import COUPLING_CONVENTIONS, CouplingConvention, FCEnvelopeInput, VibrationalMode
from fcenvelope.errors import InvalidInputError

FREQUENCY = 1200.0
HUANG_RHYS = 0.25

#: 同じ S = 0.25・omega = 1200 cm^-1 を 5 通りに書いたもの（`docs/theory/vcc.md`）。
EQUIVALENT_COUPLINGS = {
    "g": math.sqrt(HUANG_RHYS),
    "delta": math.sqrt(2.0 * HUANG_RHYS),
    "huang_rhys": HUANG_RHYS,
    "vcc": math.sqrt(2.0 * HUANG_RHYS * FREQUENCY**3),
    "lambda": HUANG_RHYS * FREQUENCY,
}


def _payload(convention: str, coupling: float) -> dict:
    return {
        "schema_version": 2,
        "frequency_unit": "cm^-1",
        "coupling_convention": convention,
        "modes": [{"frequency": FREQUENCY, "coupling": coupling}],
        "temperature": 300.0,
        "broadening": {"sigma": 150.0},
        "grid": {"e_min": -4000.0, "e_max": 1000.0, "de": 5.0},
    }


def _envelope(parsed):
    return compute_quietly(
        parsed.to_modes(),
        temperature=parsed.temperature,
        broadening=parsed.broadening,
        grid=parsed.grid,
    )


# --- 流儀オブジェクトそのもの ---


@pytest.mark.parametrize("name", sorted(EQUIVALENT_COUPLINGS))
def test_every_convention_maps_to_the_same_huang_rhys(name):
    convention = COUPLING_CONVENTIONS[name]
    assert convention.to_huang_rhys(
        EQUIVALENT_COUPLINGS[name], FREQUENCY
    ) == pytest.approx(HUANG_RHYS, rel=1e-12)


@pytest.mark.parametrize(
    ("name", "unit"),
    [
        ("g", None),
        ("delta", None),
        ("huang_rhys", None),
        ("vcc", "(cm^-1)^3/2"),
        ("lambda", "cm^-1"),
    ],
)
def test_each_convention_knows_whether_it_carries_a_unit(name, unit):
    """関数表では表現できなかった情報を型が持っている（ADR-0033）。"""
    convention = COUPLING_CONVENTIONS[name]
    assert convention.coupling_unit() == unit
    assert convention.is_dimensionless == (unit is None)


@pytest.mark.parametrize("name", ["vcc", "lambda"])
def test_dimensioned_conventions_depend_on_the_frequency(name):
    """V と lambda は omega と組でしか S に変換できない。"""
    convention = COUPLING_CONVENTIONS[name]
    coupling = EQUIVALENT_COUPLINGS[name]
    assert convention.to_huang_rhys(coupling, FREQUENCY) != convention.to_huang_rhys(
        coupling, 2.0 * FREQUENCY
    )


@pytest.mark.parametrize("name", ["g", "delta", "huang_rhys"])
def test_dimensionless_conventions_ignore_the_frequency(name):
    convention = COUPLING_CONVENTIONS[name]
    coupling = EQUIVALENT_COUPLINGS[name]
    assert convention.to_huang_rhys(coupling, FREQUENCY) == convention.to_huang_rhys(
        coupling, 2.0 * FREQUENCY
    )


def test_the_registry_is_keyed_by_the_name_written_in_the_input():
    assert set(COUPLING_CONVENTIONS) == set(EQUIVALENT_COUPLINGS)
    for name, convention in COUPLING_CONVENTIONS.items():
        assert convention.key == name
    assert COUPLING_CONVENTIONS["g"] is CouplingConvention.G


# --- 入力ファイルを通した経路 ---


@pytest.mark.parametrize("name", sorted(EQUIVALENT_COUPLINGS))
def test_every_convention_parses_to_the_same_mode(name):
    parsed = FCEnvelopeInput.from_obj(_payload(name, EQUIVALENT_COUPLINGS[name]))
    (mode,) = parsed.to_modes()
    assert mode.frequency == FREQUENCY
    assert mode.huang_rhys == pytest.approx(HUANG_RHYS, rel=1e-12)


def test_g_and_huang_rhys_agree():
    """g = 0.5 と huang_rhys = 0.25 は同一の結果を与える。"""
    from_g = FCEnvelopeInput.from_obj(_payload("g", 0.5))
    from_s = FCEnvelopeInput.from_obj(_payload("huang_rhys", 0.25))

    assert from_g.to_modes() == from_s.to_modes() == [
        VibrationalMode(frequency=FREQUENCY, huang_rhys=HUANG_RHYS)
    ]

    np.testing.assert_array_equal(_envelope(from_g).density, _envelope(from_s).density)


def test_default_convention_is_g():
    payload = _payload("g", 0.5)
    del payload["coupling_convention"]
    parsed = FCEnvelopeInput.from_obj(payload)
    assert parsed.coupling_convention is CouplingConvention.G
    assert parsed.to_modes()[0].huang_rhys == 0.25


def test_the_input_reports_the_unit_of_its_coupling():
    assert FCEnvelopeInput.from_obj(_payload("g", 0.5)).coupling_unit is None
    assert (
        FCEnvelopeInput.from_obj(_payload("lambda", 300.0)).coupling_unit == "cm^-1"
    )


@pytest.mark.parametrize("convention", ["Delta", "reorganization", "", "G", "huang-rhys"])
def test_unknown_convention_is_rejected(convention):
    with pytest.raises(InvalidInputError):
        FCEnvelopeInput.from_obj(_payload(convention, 0.5))
