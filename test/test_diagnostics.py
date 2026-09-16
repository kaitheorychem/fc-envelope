"""数値品質の診断値と警告（合意文書 §5, §7）。"""

from __future__ import annotations

import warnings

import numpy as np
import pytest
from conftest import compute_quietly, conditions

from fcenvelope import EnergyGrid, NumericalQualityWarning, VibrationalMode, compute_envelope
from fcenvelope.envelope import build_grids
from fcenvelope.physics import K_B_CM, occupation_numbers

MODES = [VibrationalMode(frequency=1200.0, huang_rhys=0.5)]


def _matching(result, needle: str) -> list[str]:
    return [message for message in result.diagnostics.messages if needle in message]


def test_grid_is_power_of_two_and_contains_the_zpl():
    grid = EnergyGrid(e_min=-4000.0, e_max=1000.0, de=5.0)
    energy, tau, n_fft, d_tau = build_grids(grid)

    assert n_fft & (n_fft - 1) == 0
    assert n_fft >= np.ceil(2 * 4000.0 / 5.0)
    assert energy.size == tau.size == n_fft
    assert 0.0 in energy
    assert d_tau == pytest.approx(2.0 * np.pi / (n_fft * grid.de))
    # FFT 標準順序: 0, 1, ..., N/2-1, -N/2, ..., -1
    assert energy[0] == 0.0
    assert energy[1] == grid.de
    assert energy[n_fft // 2] == -(n_fft // 2) * grid.de


def test_output_grid_spacing_is_exactly_de():
    setup = conditions(temperature=300.0, sigma=150.0, e_min=-4000.0, e_max=1000.0, de=5.0)
    result = compute_quietly(MODES, **setup)
    grid = setup["grid"]
    spacing = np.diff(result.energy)
    assert np.allclose(spacing, grid.de, rtol=0.0, atol=1e-9)
    assert np.min(np.abs(result.energy)) == 0.0
    assert result.energy[0] >= grid.e_min
    assert result.energy[-1] <= grid.e_max


def test_diagnostics_of_a_healthy_calculation():
    setup = conditions(temperature=300.0, sigma=150.0, e_min=-12000.0, e_max=12000.0, de=2.0)
    result = compute_quietly(MODES, **setup)
    diagnostics = result.diagnostics

    assert diagnostics.messages == ()
    assert diagnostics.total_area == pytest.approx(1.0, abs=1e-12)
    assert diagnostics.window_captured_fraction > 0.999
    assert diagnostics.edge_density_ratio < 1e-4
    assert diagnostics.max_imaginary_ratio < 1e-8
    assert diagnostics.tau_max == pytest.approx(np.pi / setup["grid"].de)
    assert diagnostics.sigma_tau_max == pytest.approx(
        setup["broadening"].sigma * diagnostics.tau_max
    )


def test_coarse_de_warns_about_truncation():
    """de が sigma に対して粗いと tau 窓が短く、打ち切りリンギングが起きる。"""
    setup = conditions(temperature=300.0, sigma=10.0, e_min=-2000.0, e_max=2000.0, de=20.0)
    with pytest.warns(NumericalQualityWarning, match="sigma\\*tau_max"):
        result = compute_envelope(MODES, **setup)

    assert result.diagnostics.sigma_tau_max < 6.0
    assert _matching(result, "sigma*tau_max")


def test_narrow_window_raises_the_edge_density_ratio():
    """E 範囲が狭いとスペクトル重みが端に届き、エイリアシングの指標が上がる。"""
    wide = conditions(temperature=300.0, sigma=150.0, e_min=-12000.0, e_max=12000.0, de=5.0)
    narrow = conditions(temperature=300.0, sigma=150.0, e_min=-1500.0, e_max=1500.0, de=5.0)

    wide_result = compute_quietly(MODES, **wide)
    with pytest.warns(NumericalQualityWarning, match="edge_density_ratio"):
        narrow_result = compute_envelope(MODES, **narrow)

    assert narrow_result.diagnostics.edge_density_ratio > 1e-4
    assert narrow_result.diagnostics.edge_density_ratio > wide_result.diagnostics.edge_density_ratio


def test_narrow_window_warns_about_captured_fraction():
    setup = conditions(temperature=300.0, sigma=150.0, e_min=-200.0, e_max=200.0, de=5.0)
    with pytest.warns(NumericalQualityWarning, match="window_captured_fraction"):
        result = compute_envelope(
            [VibrationalMode(frequency=1200.0, huang_rhys=2.0)], **setup
        )

    assert result.diagnostics.window_captured_fraction < 0.99


def test_aliasing_does_not_disturb_the_total_area():
    """エイリアシングでは重みが畳み込まれて戻るため、面積は 1 のまま（§7 の注記）。"""
    setup = conditions(temperature=300.0, sigma=150.0, e_min=-1000.0, e_max=1000.0, de=5.0)
    result = compute_quietly([VibrationalMode(frequency=1200.0, huang_rhys=2.0)], **setup)
    assert result.diagnostics.total_area == pytest.approx(1.0, abs=1e-12)
    assert result.diagnostics.edge_density_ratio > 1e-4


def test_no_warning_is_emitted_for_a_healthy_calculation():
    setup = conditions(temperature=300.0, sigma=150.0, e_min=-12000.0, e_max=12000.0, de=2.0)
    with warnings.catch_warnings():
        warnings.simplefilter("error", NumericalQualityWarning)
        compute_envelope(MODES, **setup)


def test_occupation_numbers_at_zero_temperature():
    frequencies = np.array([100.0, 1200.0])
    assert np.all(occupation_numbers(frequencies, 0.0) == 0.0)


def test_occupation_numbers_do_not_overflow():
    """eps / kT が大きい領域は expm1 -> inf を経て n = 0 に畳まれる。"""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        occupations = occupation_numbers(np.array([1e5, 1e6]), 1e-3)
    assert np.all(occupations == 0.0)
    assert np.all(np.isfinite(occupations))


def test_occupation_numbers_classical_limit():
    """eps << kT では n -> kT / eps。"""
    temperature = 300.0
    frequency = 1e-3
    n_alpha = occupation_numbers(np.array([frequency]), temperature)[0]
    assert n_alpha == pytest.approx(K_B_CM * temperature / frequency, rel=1e-5)


def test_boltzmann_constant_value():
    """k_B は約 0.695 cm^-1/K。"""
    assert K_B_CM == pytest.approx(0.6950348, rel=1e-6)


def test_density_is_real_and_finite():
    setup = conditions(temperature=300.0, sigma=150.0, e_min=-8000.0, e_max=4000.0, de=4.0)
    result = compute_quietly(MODES, **setup)
    assert result.density.dtype == np.float64
    assert np.all(np.isfinite(result.density))
    assert result.diagnostics.max_imaginary_ratio < 1e-12
