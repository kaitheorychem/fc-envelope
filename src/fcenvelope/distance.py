"""2 つのエンベロープの距離（ADR-0088）。

本プログラムが計算したエンベロープ同士だけを比べる。配列や外部のスペクトルは受けない。
ノルムはどれも E 軸上の連続な積分として定義し、出力グリッドの和で近似する。

    L1 = ∫|F1 - F2| dE           無次元。0 から 2
    L2 = (∫|F1 - F2|^2 dE)^(1/2)  (cm^-1)^(-1/2)
    L∞ = max|F1 - F2|             1/cm^-1

和は `Diagnostics.total_area` と同じく ΔE を掛けた長方形則で取る。ΔE を掛けるので、
値はグリッドの細かさによらない。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Literal

import numpy as np

from .errors import InvalidInputError
from .result import EnvelopeResult

__all__ = ["NORMS", "Norm", "envelope_distance"]

#: ノルムの名前。数学の書き方 L1・L2・L∞ に揃え、L∞ は "Linf" と書く。
Norm = Literal["L1", "L2", "Linf"]


def _l1(difference: np.ndarray, de: float) -> float:
    return float(np.sum(difference) * de)


def _l2(difference: np.ndarray, de: float) -> float:
    return math.sqrt(float(np.sum(difference**2) * de))


def _linf(difference: np.ndarray, de: float) -> float:
    return float(np.max(difference))


#: ノルムの名前 → |F_a - F_b| と ΔE から値を出す関数（ADR-0049 と同じく表で引く）。
NORMS: dict[str, Callable[[np.ndarray, float], float]] = {
    "L1": _l1,
    "L2": _l2,
    "Linf": _linf,
}

#: 2 つの出力グリッドを同じとみなす E のずれ。ΔE に対する比で表す。読み直した
#: 結果のように、同じ点が丸めの分だけずれていても同じとみなすための緩衝である。
_GRID_TOLERANCE = 1e-9


def envelope_distance(a: EnvelopeResult, b: EnvelopeResult, *, norm: Norm) -> float:
    """2 つのエンベロープの差 F_a - F_b のノルムを返す。

    `norm` は "L1"・"L2"・"Linf" のどれかで、既定値はない（ノルムごとに単位が違うため）。
    返す値の単位は L1 が無次元、L2 が (cm^-1)^(-1/2)、L∞ が 1/cm^-1 である。

    2 つの出力グリッドは同じ点でなければならない。ΔE か窓が違えば補間せずに
    `InvalidInputError` で止める。`n_fft` だけが違うなら点は同じなので比べられる。
    規格化はやり直さない。どちらも全域で ∫F dE = 1 なので、窓の中で規格化し直すと
    窓の外へ逃げた面積の差が隠れる。系・温度・線形状は違っていてよい（それを比べる
    ための関数なので警告しない）。

        distance = envelope_distance(result_300k, result_77k, norm="L1")
    """
    measure = NORMS.get(norm) if isinstance(norm, str) else None
    if measure is None:
        raise InvalidInputError(
            f"norm must be one of {', '.join(map(repr, NORMS))} (got {norm!r})"
        )
    _check_same_grid(a, b)
    return measure(np.abs(a.density - b.density), a.grid.de)


def _check_same_grid(a: EnvelopeResult, b: EnvelopeResult) -> None:
    de_a, de_b = a.grid.de, b.grid.de
    if not math.isclose(de_a, de_b, rel_tol=_GRID_TOLERANCE, abs_tol=0.0):
        raise InvalidInputError(
            f"the envelopes are sampled with different spacings (de = {de_a} and {de_b} "
            "cm^-1); compute both on the same grid, or interpolate them yourself"
        )
    tolerance = _GRID_TOLERANCE * de_a
    if a.energy.shape != b.energy.shape or not np.allclose(
        a.energy, b.energy, rtol=0.0, atol=tolerance
    ):
        raise InvalidInputError(
            "the envelopes cover different windows "
            f"([{_span(a)}] and [{_span(b)}] cm^-1); "
            "compute both with the same grid.e_min / grid.e_max"
        )


def _span(result: EnvelopeResult) -> str:
    return f"{result.energy[0]:g}, {result.energy[-1]:g}"
