"""振電相互作用の流儀（g / delta / huang_rhys / lambda）の正準化。"""

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


def _payload(convention: str, coupling: float, **extra: object) -> dict:
    return {
        "schema_version": 3,
        "frequency_unit": "cm^-1",
        "coupling_convention": convention,
        **extra,
        "modes": [{"frequency": 1200.0, "coupling": coupling}],
        "temperature": 300.0,
        "broadening": {"sigma": 150.0},
        "grid": {"e_min": -4000.0, "e_max": 1000.0, "points": {"de": 5.0}},
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


def test_the_convention_type_can_express_v():
    """V はまだ登録しないが、型としては表現できる（ADR-0055）。

    相手プログラムが V をどの単位で出すかが分かっていないので登録は保留する。
    次元が単一のべき指数で表せるかどうかも、そのときに決まる。
    """
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


def test_lambda_and_huang_rhys_agree():
    """S = lambda / eps。lambda を eV で書いても同じ系になる（ADR-0055）。"""
    huang_rhys = 0.25
    frequency = 1200.0
    in_ev = huang_rhys * frequency / units.energy_conversion_factor("eV")

    from_s = FCEnvelopeInput.from_obj(_payload("huang_rhys", huang_rhys))
    from_lambda = FCEnvelopeInput.from_obj(
        _payload("lambda", in_ev, coupling_unit="eV")
    )

    assert from_lambda.to_system().modes[0].huang_rhys == pytest.approx(
        huang_rhys, rel=1e-14
    )
    expected = _envelope(from_s).density
    np.testing.assert_allclose(
        _envelope(from_lambda).density,
        expected,
        rtol=0.0,
        atol=1e-12 * float(expected.max()),
    )


def test_lambda_in_the_canonical_unit_is_the_reorganization_energy():
    """cm^-1 で書いた lambda が、そのまま系の再配列エネルギーになること。"""
    parsed = FCEnvelopeInput.from_obj(
        _payload("lambda", 300.0, coupling_unit="cm^-1")
    )
    assert parsed.to_system().reorganization_energy == pytest.approx(300.0, rel=1e-14)


def test_a_dimensioned_convention_needs_a_coupling_unit():
    """有次元の流儀で単位を省くと拒否される（check_coupling_unit の一方の枝）。"""
    with pytest.raises(UnsupportedUnitError, match="carries units"):
        FCEnvelopeInput.from_obj(_payload("lambda", 300.0)).to_system()


@pytest.mark.parametrize("convention", ["g", "delta", "huang_rhys"])
def test_a_dimensionless_convention_refuses_a_coupling_unit(convention):
    """無次元の流儀に単位を添えると拒否される（もう一方の枝）。"""
    payload = _payload(convention, 0.5, coupling_unit="eV")
    with pytest.raises(InvalidInputError, match="dimensionless"):
        FCEnvelopeInput.from_obj(payload).to_system()


def test_an_unknown_coupling_unit_is_rejected():
    with pytest.raises(UnsupportedUnitError, match="unsupported energy unit"):
        FCEnvelopeInput.from_obj(_payload("lambda", 300.0, coupling_unit="nm"))


def test_the_coupling_unit_is_omitted_by_default():
    """単位を書いていない既存の入力は、無次元の流儀として読まれ続ける。"""
    parsed = FCEnvelopeInput.from_obj(_payload("g", 0.5))
    assert parsed.coupling_unit is None
    assert parsed.to_system().modes[0].huang_rhys == 0.25
