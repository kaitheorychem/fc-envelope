"""計算用の値の型。常に正準形で、pydantic に依存しない。

入力ファイルの形（単位・流儀・構造）は `inputs.py` が扱う。このモジュールの型は
その先にあり、振動数は常に cm^-1、結合は常に Huang-Rhys 因子 S である
（`docs/adr/0045-separate-input-file-types-from-computation-values.md`）。

どの型も `__post_init__` で自分の不変条件を検証し、違反は `InvalidInputError` に
する。入口が入力ファイルでもライブラリの直接呼び出しでも同じように守られる
（`docs/adr/0051-value-types-validate-their-own-invariants.md`）。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

import numpy as np

from .errors import InvalidInputError
from .physics import occupation_numbers

__all__ = [
    "Broadening",
    "EnergyGrid",
    "Selection",
    "VibrationalMode",
    "VibrationalSystem",
    "validate_frequency",
    "validate_temperature",
]


def validate_temperature(temperature: float) -> float:
    """T [K] の不変条件 T >= 0 を検証して返す。

    温度は系にも条件のどの型にも属さない独立したフィールドなので（ADR-0046）、
    型の `__post_init__` ではなくこの関数が唯一の置き場になる。制約を 2 箇所に
    書かないための措置で、狙いは ADR-0051 と同じである。
    """
    if not temperature >= 0.0:
        raise InvalidInputError(
            f"temperature must be non-negative (got {temperature})"
        )
    return temperature


def validate_frequency(frequency: float) -> float:
    """振動数 eps [cm^-1] の不変条件 eps > 0 を検証して返す。

    `VibrationalMode` の検査はこれを使う。入力の正準化も、振動数で割る流儀の変換式
    （lambda / vcc）を呼ぶ前にこれを呼ぶ（ADR-0077）。そうしないと 0 の振動数が
    `ZeroDivisionError` として落ちる。制約はこの 1 箇所にだけ書く（ADR-0051）。
    """
    if not frequency > 0.0:
        raise InvalidInputError(f"frequency must be positive (got {frequency})")
    return frequency


@dataclass(frozen=True, slots=True)
class VibrationalMode:
    """基底状態の調和ポテンシャルにおける 1 つの基準振動。正準形。"""

    frequency: float
    """epsilon_alpha [cm^-1]。"""

    huang_rhys: float
    """S_alpha（無次元）。"""

    def __post_init__(self) -> None:
        validate_frequency(self.frequency)
        if not self.huang_rhys >= 0.0:
            raise InvalidInputError(
                f"huang_rhys must be non-negative (got {self.huang_rhys})"
            )


@dataclass(frozen=True, slots=True)
class VibrationalSystem:
    """計算対象の分子の振動モードの集まり。分子に固有で、条件は含まない。

    単位変換・流儀・非対角な基底からの入力といった入口がいくつ増えても、正準化の
    行き先はこの型 1 つである（`docs/adr/0044-vibrational-system-class.md`）。
    """

    modes: tuple[VibrationalMode, ...]
    """1 つ以上の振動モード。"""

    def __init__(self, modes: Sequence[VibrationalMode]) -> None:
        object.__setattr__(self, "modes", tuple(modes))
        self.__post_init__()

    def __post_init__(self) -> None:
        if not self.modes:
            raise InvalidInputError("a system must have at least one mode")
        for index, mode in enumerate(self.modes):
            if not isinstance(mode, VibrationalMode):
                raise InvalidInputError(
                    f"modes[{index}] must be a VibrationalMode "
                    f"(got {type(mode).__name__})"
                )

    @property
    def frequencies(self) -> np.ndarray:
        """(A,) float64, cm^-1。`modes` と同じ順序。"""
        return np.array([mode.frequency for mode in self.modes], dtype=np.float64)

    @property
    def huang_rhys(self) -> np.ndarray:
        """(A,) float64, 無次元。`modes` と同じ順序。"""
        return np.array([mode.huang_rhys for mode in self.modes], dtype=np.float64)

    @property
    def reorganization_energy(self) -> float:
        """再配列エネルギー lambda = sum_alpha S_alpha * eps_alpha [cm^-1]。

        系から一意に決まるので結果クラスには持たせない（ADR-0047）。
        """
        return float(sum(mode.huang_rhys * mode.frequency for mode in self.modes))

    def occupations(self, temperature: float) -> np.ndarray:
        """温度 T [K] での占有数 n_alpha。式そのものは `physics.py` にある。"""
        return occupation_numbers(self.frequencies, temperature)


@dataclass(frozen=True, slots=True)
class Broadening:
    """1 本の線が E 軸上で持つ幅と形。現在はガウス幅 sigma だけを扱う。

    **線形状がガウス型であるという知識はこの型だけが持つ**（ADR-0034）。
    `envelope.py` は `log_damping` を、`plotting.py` は `peak_height` を、診断は
    `truncation_indicator` を呼ぶだけで、種類を知らなくてよい。gamma を足す作業は
    この型の中だけで済む。

    型階層にはしない——ガウス・ローレンツ・Voigt は時間領域ではいずれも rho(tau) に
    掛かる実数の減衰因子で、パラメータ (sigma, gamma) を持つ 1 つの族だからである。
    """

    sigma: float
    """sigma [cm^-1]。"""

    #: `truncation_indicator` がこれを下回ると、tau 窓が閉じる前に減衰が終わって
    #: いないとみなす。ガウス型では sigma*tau_max >= 6 に当たる。
    MIN_TRUNCATION_INDICATOR: ClassVar[float] = 6.0

    def __post_init__(self) -> None:
        if not self.sigma > 0.0:
            raise InvalidInputError(f"sigma must be positive (got {self.sigma})")

    def log_damping(self, tau: np.ndarray) -> np.ndarray:
        """時間領域で rho(tau) に掛かる減衰因子の対数 ln D(tau)。

        ガウス型では ln D = -sigma^2 tau^2 / 2（`docs/theory/time-ft.md`）。対数で
        返すのは、呼び出し側が ln rho(tau) に足すだけで済むようにするため。
        """
        return -0.5 * self.sigma**2 * np.asarray(tau, dtype=float) ** 2

    def peak_height(self) -> float:
        """規格化された線形状の頂点値 L(0) [1/cm^-1]。

        重み w の線が F(E) に立てる山の高さは w * L(0) である（ADR-0027, 0032）。
        ガウス型では 1 / (sigma * sqrt(2 pi))。
        """
        return 1.0 / (self.sigma * math.sqrt(2.0 * math.pi))

    def truncation_indicator(self, tau_max: float) -> float:
        """tau 窓 [-tau_max, tau_max] の内側で減衰がどれだけ進んだかの指標。

        大きいほど安全で、`MIN_TRUNCATION_INDICATOR` を下回ると窓の打ち切りによる
        リンギングが疑わしくなる。ガウス型では sigma * tau_max。

        Voigt 型を足すときは減衰因子そのもので測る形へ一般化する（ADR-0038、提案）。
        """
        return self.sigma * tau_max


def _next_pow2(value: int) -> int:
    """value 以上の最小の 2 のべき（最小 2）。"""
    if value <= 2:
        return 2
    return 1 << (value - 1).bit_length()


@dataclass(frozen=True, slots=True)
class EnergyGrid:
    """エンベロープを標本する E 軸上の点列。省略値も自動推定もない。

    持つのは**解決済み**の全域グリッド、すなわち点数 `n_fft`（2 の冪）と間隔 `de`
    である。入力ファイルはこの 2 つを直接は書かず、`from_points` か `from_spacing`
    のどちらかで決める（ADR-0070）。窓 `e_min` / `e_max` は切り出しの範囲でしかなく、
    全域グリッドの広さ `n_fft * de` はそれ以上になりうる。
    """

    e_min: float
    """出力窓の下端 [cm^-1]。"""

    e_max: float
    """出力窓の上端 [cm^-1]。"""

    de: float
    """出力グリッド間隔 [cm^-1]。全域幅を `n_fft` で割ったもの。"""

    n_fft: int
    """全域グリッドの点数 N。2 の冪（FFT の基数）。"""

    def __post_init__(self) -> None:
        if not self.de > 0.0:
            raise InvalidInputError(f"de must be positive (got {self.de})")
        if not self.e_min < self.e_max:
            raise InvalidInputError(
                f"e_min must be smaller than e_max (got {self.e_min} >= {self.e_max})"
            )
        if self.n_fft < 2 or self.n_fft & (self.n_fft - 1):
            raise InvalidInputError(
                f"n_fft must be a power of two and at least 2 (got {self.n_fft})"
            )
        # 全域グリッドは窓を覆っていなければならない。等号ちょうどを弾かないよう、
        # 割り算の丸めのぶんだけ緩める。
        if self.full_span < 2.0 * self.e_half * (1.0 - 1e-12):
            raise InvalidInputError(
                f"the full grid must cover the window: n_fft * de = {self.full_span} "
                f"is narrower than 2 * max(|e_min|, |e_max|) = {2.0 * self.e_half}"
            )

    @property
    def e_half(self) -> float:
        """窓を覆う 0 対称な範囲の半幅 [cm^-1]。"""
        return max(abs(self.e_min), abs(self.e_max))

    @property
    def full_span(self) -> float:
        """全域グリッドの広さ `n_fft * de` [cm^-1]。窓より広いことがある。"""
        return self.n_fft * self.de

    @classmethod
    def from_points(cls, *, e_min: float, e_max: float, n: int) -> "EnergyGrid":
        """グリッド数を直接指定して作る。全域幅は窓ちょうど 2 * e_half になる。

        dE = 2 * e_half / n は端数になりうる。丸い dE が欲しいときは
        `from_spacing` を使う（ADR-0070）。
        """
        if n < 2 or n & (n - 1):
            raise InvalidInputError(
                f"n must be a power of two and at least 2 (got {n}); "
                f"write de instead if you want to choose the spacing"
            )
        e_half = max(abs(e_min), abs(e_max))
        return cls(e_min=e_min, e_max=e_max, de=2.0 * e_half / n, n_fft=n)

    @classmethod
    def from_spacing(
        cls, *, e_min: float, e_max: float, de: float, shift: int = 0
    ) -> "EnergyGrid":
        """間隔 dE を指定して作る。グリッド数は窓を覆う最小の 2 の冪になる。

        `shift` は**全域幅を保ったまま**その冪を上へずらす。n は 2^shift 倍、
        dE は 2^shift 分の 1 になり、覆う範囲は変わらないまま刻みだけ細かくなる
        （ADR-0070）。`shift = 0` なら dE は書いた `de` ちょうどである。
        """
        if not de > 0.0:
            raise InvalidInputError(f"de must be positive (got {de})")
        if shift < 0:
            raise InvalidInputError(
                f"shift must be non-negative (got {shift}); "
                f"write a larger de to make the grid coarser"
            )
        e_half = max(abs(e_min), abs(e_max))
        n_base = _next_pow2(math.ceil(2.0 * e_half / de))
        # 2 の冪での乗除なので、ここは浮動小数点でも丸め誤差が出ない。
        return cls(
            e_min=e_min,
            e_max=e_max,
            de=de / (1 << shift),
            n_fft=n_base << shift,
        )


@dataclass(frozen=True, slots=True)
class Selection:
    """離散線のうちどれを保持するかを決めるつまみの組。

    既定値はここにしかない。CLI の既定値は「上書きしない」という意味の `None`
    である（ADR-0050）。
    """

    min_weight: float = 1e-4
    """保持する重みの下限（0 < x <= 1）。"""

    max_lines: int = 10000
    """保持・列挙する線数の上限。"""

    max_quanta: int | None = None
    """1 モードあたりの振動量子数の上限。None なら自動。"""

    def __post_init__(self) -> None:
        if not 0.0 < self.min_weight <= 1.0:
            raise InvalidInputError(
                f"min_weight must lie in (0, 1] (got {self.min_weight})"
            )
        if self.max_lines < 1:
            raise InvalidInputError(
                f"max_lines must be at least 1 (got {self.max_lines})"
            )
        if self.max_quanta is not None and self.max_quanta < 0:
            raise InvalidInputError(
                f"max_quanta must be non-negative (got {self.max_quanta})"
            )
