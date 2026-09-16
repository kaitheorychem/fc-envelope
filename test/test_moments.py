"""モーメント恒等式による検証（合意文書 §11）。

    0 次: int F dE = 1
    1 次: <E> = -lambda,  lambda = sum_a S_a eps_a   （温度に依存しない）
    2 次: Var(E) = sum_a S_a eps_a^2 (2 n_a + 1) + sigma^2 （ここにのみ温度が効く）
"""

from __future__ import annotations

import numpy as np
import pytest
from conftest import compute_quietly, conditions, moments

from fcenvelope import VibrationalMode
from fcenvelope.physics import occupation_numbers

TEMPERATURES = [0.0, 77.0, 300.0]


def expected_variance(modes: list[VibrationalMode], temperature: float, sigma: float) -> float:
    occupations = occupation_numbers(
        np.array([mode.frequency for mode in modes]), temperature
    )
    vibrational = sum(
        mode.huang_rhys * mode.frequency**2 * (2.0 * n_alpha + 1.0)
        for mode, n_alpha in zip(modes, occupations, strict=True)
    )
    return float(vibrational + sigma**2)


@pytest.fixture(params=TEMPERATURES, ids=lambda t: f"T={t:g}K")
def temperature(request: pytest.FixtureRequest) -> float:
    return request.param


SIGMA = 150.0


def _conditions(temperature: float) -> dict:
    return conditions(
        temperature=temperature, sigma=SIGMA, e_min=-12000.0, e_max=12000.0, de=2.0
    )


def test_normalization_over_full_grid(multi_mode, temperature):
    """全域グリッドでの面積は離散和として厳密に 1 になる。"""
    result = compute_quietly(multi_mode, **_conditions(temperature))
    assert result.diagnostics.total_area == pytest.approx(1.0, abs=1e-12)


def test_zeroth_moment(multi_mode, temperature):
    result = compute_quietly(multi_mode, **_conditions(temperature))
    area, _, _ = moments(result)
    assert area == pytest.approx(1.0, abs=1e-9)


def test_first_moment_is_minus_reorganization_energy(multi_mode, temperature):
    """<E> = -lambda。温度に依存しない。"""
    result = compute_quietly(multi_mode, **_conditions(temperature))
    _, mean, _ = moments(result)
    expected = -sum(mode.huang_rhys * mode.frequency for mode in multi_mode)
    assert result.reorganization_energy == pytest.approx(-expected)
    assert mean == pytest.approx(expected, rel=1e-8)


def test_second_moment_carries_the_temperature(multi_mode, temperature):
    """Var(E) にのみ温度が効く。"""
    result = compute_quietly(multi_mode, **_conditions(temperature))
    _, _, variance = moments(result)
    assert variance == pytest.approx(
        expected_variance(multi_mode, temperature, SIGMA), rel=1e-8
    )


def test_first_moment_is_temperature_independent(multi_mode):
    """1 次モーメントは温度で動かない（2 次は動く）。"""
    means = []
    variances = []
    for temperature in TEMPERATURES:
        _, mean, variance = moments(compute_quietly(multi_mode, **_conditions(temperature)))
        means.append(mean)
        variances.append(variance)

    assert means[0] == pytest.approx(means[1], rel=1e-8)
    assert means[0] == pytest.approx(means[2], rel=1e-8)
    assert variances[0] < variances[1] < variances[2]


def test_single_mode_moments(single_mode, temperature):
    result = compute_quietly(single_mode, **_conditions(temperature))
    area, mean, variance = moments(result)
    assert area == pytest.approx(1.0, abs=1e-9)
    assert mean == pytest.approx(-single_mode[0].huang_rhys * single_mode[0].frequency, rel=1e-8)
    assert variance == pytest.approx(
        expected_variance(single_mode, temperature, SIGMA), rel=1e-8
    )
