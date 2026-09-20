"""離散 FC 因子の列挙（`compute_fc_lines`）。

中核の検証はエンベロープとの突き合わせ。線をガウシアンで畳んで足し上げたものは
FFT で求めた F(E) に一致しなければならない。両者は独立な実装であり、符号規約・
熱占有・規格化のいずれを取り違えてもこの一致が壊れる。
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pytest
from conftest import lines_quietly

from fcenvelope import (
    Broadening,
    EnergyGrid,
    InvalidInputError,
    NumericalQualityWarning,
    Selection,
    VibrationalMode,
    VibrationalSystem,
    compute_fc_lines,
)

TEMPERATURES = [0.0, 77.0, 300.0]


def broadened(result, energy: np.ndarray, sigma: float) -> np.ndarray:
    """線をガウシアンで畳んだスペクトル密度。"""
    total = np.zeros_like(energy)
    for line in result.lines:
        total += line.weight * np.exp(
            -0.5 * ((energy - line.energy) / sigma) ** 2
        ) / (sigma * math.sqrt(2.0 * math.pi))
    return total


@pytest.fixture(params=TEMPERATURES, ids=lambda t: f"T={t:g}K")
def temperature(request: pytest.FixtureRequest) -> float:
    return request.param


def test_single_mode_at_zero_temperature_is_the_poisson_series(single_mode):
    """T = 0・単一モードでは FC = exp(-S) S^k / k! が E = -k eps に並ぶ。"""
    mode = single_mode.modes[0]
    result = lines_quietly(single_mode, temperature=0.0, min_weight=1e-12)

    for line in result.lines:
        # ZPL は量子数がすべて 0 なので遷移を持たない。
        assert len(line.transitions) <= 1
        quanta = 0
        if line.transitions:
            transition = line.transitions[0]
            assert transition.initial == 0
            quanta = transition.final
        assert line.energy == pytest.approx(-quanta * mode.frequency)
        assert line.fc_factor == pytest.approx(
            math.exp(-mode.huang_rhys) * mode.huang_rhys**quanta / math.factorial(quanta)
        )
        assert line.weight == pytest.approx(line.fc_factor)


def test_zero_phonon_line_comes_first_and_sits_at_zero(multi_mode, temperature):
    """E = 0 の ZPL は遷移を持たない線として必ず含まれる。"""
    result = lines_quietly(multi_mode, temperature=temperature, min_weight=1e-8)
    zero_phonon = [line for line in result.lines if not line.transitions]
    assert len(zero_phonon) == 1
    assert zero_phonon[0].energy == 0.0
    assert zero_phonon[0].fc_factor == pytest.approx(
        math.exp(-sum(mode.huang_rhys for mode in multi_mode.modes))
    )


def test_lines_are_sorted_by_weight(multi_mode, temperature):
    result = lines_quietly(multi_mode, temperature=temperature, min_weight=1e-6)
    weights = result.weights
    assert np.all(np.diff(weights) <= 0.0)
    assert np.all(weights >= result.selection.min_weight)


def test_broadened_lines_reproduce_the_envelope(multi_mode, temperature):
    """離散線とエンベロープは同じ物理量の 2 つの表現であり一致する。"""
    from conftest import compute_quietly

    sigma = 150.0
    envelope = compute_quietly(
        multi_mode,
        temperature=temperature,
        broadening=Broadening(sigma=sigma),
        grid=EnergyGrid.from_spacing(e_min=-12000.0, e_max=12000.0, de=4.0),
    )
    result = lines_quietly(
        multi_mode, temperature=temperature, min_weight=1e-7, max_lines=200000
    )

    assert result.diagnostics.beam_truncated is False
    reconstructed = broadened(result, envelope.energy, sigma)
    peak = float(np.max(envelope.density))
    residual = float(np.max(np.abs(reconstructed - envelope.density)))
    # 取りこぼした強度（1 - captured）が誤差の上限を与える。
    assert residual / peak < 10.0 * (1.0 - result.diagnostics.captured_weight) + 1e-9


def test_total_weight_approaches_one(multi_mode, temperature):
    """全遷移にわたる線強度の総和は厳密に 1。閾値の分だけ取りこぼす。"""
    coarse = lines_quietly(multi_mode, temperature=temperature, min_weight=1e-4)
    fine = lines_quietly(
        multi_mode, temperature=temperature, min_weight=1e-7, max_lines=200000
    )
    assert coarse.diagnostics.captured_weight < fine.diagnostics.captured_weight
    assert fine.diagnostics.captured_weight == pytest.approx(1.0, abs=1e-3)


def test_mean_energy_approaches_minus_reorganization_energy(multi_mode, temperature):
    """<E> = -lambda（合意文書 §11 の 1 次モーメント、温度に依存しない）。"""
    result = lines_quietly(
        multi_mode, temperature=temperature, min_weight=1e-7, max_lines=200000
    )
    expected = -multi_mode.reorganization_energy
    assert result.system.reorganization_energy == pytest.approx(-expected)
    assert result.diagnostics.mean_energy == pytest.approx(expected, rel=1e-3)


def test_threshold_is_exhaustive(multi_mode):
    """閾値以上の線は枝刈りで取りこぼされない（細かい計算の部分集合と一致する）。"""
    coarse = lines_quietly(multi_mode, temperature=300.0, min_weight=1e-3)
    fine = lines_quietly(
        multi_mode, temperature=300.0, min_weight=1e-8, max_lines=200000
    )

    def key(line):
        return tuple(
            (t.mode_index, t.initial, t.final) for t in line.transitions
        )

    expected = {key(line) for line in fine.lines if line.weight >= 1e-3}
    assert {key(line) for line in coarse.lines} == expected


def test_sidebands_are_negative_and_hot_bands_positive(single_mode):
    """符号規約 §3: 量子生成は負側、ホットバンドは正側。"""
    mode = single_mode.modes[0]
    cold = lines_quietly(single_mode, temperature=0.0, min_weight=1e-8)
    assert all(line.energy <= 0.0 for line in cold.lines)

    hot = lines_quietly(
        VibrationalSystem([VibrationalMode(frequency=200.0, huang_rhys=0.5)]),
        temperature=600.0,
        min_weight=1e-4,
    )
    positive = [line for line in hot.lines if line.energy > 0.0]
    assert positive
    for line in positive:
        transition = line.transitions[0]
        assert transition.initial > transition.final
        assert line.energy == pytest.approx(
            (transition.initial - transition.final) * 200.0
        )
    del mode


def test_zero_coupling_puts_every_line_at_the_zero_phonon_energy():
    """S = 0 では n -> n しか起きない。

    始状態が熱的に分布するぶん線は複数本になるが、どれも E = 0 で FC = 1 であり、
    強度の総和は 1 になる。エネルギーが縮退した遷移はまとめずに別の線として残す。
    """
    result = lines_quietly(
        VibrationalSystem([VibrationalMode(frequency=800.0, huang_rhys=0.0)]),
        temperature=300.0,
    )
    assert all(line.energy == 0.0 for line in result.lines)
    assert all(line.fc_factor == pytest.approx(1.0) for line in result.lines)
    assert all(
        transition.initial == transition.final
        for line in result.lines
        for transition in line.transitions
    )
    assert result.diagnostics.captured_weight == pytest.approx(1.0, abs=1e-4)
    assert result.system.reorganization_energy == 0.0


def test_temperature_zero_keeps_the_initial_state_in_the_ground_state(multi_mode):
    result = lines_quietly(multi_mode, temperature=0.0, min_weight=1e-6)
    assert result.diagnostics.max_initial_quanta == 0
    assert all(t.initial == 0 for line in result.lines for t in line.transitions)
    assert all(line.weight == pytest.approx(line.fc_factor) for line in result.lines)


def test_max_lines_truncates_and_warns(multi_mode):
    with pytest.warns(NumericalQualityWarning, match="max_lines"):
        result = compute_fc_lines(
            multi_mode,
            temperature=300.0,
            selection=Selection(min_weight=1e-8, max_lines=50),
        )
    assert result.diagnostics.n_lines == 50
    assert result.diagnostics.beam_truncated is True


def test_low_coverage_warns(multi_mode):
    """線は拾えているが強度の大半を取りこぼしている場合。"""
    with pytest.warns(NumericalQualityWarning, match="captured_weight"):
        result = compute_fc_lines(
            multi_mode, temperature=300.0, selection=Selection(min_weight=0.02)
        )
    assert result.diagnostics.n_lines > 0
    assert result.diagnostics.captured_weight < 0.9


def test_no_line_above_the_threshold_reports_the_strongest(multi_mode):
    with pytest.warns(NumericalQualityWarning, match="strongest possible line"):
        result = compute_fc_lines(
            multi_mode, temperature=300.0, selection=Selection(min_weight=1.0)
        )
    assert result.lines == ()
    assert result.diagnostics.captured_weight == 0.0


def test_max_quanta_caps_the_ladder_and_warns(single_mode):
    with pytest.warns(NumericalQualityWarning, match="min_mode_completeness"):
        result = compute_fc_lines(
            single_mode, temperature=0.0, selection=Selection(max_quanta=1)
        )
    assert result.diagnostics.max_final_quanta == 1
    assert result.diagnostics.min_mode_completeness < 1.0


def test_recurrence_limited_initial_state_warns():
    """g も n も大きい領域では漸化式の破綻を避けて n を打ち切る。"""
    system = VibrationalSystem([VibrationalMode(frequency=40.0, huang_rhys=25.0)])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = compute_fc_lines(
            system, temperature=300.0, selection=Selection(min_weight=1e-4)
        )
    assert result.diagnostics.recurrence_limited is True
    assert any("recurrence" in str(entry.message) for entry in caught)


def test_negative_temperature_is_rejected(single_mode):
    with pytest.raises(InvalidInputError):
        compute_fc_lines(single_mode, temperature=-1.0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_weight": 0.0},
        {"min_weight": 2.0},
        {"max_lines": 0},
        {"max_quanta": -1},
    ],
)
def test_selection_rejects_invalid_knobs(kwargs):
    """つまみの不変条件は `Selection` 自身が守る（ADR-0051）。"""
    with pytest.raises(InvalidInputError):
        Selection(**kwargs)


def test_empty_system_is_rejected():
    with pytest.raises(InvalidInputError):
        VibrationalSystem([])


def test_arrays_follow_the_line_order(multi_mode):
    result = lines_quietly(multi_mode, temperature=77.0, min_weight=1e-5)
    assert result.energies.shape == result.weights.shape == result.fc_factors.shape
    assert result.energies[0] == result.lines[0].energy
    assert result.fc_factors[-1] == result.lines[-1].fc_factor
