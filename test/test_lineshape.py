"""線形状の 2 パラメータ族 (sigma, gamma)（ADR-0034 / ADR-0039）。

ガウス・ローレンツ・Voigt は別の「種類」ではなく、時間領域の減衰因子

    D(tau) = exp(-sigma^2 tau^2 / 2 - gamma |tau|)

の 1 つの族の中の点である。したがって検証も「gamma = 0 で従来と一致する」
「極限で閉じた形に帰着する」「族の全域でモーメント恒等式が保たれる」の 3 本になる。

注意: ADR-0015 の 2 次モーメント恒等式は gamma > 0 では成立しない。ローレンツ分布は
分散を持たないためで、gamma > 0 のテストでは 0 次と 1 次だけを使う。
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from conftest import compute_quietly, conditions, lines_quietly, moments
from scipy.special import voigt_profile

from fcenvelope import Broadening, InvalidInputError, VibrationalMode
from fcenvelope.physics import lineshape_peak

MODES = [
    VibrationalMode(frequency=1200.0, huang_rhys=0.25),
    VibrationalMode(frequency=450.0, huang_rhys=0.64),
]

#: (sigma, gamma)。純ガウス・純ローレンツ・その間の Voigt。
WIDTHS = [(150.0, 0.0), (0.0, 60.0), (120.0, 60.0), (40.0, 150.0)]


# --- 頂点値 ---


@pytest.mark.parametrize("sigma", [1.0, 80.0, 150.0])
def test_peak_reduces_to_the_gaussian_at_zero_gamma(sigma):
    assert lineshape_peak(sigma, 0.0) == pytest.approx(
        1.0 / (sigma * math.sqrt(2.0 * math.pi)), rel=1e-14
    )


@pytest.mark.parametrize("gamma", [1.0, 40.0, 150.0])
def test_peak_reduces_to_the_lorentzian_at_zero_sigma(gamma):
    assert lineshape_peak(0.0, gamma) == pytest.approx(1.0 / (math.pi * gamma), rel=1e-14)


@pytest.mark.parametrize(("sigma", "gamma"), WIDTHS)
def test_peak_matches_the_inverse_transform_of_the_damping_factor(sigma, gamma):
    """頂点値が減衰因子の逆フーリエ変換の E = 0 値に一致する。

        V(0) = (1 / 2pi) int dtau exp(-sigma^2 tau^2 / 2 - gamma |tau|)
             = (1 / pi) int_0^inf dtau exp(...)

    `lineshape_peak` は Faddeeva 関数で閉じた形を与えており、この数値積分とは
    独立な経路になる。
    """
    scale = max(sigma, gamma)
    tau = np.linspace(0.0, 60.0 / scale, 2_000_001)
    integrand = np.exp(-0.5 * sigma**2 * tau**2 - gamma * tau)
    numeric = float(np.trapezoid(integrand, tau)) / math.pi
    assert lineshape_peak(sigma, gamma) == pytest.approx(numeric, rel=1e-9)


@pytest.mark.parametrize(("sigma", "gamma"), WIDTHS)
def test_peak_agrees_with_the_scipy_voigt_profile(sigma, gamma):
    assert lineshape_peak(sigma, gamma) == pytest.approx(
        float(voigt_profile(0.0, sigma, gamma)), rel=1e-12
    )


# --- 検証 ---


def test_a_pure_lorentzian_is_a_valid_broadening():
    assert Broadening(sigma=0.0, gamma=60.0).sigma == 0.0


def test_both_widths_zero_is_rejected():
    with pytest.raises(InvalidInputError):
        Broadening(sigma=0.0, gamma=0.0)


@pytest.mark.parametrize(("sigma", "gamma"), [(-1.0, 60.0), (150.0, -1.0)])
def test_negative_widths_are_rejected(sigma, gamma):
    with pytest.raises(InvalidInputError):
        Broadening(sigma=sigma, gamma=gamma)


# --- エンベロープ ---


def test_zero_gamma_reproduces_the_gaussian_envelope_exactly():
    """回帰: gamma = 0 は段階 2 までの計算と 1 ビットも違わない。"""
    setup = conditions(temperature=300.0, sigma=150.0, e_min=-8000.0, e_max=4000.0, de=4.0)
    result = compute_quietly(MODES, **setup)

    explicit = compute_quietly(
        MODES,
        temperature=setup["temperature"],
        broadening=Broadening(sigma=150.0, gamma=0.0),
        grid=setup["grid"],
    )
    np.testing.assert_array_equal(result.density, explicit.density)


def _wide(sigma: float, gamma: float, half: float) -> dict:
    return conditions(
        temperature=300.0, sigma=sigma, gamma=gamma, e_min=-half, e_max=half, de=2.0
    )


@pytest.mark.parametrize(("sigma", "gamma"), WIDTHS)
def test_zeroth_moment_holds_across_the_family(sigma, gamma):
    """全域グリッドでの ∫F dE = 1 は線形状によらず厳密（ADR-0015 の 0 次モーメント）。"""
    result = compute_quietly(MODES, **_wide(sigma, gamma, 40000.0))
    assert result.diagnostics.total_area == pytest.approx(1.0, abs=1e-12)


@pytest.mark.parametrize(("sigma", "gamma"), WIDTHS)
def test_the_window_captures_everything_only_in_the_limit(sigma, gamma):
    """窓の中の面積は窓を広げるほど 1 に近づく。

    ローレンツ成分の裾は 1/E^2 でしか落ちないので、有限の窓では原理的に拾い切れない。
    その取りこぼしがそのまま `window_captured_fraction` である。
    """
    narrow = compute_quietly(MODES, **_wide(sigma, gamma, 40000.0))
    wide = compute_quietly(MODES, **_wide(sigma, gamma, 200000.0))

    for result in (narrow, wide):
        area, _, _ = moments(result)
        assert area == pytest.approx(result.diagnostics.window_captured_fraction, abs=1e-9)

    assert 1.0 - wide.diagnostics.window_captured_fraction <= (
        1.0 - narrow.diagnostics.window_captured_fraction
    )
    assert wide.diagnostics.window_captured_fraction > 0.999


@pytest.mark.parametrize(("sigma", "gamma"), WIDTHS)
def test_first_moment_approaches_minus_lambda(sigma, gamma):
    """<E> -> -lambda。2 次モーメントはローレンツ成分で発散するので使わない。

    窓の切り落としは <E> にも効く（分布の中心 -lambda が窓の中心からずれている
    ぶん、左右の裾を非対称に落とす）ので、窓を広げるほど -lambda に寄ることを見る。
    """
    expected = -sum(mode.huang_rhys * mode.frequency for mode in MODES)
    _, narrow_mean, _ = moments(compute_quietly(MODES, **_wide(sigma, gamma, 40000.0)))
    _, wide_mean, _ = moments(compute_quietly(MODES, **_wide(sigma, gamma, 200000.0)))

    # 純ガウスではどちらも機械精度で一致するので、単調性は丸め誤差の床を置いて見る。
    floor = 1e-9 * abs(expected)
    assert abs(wide_mean - expected) <= abs(narrow_mean - expected) + floor
    assert wide_mean == pytest.approx(expected, abs=1.0)


@pytest.mark.parametrize(("sigma", "gamma"), WIDTHS)
def test_broadened_lines_reproduce_the_envelope_for_voigt(sigma, gamma):
    """線を線形状で畳んだものがエンベロープに一致する（ADR-0026 を族の全域へ）。

    エンベロープ（FFT）と離散線（漸化式）はほとんど共通コードを持たない独立な
    2 実装であり、線形状の側も `scipy.special.voigt_profile` という第 3 の実装で
    与えている。
    """
    # 窓を広く取る。ローレンツ成分の裾は全域グリッドの端から折り返して戻り
    # （その量が `edge_density_ratio`）、線を畳んだものとのずれの主因になる。
    setup = conditions(
        temperature=300.0, sigma=sigma, gamma=gamma, e_min=-60000.0, e_max=60000.0, de=4.0
    )
    envelope = compute_quietly(MODES, **setup)
    lines = lines_quietly(MODES, temperature=300.0, min_weight=1e-7, max_lines=200000)
    assert lines.diagnostics.beam_truncated is False

    reconstructed = np.zeros_like(envelope.energy)
    for line in lines.lines:
        reconstructed += line.weight * voigt_profile(
            envelope.energy - line.energy, sigma, gamma
        )

    peak = float(np.max(envelope.density))
    residual = float(np.max(np.abs(reconstructed - envelope.density)))
    assert residual / peak < 10.0 * (1.0 - lines.diagnostics.captured_weight) + 1e-6


def test_gamma_widens_the_wings_more_than_sigma():
    """同じ半値幅でもローレンツ成分は裾が重い。族の中の 2 点が区別できている確認。"""
    window = {"e_min": -20000.0, "e_max": 8000.0, "de": 2.0}
    gaussian = compute_quietly(
        MODES, **conditions(temperature=0.0, sigma=150.0, **window)
    )
    voigt = compute_quietly(
        MODES, **conditions(temperature=0.0, sigma=150.0, gamma=150.0, **window)
    )
    far = np.abs(gaussian.energy + 16000.0) < 1000.0
    assert np.max(voigt.density[far]) > 100.0 * np.max(gaussian.density[far])
