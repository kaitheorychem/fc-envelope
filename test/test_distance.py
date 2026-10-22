"""2 つのエンベロープの距離 `envelope_distance`（ADR-0088）。

S = 0 の系のエンベロープは ZPL を線形状で広げたガウシアンそのものなので、幅の違う 2 つの
ガウシアンの L1・L2・L∞ を解析的に書いて比べられる。
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pytest
from conftest import compute_quietly

from fcenvelope import (
    Broadening,
    EnergyGrid,
    InvalidInputError,
    VibrationalMode,
    VibrationalSystem,
    envelope_distance,
    load_envelope,
    save_envelope,
)

NO_COUPLING = VibrationalSystem([VibrationalMode(frequency=1000.0, huang_rhys=0.0)])
SYSTEM = VibrationalSystem(
    [
        VibrationalMode(frequency=300.0, huang_rhys=0.4),
        VibrationalMode(frequency=1200.0, huang_rhys=0.25),
    ]
)
GRID = EnergyGrid.from_spacing(e_min=-4000.0, e_max=1000.0, de=5.0)
SIGMA_1, SIGMA_2 = 100.0, 160.0


def _gaussian(sigma: float, grid: EnergyGrid = GRID):
    return compute_quietly(
        NO_COUPLING, temperature=0.0, broadening=Broadening(sigma=sigma), grid=grid
    )


def _envelope(temperature: float = 300.0, *, system=SYSTEM, grid=GRID, sigma=150.0):
    return compute_quietly(
        system, temperature=temperature, broadening=Broadening(sigma=sigma), grid=grid
    )


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _analytic_l1(s1: float, s2: float) -> float:
    """同じ中心で幅 s1 < s2 のガウシアン。|x| < x0 で狭いほうが上に出る。"""
    x0 = math.sqrt(2.0 * s1**2 * s2**2 * math.log(s2 / s1) / (s2**2 - s1**2))
    return 4.0 * (_phi(x0 / s1) - _phi(x0 / s2))


def _analytic_l2(s1: float, s2: float) -> float:
    squared = (
        1.0 / (2.0 * math.sqrt(math.pi) * s1)
        + 1.0 / (2.0 * math.sqrt(math.pi) * s2)
        - 2.0 / math.sqrt(2.0 * math.pi * (s1**2 + s2**2))
    )
    return math.sqrt(squared)


def _analytic_linf(s1: float, s2: float) -> float:
    return (1.0 / s1 - 1.0 / s2) / math.sqrt(2.0 * math.pi)


#: L1 は被積分関数 |F1 - F2| が交点で折れるので、長方形則の誤差が ΔE の 1 次で残る。
#: 滑らかな L2 と、和を取らない L∞ はもっと近い。
@pytest.mark.parametrize(
    ("norm", "expected", "rel"),
    [
        ("L1", _analytic_l1(SIGMA_1, SIGMA_2), 1e-4),
        ("L2", _analytic_l2(SIGMA_1, SIGMA_2), 1e-6),
        ("Linf", _analytic_linf(SIGMA_1, SIGMA_2), 1e-6),
    ],
)
def test_two_gaussians_match_the_analytic_norms(norm, expected, rel):
    distance = envelope_distance(_gaussian(SIGMA_1), _gaussian(SIGMA_2), norm=norm)

    assert distance == pytest.approx(expected, rel=rel)


@pytest.mark.parametrize("norm", ["L1", "L2", "Linf"])
def test_an_envelope_is_at_distance_zero_from_itself(norm):
    result = _envelope()

    assert envelope_distance(result, result, norm=norm) == 0.0


@pytest.mark.parametrize("norm", ["L1", "L2", "Linf"])
def test_the_distance_is_symmetric(norm):
    a, b = _envelope(300.0), _envelope(77.0)

    assert envelope_distance(a, b, norm=norm) == envelope_distance(b, a, norm=norm)


def test_the_distance_does_not_depend_on_the_spacing():
    """ΔE を掛けた連続版なので、グリッドを細かくしても値は変わらない。"""
    coarse = EnergyGrid.from_spacing(e_min=-4000.0, e_max=1000.0, de=5.0)
    fine = EnergyGrid.from_spacing(e_min=-4000.0, e_max=1000.0, de=2.5)

    for norm in ("L1", "L2"):
        on_coarse = envelope_distance(
            _envelope(300.0, grid=coarse), _envelope(77.0, grid=coarse), norm=norm
        )
        on_fine = envelope_distance(
            _envelope(300.0, grid=fine), _envelope(77.0, grid=fine), norm=norm
        )
        assert on_fine == pytest.approx(on_coarse, rel=1e-4)


def test_separated_envelopes_are_at_l1_distance_two():
    """重ならない 2 つの確率密度の L1 は 2 になる。

    結合のある側は ZPL に重み e^-S だけを残し、残りは σ の 15 倍離れたサイドバンドに
    立つ。重なるのは ZPL の分だけなので、L1 = 2 (1 - e^-S) になる。
    """
    grid = EnergyGrid.from_spacing(e_min=-24000.0, e_max=1000.0, de=10.0)
    coupled = VibrationalSystem([VibrationalMode(frequency=1500.0, huang_rhys=4.0)])

    distance = envelope_distance(
        _envelope(0.0, system=NO_COUPLING, grid=grid, sigma=100.0),
        _envelope(0.0, system=coupled, grid=grid, sigma=100.0),
        norm="L1",
    )

    assert distance == pytest.approx(2.0 * (1.0 - math.exp(-4.0)), abs=1e-5)


def test_the_window_is_not_renormalized():
    """窓の外へ逃げた面積の差は距離に残る。

    窓よりずっと広い 2 つのガウシアンは、窓の中ではどちらもほぼ平らである。窓の中で
    規格化し直せばほとんど同じになるが、窓に残った面積は幅に反比例して違う。狭いほうが
    窓の中のどこでも上にあるので、L1 は窓に残った面積の差そのものになる。
    """
    grid = EnergyGrid(e_min=-50.0, e_max=50.0, de=1.0, n_fft=16384)
    narrow, wide = _gaussian(500.0, grid), _gaussian(1000.0, grid)
    kept = [float(np.sum(r.density) * grid.de) for r in (narrow, wide)]

    distance = envelope_distance(narrow, wide, norm="L1")

    assert distance == pytest.approx(kept[0] - kept[1], rel=1e-9)
    renormalized = (
        np.sum(np.abs(narrow.density / kept[0] - wide.density / kept[1])) * grid.de
    )
    assert distance > 10.0 * renormalized


def test_only_n_fft_may_differ():
    """ΔE と窓が同じなら出力の点は同じなので、全域グリッドの点数が違っても比べられる。"""
    small = EnergyGrid(e_min=-4000.0, e_max=1000.0, de=5.0, n_fft=2048)
    large = EnergyGrid(e_min=-4000.0, e_max=1000.0, de=5.0, n_fft=4096)

    distance = envelope_distance(
        _envelope(grid=small), _envelope(grid=large), norm="L1"
    )

    assert distance == pytest.approx(0.0, abs=1e-9)


def test_a_different_spacing_is_refused():
    other = EnergyGrid.from_spacing(e_min=-4000.0, e_max=1000.0, de=2.5)

    with pytest.raises(InvalidInputError, match="spacings"):
        envelope_distance(_envelope(), _envelope(grid=other), norm="L1")


def test_a_different_window_is_refused():
    other = EnergyGrid.from_spacing(e_min=-3000.0, e_max=1000.0, de=5.0)

    with pytest.raises(InvalidInputError, match="windows"):
        envelope_distance(_envelope(), _envelope(grid=other), norm="L1")


@pytest.mark.parametrize("norm", [1, 2, math.inf, "l1", "L3", "inf", None])
def test_an_unknown_norm_is_refused(norm):
    result = _envelope()

    with pytest.raises(InvalidInputError, match="norm"):
        envelope_distance(result, result, norm=norm)


def test_different_conditions_are_compared_without_a_warning():
    """系・温度・線形状が違うのは比べる目的そのものなので、警告しない。"""
    a = _envelope(300.0, sigma=150.0)
    b = _envelope(0.0, system=SYSTEM.scale_huang_rhys(1.5), sigma=120.0)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert envelope_distance(a, b, norm="L2") > 0.0


def test_a_reloaded_result_compares_like_the_original(tmp_path):
    a, b = _envelope(300.0), _envelope(77.0)
    path = tmp_path / "result.json"
    save_envelope(a, path)

    reloaded = load_envelope(path)

    for norm in ("L1", "L2", "Linf"):
        assert envelope_distance(reloaded, b, norm=norm) == pytest.approx(
            envelope_distance(a, b, norm=norm), rel=1e-12
        )
    np.testing.assert_allclose(reloaded.energy, a.energy)
