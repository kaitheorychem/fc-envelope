"""2 つの表現が共有する物理: ボルツマン定数、占有数 n_alpha、梯子 P(n)。

エンベロープ（FFT）と離散線（漸化式）はアルゴリズムを共有しないが、始状態の熱占有
だけは同じ物理から来る。占有数 n_alpha（ボーズ分布の平均）と P(n)（同じ分布の確率
質量）は n_alpha = sum_n n * P(n) という関係にある同一物理の 2 つの顔なので、同じ
モジュールに置く（`docs/adr/0041-symmetric-module-layering-with-a-physics-layer.md`）。

このモジュールは配列と数値だけを扱い、モデルの型を知らない。
"""

from __future__ import annotations

import math

import numpy as np
from scipy import constants

__all__ = [
    "K_B_CM",
    "boltzmann_populations",
    "occupation_numbers",
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
