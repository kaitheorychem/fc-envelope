"""平行移動演算子の行列要素と FC 因子（`docs/theory/fc-factor.md`）。

漸化式

    sqrt(n+1) <m|U|n+1> = sqrt(m) <m-1|U|n> - g <m|U|n>

を、閉じた解析形および完全性 sum_m |<m|U|n>|^2 = 1 で検証する。
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.special import eval_genlaguerre, factorial

from fcenvelope import fc_factor_matrix
from fcenvelope.lines import RECURRENCE_TOLERANCE, displacement_matrix

HUANG_RHYS = [0.0, 0.25, 1.0, 3.0, 6.0]


def analytic_element(g: float, m: int, n: int) -> float:
    """<m|D(g)|n> の閉じた形（Laguerre 陪多項式）。g は実。"""
    if m >= n:
        return (
            math.sqrt(factorial(n) / factorial(m))
            * g ** (m - n)
            * math.exp(-0.5 * g * g)
            * eval_genlaguerre(n, m - n, g * g)
        )
    return (
        math.sqrt(factorial(m) / factorial(n))
        * (-g) ** (n - m)
        * math.exp(-0.5 * g * g)
        * eval_genlaguerre(m, n - m, g * g)
    )


#: 最大値で正規化した相対誤差の許容値（ADR-0042）。
#:
#: 漸化式は n を 1 段進めるたびに sqrt(m) <m-1|U|n> と g <m|U|n> の差を取る。12 段ぶんの
#: 打ち消しで ~1e-10 の相対誤差が出るため、判定は量の大きさに対して相対的でなければ
#: ならない。要素ごとの相対誤差は使えない: 行列の要素の大半はほぼ 0 で 0/0 になる。
#: 絶対値で測ると S を広げるたびに同じ形で破綻する（S = 6 で max|rec - ana| = 1.488e-11、
#: max|ana| = 0.4008 なので相対では 3.7e-11）。
#:
#: これは ADR-0024 が記録した漸化式の「破綻」とは別物である。破綻は列和 sum_m FC_mn が
#: 1 を大きく上回る形で現れ（S = 25・n = 29 でずれは -0.26）、ここで見ているずれは
#: S = 6・n = 12 で ~1e-16 と機械精度に収まっている。
RELATIVE_TOLERANCE = 1e-9


@pytest.mark.parametrize("huang_rhys", HUANG_RHYS)
def test_recurrence_matches_the_closed_form(huang_rhys):
    """漸化式で組んだ行列要素が解析形と一致する。"""
    g = math.sqrt(huang_rhys)
    elements = displacement_matrix(g, 25, 12)
    expected = np.array(
        [[analytic_element(g, m, n) for n in range(13)] for m in range(26)]
    )
    residual = np.max(np.abs(elements - expected))
    assert residual < RELATIVE_TOLERANCE * np.max(np.abs(expected))


@pytest.mark.parametrize("huang_rhys", HUANG_RHYS)
def test_columns_are_normalized(huang_rhys):
    """U はユニタリなので各列の FC 因子の和は 1（梯子が十分長ければ）。"""
    factors = fc_factor_matrix(huang_rhys, 120, 10)
    np.testing.assert_allclose(factors.sum(axis=0), 1.0, atol=1e-12)


@pytest.mark.parametrize("huang_rhys", HUANG_RHYS)
def test_ground_state_column_is_the_poisson_series(huang_rhys):
    """n = 0 の列は FC = exp(-S) S^m / m!（合意文書 §3 の検算式）。"""
    factors = fc_factor_matrix(huang_rhys, 40)
    expected = np.array(
        [
            math.exp(-huang_rhys) * huang_rhys**m / math.factorial(m)
            for m in range(41)
        ]
    )
    np.testing.assert_allclose(factors[:, 0], expected, rtol=1e-12, atol=1e-300)


@pytest.mark.parametrize("huang_rhys", HUANG_RHYS)
def test_matrix_is_symmetric_in_magnitude(huang_rhys):
    """|<m|U|n>| = |<n|U|m>|。漸化式とは独立な不変量。"""
    factors = fc_factor_matrix(huang_rhys, 20, 20)
    np.testing.assert_allclose(factors, factors.T, atol=1e-12)


def test_zero_coupling_is_the_identity():
    """S = 0 では平行移動がないので FC は単位行列。"""
    np.testing.assert_array_equal(fc_factor_matrix(0.0, 5, 5), np.eye(6))


def test_default_is_the_ground_state_column_only():
    assert fc_factor_matrix(1.0, 7).shape == (8, 1)


def test_large_coupling_and_high_n_breaks_the_recurrence_upwards():
    """破綻の向きを固定する。

    梯子の打ち切りは正の項を落とすだけなので列和は 1 を下回る。一方、漸化式の
    桁落ちは二乗されて正の側に積み上がるため列和は 1 を上回る。
    `_stable_fc_matrix` はこの向きの違いで両者を見分けている。
    """
    sums = fc_factor_matrix(25.0, 600, 60).sum(axis=0)
    assert np.max(sums) > 1.0 + RECURRENCE_TOLERANCE

    truncated = fc_factor_matrix(1.0, 3, 4).sum(axis=0)
    assert np.all(truncated < 1.0)


@pytest.mark.parametrize("bad", [-1.0])
def test_negative_coupling_is_rejected(bad):
    with pytest.raises(ValueError):
        fc_factor_matrix(bad, 4)
    with pytest.raises(ValueError):
        displacement_matrix(bad, 4, 0)


def test_negative_sizes_are_rejected():
    with pytest.raises(ValueError):
        displacement_matrix(1.0, -1, 0)
