"""モーメント恒等式による検証（合意文書 §11）。

    0 次: int F dE = 1
    1 次: <E> = -lambda,  lambda = sum_a S_a eps_a   （温度に依存しない）
    2 次: Var(E) = sum_a S_a eps_a^2 (2 n_a + 1) + sigma^2 （ここにのみ温度が効く）
"""

from __future__ import annotations

import pytest
from conftest import compute_quietly, moments

from fcenvelope import Broadening, EnergyGrid, VibrationalSystem

TEMPERATURES = [0.0, 77.0, 300.0]

BROADENING = Broadening(sigma=150.0)
GRID = EnergyGrid(e_min=-12000.0, e_max=12000.0, de=2.0)


def expected_variance(
    system: VibrationalSystem, temperature: float, sigma: float
) -> float:
    occupations = system.occupations(temperature)
    vibrational = sum(
        mode.huang_rhys * mode.frequency**2 * (2.0 * n_alpha + 1.0)
        for mode, n_alpha in zip(system.modes, occupations, strict=True)
    )
    return float(vibrational + sigma**2)


@pytest.fixture(params=TEMPERATURES, ids=lambda t: f"T={t:g}K")
def temperature(request: pytest.FixtureRequest) -> float:
    return request.param


def _envelope(system: VibrationalSystem, temperature: float):
    return compute_quietly(
        system, temperature=temperature, broadening=BROADENING, grid=GRID
    )


def test_normalization_over_full_grid(multi_mode, temperature):
    """全域グリッドでの面積は離散和として厳密に 1 になる。"""
    result = _envelope(multi_mode, temperature)
    assert result.diagnostics.total_area == pytest.approx(1.0, abs=1e-12)


def test_zeroth_moment(multi_mode, temperature):
    result = _envelope(multi_mode, temperature)
    area, _, _ = moments(result)
    assert area == pytest.approx(1.0, abs=1e-9)


def test_first_moment_is_minus_reorganization_energy(multi_mode, temperature):
    """<E> = -lambda。温度に依存しない。"""
    result = _envelope(multi_mode, temperature)
    _, mean, _ = moments(result)
    expected = -multi_mode.reorganization_energy
    assert result.system.reorganization_energy == pytest.approx(-expected)
    assert mean == pytest.approx(expected, rel=1e-8)


def test_second_moment_carries_the_temperature(multi_mode, temperature):
    """Var(E) にのみ温度が効く。"""
    _, _, variance = moments(_envelope(multi_mode, temperature))
    assert variance == pytest.approx(
        expected_variance(multi_mode, temperature, BROADENING.sigma), rel=1e-8
    )


def test_first_moment_is_temperature_independent(multi_mode):
    """1 次モーメントは温度で動かない（2 次は動く）。"""
    means = []
    variances = []
    for temperature in TEMPERATURES:
        _, mean, variance = moments(_envelope(multi_mode, temperature))
        means.append(mean)
        variances.append(variance)

    assert means[0] == pytest.approx(means[1], rel=1e-8)
    assert means[0] == pytest.approx(means[2], rel=1e-8)
    assert variances[0] < variances[1] < variances[2]


def test_single_mode_moments(single_mode, temperature):
    area, mean, variance = moments(_envelope(single_mode, temperature))
    assert area == pytest.approx(1.0, abs=1e-9)
    assert mean == pytest.approx(-single_mode.reorganization_energy, rel=1e-8)
    assert variance == pytest.approx(
        expected_variance(single_mode, temperature, BROADENING.sigma), rel=1e-8
    )
