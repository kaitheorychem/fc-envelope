"""T = 0・単一モードの解析解（合意文書 §3）との一致。

    F(E) = exp(-S) * sum_k S^k / k! * N(E; -k eps, sigma)

サイドバンドは E = -k eps（負側）に立つ。
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from conftest import compute_quietly

from fcenvelope import Broadening, EnergyGrid, VibrationalMode, VibrationalSystem


def poisson_series(
    energy: np.ndarray, huang_rhys: float, frequency: float, sigma: float, k_max: int = 60
) -> np.ndarray:
    total = np.zeros_like(energy)
    for k in range(k_max + 1):
        weight = math.exp(-huang_rhys) * huang_rhys**k / math.factorial(k)
        gaussian = np.exp(-0.5 * ((energy + k * frequency) / sigma) ** 2) / (
            sigma * math.sqrt(2.0 * math.pi)
        )
        total += weight * gaussian
    return total


@pytest.mark.parametrize("huang_rhys", [0.25, 1.0, 3.0])
def test_matches_poisson_series_at_zero_temperature(huang_rhys):
    frequency = 1200.0
    sigma = 120.0
    system = VibrationalSystem(
        [VibrationalMode(frequency=frequency, huang_rhys=huang_rhys)]
    )

    result = compute_quietly(
        system,
        temperature=0.0,
        broadening=Broadening(sigma=sigma),
        grid=EnergyGrid.from_spacing(e_min=-20000.0, e_max=6000.0, de=4.0),
    )
    expected = poisson_series(result.energy, huang_rhys, frequency, sigma)

    assert np.max(np.abs(result.density - expected)) < 1e-9 * np.max(expected)


def test_sidebands_sit_on_the_negative_side():
    """振動量子 k 個生成のサイドバンドは E = -k eps に立つ（符号規約 §3）。"""
    frequency = 1000.0
    grid = EnergyGrid.from_spacing(e_min=-8000.0, e_max=4000.0, de=2.0)
    system = VibrationalSystem([VibrationalMode(frequency=frequency, huang_rhys=1.0)])
    result = compute_quietly(
        system, temperature=0.0, broadening=Broadening(sigma=60.0), grid=grid
    )

    for k in range(4):
        center = -k * frequency
        near = np.abs(result.energy - center) < frequency / 2.0
        peak_energy = result.energy[near][np.argmax(result.density[near])]
        assert peak_energy == pytest.approx(center, abs=grid.de)

    # S = 1 のとき 0-0 と 0-1 のピーク高さは等しく、それ以降は単調に落ちる。
    heights = [
        float(np.max(result.density[np.abs(result.energy + k * frequency) < frequency / 2.0]))
        for k in range(5)
    ]
    assert heights[0] == pytest.approx(heights[1], rel=1e-6)
    assert heights[1] > heights[2] > heights[3] > heights[4]


def test_zero_coupling_gives_a_pure_gaussian():
    """S = 0 なら ZPL のガウシアンそのもの。"""
    sigma = 100.0
    result = compute_quietly(
        VibrationalSystem([VibrationalMode(frequency=800.0, huang_rhys=0.0)]),
        temperature=300.0,
        broadening=Broadening(sigma=sigma),
        grid=EnergyGrid.from_spacing(e_min=-2000.0, e_max=2000.0, de=1.0),
    )

    expected = np.exp(-0.5 * (result.energy / sigma) ** 2) / (sigma * math.sqrt(2.0 * math.pi))
    assert np.max(np.abs(result.density - expected)) < 1e-12
    assert result.system.reorganization_energy == 0.0


def test_hot_band_appears_on_the_positive_side():
    """有限温度では n 項により E > 0 側にもホットバンドが立ち、左右非対称になる。"""
    frequency = 300.0
    shared = {
        "broadening": Broadening(sigma=40.0),
        "grid": EnergyGrid.from_spacing(e_min=-4000.0, e_max=2000.0, de=2.0),
    }
    system = VibrationalSystem([VibrationalMode(frequency=frequency, huang_rhys=0.5)])

    cold = compute_quietly(system, temperature=0.0, **shared)
    hot = compute_quietly(system, temperature=600.0, **shared)

    window = np.abs(cold.energy - frequency) < frequency / 2.0
    assert np.max(hot.density[window]) > 100.0 * np.max(cold.density[window])
