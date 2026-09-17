"""振電相互作用の流儀（g / delta / huang_rhys）の正準化。"""

from __future__ import annotations

import math

import numpy as np
import pytest
from conftest import compute_quietly

from fcenvelope import (
    CouplingConvention,
    FCEnvelopeInput,
    VibrationalMode,
    VibrationalSystem,
    units,
)
from fcenvelope.errors import InvalidInputError, UnsupportedUnitError


def _payload(convention: str, coupling: float) -> dict:
    return {
        "schema_version": 2,
        "frequency_unit": "cm^-1",
        "coupling_convention": convention,
        "modes": [{"frequency": 1200.0, "coupling": coupling}],
        "temperature": 300.0,
        "broadening": {"sigma": 150.0},
        "grid": {"e_min": -4000.0, "e_max": 1000.0, "de": 5.0},
    }


def _envelope(parsed: FCEnvelopeInput):
    return compute_quietly(
        parsed.to_system(),
        temperature=parsed.to_temperature(),
        broadening=parsed.to_broadening(),
        grid=parsed.to_grid(),
    )


def test_registry_conversions():
    assert units.G.to_huang_rhys(0.5, 1200.0) == 0.25
    assert units.DELTA.to_huang_rhys(1.0, 1200.0) == 0.5
    assert units.HUANG_RHYS.to_huang_rhys(0.25, 1200.0) == 0.25


def test_the_dimensionless_conventions_ignore_the_frequency():
    """g / Delta / huang_rhys は omega を要しない（`docs/theory/vcc.md` の表）。"""
    for convention in (units.G, units.DELTA, units.HUANG_RHYS):
        assert convention.is_dimensionless
        assert convention.to_huang_rhys(0.5, 1200.0) == convention.to_huang_rhys(
            0.5, 300.0
        )


def test_a_dimensionless_convention_rejects_a_coupling_unit():
    with pytest.raises(InvalidInputError, match="dimensionless"):
        units.G.check_coupling_unit("cm^-1")
    assert units.G.check_coupling_unit(None) is None


def test_the_convention_type_can_express_a_dimensioned_convention():
    """V と lambda を足せる構造であることを確かめる（ADR-0033）。

    登録はしない——このリファクタリングの目的は足せる構造にすることであって、
    流儀を増やすことではない。
    """
    reorganization = CouplingConvention(
        name="lambda", energy_power=1.0, converter=lambda value, freq: value / freq
    )
    assert not reorganization.is_dimensionless
    assert reorganization.to_huang_rhys(300.0, 1200.0) == 0.25
    with pytest.raises(UnsupportedUnitError, match="carries units"):
        reorganization.check_coupling_unit(None)

    vibronic = CouplingConvention(
        name="vcc",
        energy_power=1.5,
        converter=lambda value, freq: value**2 / (2.0 * freq**3),
    )
    assert not vibronic.is_dimensionless
    assert vibronic.to_huang_rhys(math.sqrt(2.0 * 1200.0**3 * 0.25), 1200.0) == (
        pytest.approx(0.25)
    )


def test_an_unknown_name_names_the_known_conventions():
    with pytest.raises(InvalidInputError, match="huang_rhys"):
        units.coupling_convention("Delta")


def test_g_and_huang_rhys_agree():
    """g = 0.5 と huang_rhys = 0.25 は同一の結果を与える。"""
    from_g = FCEnvelopeInput.from_obj(_payload("g", 0.5))
    from_s = FCEnvelopeInput.from_obj(_payload("huang_rhys", 0.25))

    expected = VibrationalSystem([VibrationalMode(frequency=1200.0, huang_rhys=0.25)])
    assert from_g.to_system() == from_s.to_system() == expected

    result_g = _envelope(from_g)
    result_s = _envelope(from_s)

    np.testing.assert_array_equal(result_g.density, result_s.density)
    assert result_g.system.reorganization_energy == result_s.system.reorganization_energy


def test_delta_and_g_agree():
    """Delta = sqrt(2)*g は同じ S を与える（`docs/theory/vcc.md` の表）。"""
    g = 0.5
    from_g = FCEnvelopeInput.from_obj(_payload("g", g))
    from_delta = FCEnvelopeInput.from_obj(_payload("delta", math.sqrt(2.0) * g))

    assert from_delta.to_system().modes[0].huang_rhys == pytest.approx(
        from_g.to_system().modes[0].huang_rhys
    )
    # sqrt(2) を往復するぶん S が 1 ULP ずれるので、判定は最大値で正規化した
    # 相対誤差にする（ADR-0042）。要素ごとの相対誤差は裾がほぼ 0 なので使えない。
    from_delta_density = _envelope(from_delta).density
    from_g_density = _envelope(from_g).density
    np.testing.assert_allclose(
        from_delta_density,
        from_g_density,
        rtol=0.0,
        atol=1e-12 * float(from_g_density.max()),
    )


def test_delta_is_dimensionless():
    """Delta は無次元なので coupling の単位を添えるのは誤り（ADR-0055）。"""
    assert units.DELTA.is_dimensionless
    assert units.DELTA.check_coupling_unit(None) is None
    with pytest.raises(InvalidInputError, match="dimensionless"):
        units.DELTA.check_coupling_unit("eV")


def test_default_convention_is_g():
    payload = _payload("g", 0.5)
    del payload["coupling_convention"]
    parsed = FCEnvelopeInput.from_obj(payload)
    assert parsed.convention is units.G
    assert parsed.to_system().modes[0].huang_rhys == 0.25


@pytest.mark.parametrize("convention", ["Delta", "reorganization", ""])
def test_unknown_convention_is_rejected(convention):
    with pytest.raises(InvalidInputError):
        FCEnvelopeInput.from_obj(_payload(convention, 0.5))
