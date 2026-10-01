"""系の S を一様に倍にする `VibrationalSystem.scale_huang_rhys`（ADR-0087）。"""

from __future__ import annotations

import math

import numpy as np
import pytest
from conftest import compute_quietly, moments

from fcenvelope import (
    Broadening,
    EnergyGrid,
    InvalidInputError,
    VibrationalMode,
    VibrationalSystem,
)

SYSTEM = VibrationalSystem(
    [
        VibrationalMode(frequency=300.0, huang_rhys=0.4),
        VibrationalMode(frequency=1200.0, huang_rhys=0.25),
        VibrationalMode(frequency=1600.0, huang_rhys=0.0),
    ]
)


@pytest.mark.parametrize("factor", [0.0, 0.5, 1.0, 2.5])
def test_scales_every_huang_rhys_and_keeps_frequencies(factor):
    scaled = SYSTEM.scale_huang_rhys(factor)

    np.testing.assert_array_equal(scaled.frequencies, SYSTEM.frequencies)
    np.testing.assert_allclose(scaled.huang_rhys, SYSTEM.huang_rhys * factor)
    assert scaled.reorganization_energy == pytest.approx(
        SYSTEM.reorganization_energy * factor
    )


def test_returns_a_new_system_and_leaves_the_original_alone():
    before = SYSTEM.huang_rhys.copy()

    scaled = SYSTEM.scale_huang_rhys(2.0)

    assert scaled is not SYSTEM
    np.testing.assert_array_equal(SYSTEM.huang_rhys, before)


def test_factor_one_gives_an_equal_system():
    assert SYSTEM.scale_huang_rhys(1.0) == SYSTEM


def test_scaling_g_by_c_is_a_factor_of_c_squared():
    """S = g^2 なので、g を c 倍した入力と S を c^2 倍した系は一致する。"""
    g, c = 0.6, 1.3
    original = VibrationalSystem([VibrationalMode(frequency=500.0, huang_rhys=g**2)])
    from_g = VibrationalSystem(
        [VibrationalMode(frequency=500.0, huang_rhys=(c * g) ** 2)]
    )

    assert original.scale_huang_rhys(c**2).huang_rhys == pytest.approx(
        from_g.huang_rhys
    )


@pytest.mark.parametrize("factor", [-1.0, -0.0001, math.nan, math.inf])
def test_rejects_negative_or_non_finite_factors(factor):
    with pytest.raises(InvalidInputError, match="factor"):
        SYSTEM.scale_huang_rhys(factor)


def test_rejects_a_negative_factor_even_when_every_s_is_zero():
    """S が全部 0 だと掛けても負にならないが、負の倍は意図の誤りなので止める。"""
    zero = VibrationalSystem([VibrationalMode(frequency=800.0, huang_rhys=0.0)])

    with pytest.raises(InvalidInputError, match="factor"):
        zero.scale_huang_rhys(-1.0)


def test_envelope_first_moment_follows_the_scaled_reorganization_energy():
    """<E> = -lambda なので、倍にした系のエンベロープの平均は -factor * lambda になる。"""
    factor = 1.8
    scaled = SYSTEM.scale_huang_rhys(factor)
    result = compute_quietly(
        scaled,
        temperature=300.0,
        broadening=Broadening(sigma=150.0),
        grid=EnergyGrid.from_spacing(e_min=-12000.0, e_max=12000.0, de=2.0),
    )

    _, mean, _ = moments(result)
    assert mean == pytest.approx(-factor * SYSTEM.reorganization_energy, abs=1e-6)
