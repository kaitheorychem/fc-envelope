"""両系統が共有する物理: 熱占有、再配列エネルギー、線形状の頂点値。

エンベロープ（`envelope.py`）と離散線（`lines.py`）は独立な 2 実装だが、
温度の効き方と再配列エネルギーの定義は共有している。ここに置くことで、
どちらか一方がもう一方を import する必要がなくなる（ADR-0041）。

占有数 n_alpha（ボーズ分布の平均）と占有確率 P(n)（同じ分布の確率質量）は

    n_alpha = sum_n n * P(n)

という関係にある同一物理の 2 つの顔であり、別モジュールに置く理由がない。
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from scipy import constants

from .models import VibrationalMode

__all__ = [
    "K_B_CM",
    "boltzmann_populations",
    "occupation_numbers",
    "reorganization_energy",
]

#: ボルツマン定数 [cm^-1 / K]。scipy から導出し、値をハードコードしない。
K_B_CM = constants.k / (constants.h * constants.c * 100.0)


def occupation_numbers(frequencies: np.ndarray, temperature: float) -> np.ndarray:
    """ボーズ分布による占有数 n_alpha を返す。

    `expm1` を用いることで eps / kT が大きい領域は inf -> n = 0 と正しく畳まれる。
    T = 0 は分岐して n = 0 を直接与える。
    """
    freq = np.asarray(frequencies, dtype=float)
    if temperature == 0.0:
        return np.zeros_like(freq)
    with np.errstate(over="ignore"):
        return 1.0 / np.expm1(freq / (K_B_CM * temperature))


def boltzmann_populations(frequency: float, temperature: float, n_max: int) -> np.ndarray:
    """調和振動子の始状態占有 P(n) = (1 - x) x^n, x = exp(-eps / kT) を返す。

    T = 0 は分岐して P(0) = 1 を直接与える。
    """
    populations = np.zeros(n_max + 1, dtype=float)
    if temperature == 0.0:
        populations[0] = 1.0
        return populations
    ratio = math.exp(-frequency / (K_B_CM * temperature))
    populations[:] = (1.0 - ratio) * ratio ** np.arange(n_max + 1)
    return populations


def reorganization_energy(modes: Sequence[VibrationalMode]) -> float:
    """再配列エネルギー lambda = sum_alpha S_alpha * eps_alpha [cm^-1]。"""
    return float(sum(mode.huang_rhys * mode.frequency for mode in modes))
