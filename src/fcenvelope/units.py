"""単位と振電相互作用の流儀。

流儀は「結合をどの量で書くか」の選択であり、`docs/theory/vcc.md` の 5 つを区別する。
変換式・単位の有無・振動数への依存の仕方は流儀ごとに違うので、それらを自分で知って
いるオブジェクトとして表す（ADR-0033）。

| 流儀 | S への変換 | omega が要るか | 単位 |
|---|---|---|---|
| g | S = g^2 | 不要 | 無次元 |
| delta | S = Delta^2 / 2 | 不要 | 無次元 |
| huang_rhys | 恒等 | 不要 | 無次元 |
| vcc | S = V^2 / (2 omega^3) | **必要** | エネルギー^(3/2) |
| lambda | S = lambda / omega | **必要** | エネルギー |

正準量を S とする決定そのものは ADR-0003 のまま。g の符号は物理的に無意味なので、
平方根の往復を避けて S を内部表現に選んでいる。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from fractions import Fraction

from .errors import InvalidInputError, UnsupportedUnitError

__all__ = [
    "CANONICAL_FREQUENCY_UNIT",
    "COUPLING_CONVENTIONS",
    "CouplingConvention",
    "check_frequency_unit",
    "coupling_convention",
]

#: エネルギーの正準単位。入力・内部・出力のすべてでこれを使う（ADR-0002）。
CANONICAL_FREQUENCY_UNIT = "cm^-1"


@dataclass(frozen=True)
class CouplingConvention:
    """振電相互作用パラメータの流儀。

    `frequency_power` は coupling の単位が振動数の単位の何乗かを表す。0 なら無次元で、
    このとき単位を添えることはできない。関数表 `Callable[[float], float]` では
    V（omega^3 が要る）と lambda（omega が要る）を構造的に表現できず、単位の有無を
    置く場所もなかった。それがこの型を導入した理由である（ADR-0033）。
    """

    key: str
    """入力ファイルの `coupling_convention` に書く文字列。"""

    symbol: str
    """文書と警告文で使う記号。"""

    frequency_power: float
    """coupling の単位 = （振動数の単位）^frequency_power。0 なら無次元。"""

    convert: Callable[[float, float], float] = field(repr=False, compare=False)
    """(coupling, frequency [cm^-1]) -> S。無次元の流儀は frequency を無視する。"""

    @property
    def is_dimensionless(self) -> bool:
        """単位を持たない流儀か。`coupling_unit` が None を返すのと同じこと。"""
        return self.frequency_power == 0.0

    def coupling_unit(self, frequency_unit: str = CANONICAL_FREQUENCY_UNIT) -> str | None:
        """この流儀の coupling が持つ単位。無次元なら None。

        単位は振動数の単位と組で決まる。V を eV^(3/2) で、omega を cm^-1 で与えて
        よいか、という問いが立たないのはこのためである（ADR-0033）。
        """
        if self.is_dimensionless:
            return None
        if self.frequency_power == 1.0:
            return frequency_unit
        power = Fraction(self.frequency_power).limit_denominator()
        return f"({frequency_unit})^{power}"

    def to_huang_rhys(self, coupling: float, frequency: float) -> float:
        """流儀に従った coupling 値を Huang-Rhys 因子 S に変換する。

        Args:
            coupling: この流儀での結合の値。単位は `coupling_unit()`。
            frequency: 同じモードの振動数 [cm^-1]。無次元の流儀では使われない。
        """
        return self.convert(coupling, frequency)


#: 無次元化振電相互作用定数 g。H = hbar omega g (a + a^dagger)。
G = CouplingConvention("g", "g", 0.0, lambda coupling, _: coupling * coupling)

#: 無次元化変位 Delta = sqrt(2) g。
DELTA = CouplingConvention("delta", "Delta", 0.0, lambda coupling, _: 0.5 * coupling * coupling)

#: Huang-Rhys 因子そのもの。正準量なので変換は恒等。
HUANG_RHYS = CouplingConvention("huang_rhys", "S", 0.0, lambda coupling, _: coupling)

#: 振電相互作用定数 V = g sqrt(2 hbar omega^3)。片方のポテンシャルの底での他方の傾き。
VCC = CouplingConvention(
    "vcc", "V", 1.5, lambda coupling, frequency: coupling * coupling / (2.0 * frequency**3)
)

#: 再配列エネルギー lambda = hbar omega S。片方のポテンシャルの底での他方の高さ。
REORGANIZATION_ENERGY = CouplingConvention(
    "lambda", "lambda", 1.0, lambda coupling, frequency: coupling / frequency
)

#: 流儀は 5 つで打ち止めである（物理モデルが固定なので増えない）。
COUPLING_CONVENTIONS: Mapping[str, CouplingConvention] = {
    convention.key: convention
    for convention in (G, DELTA, HUANG_RHYS, VCC, REORGANIZATION_ENERGY)
}

# 名前で辿れるようにする。`CouplingConvention.G` のように書ける。
CouplingConvention.G = G
CouplingConvention.DELTA = DELTA
CouplingConvention.HUANG_RHYS = HUANG_RHYS
CouplingConvention.VCC = VCC
CouplingConvention.REORGANIZATION_ENERGY = REORGANIZATION_ENERGY


def coupling_convention(value: object) -> CouplingConvention:
    """流儀名を `CouplingConvention` に解決する。未知の名前は `InvalidInputError`。"""
    if isinstance(value, CouplingConvention):
        return value
    if isinstance(value, str) and value in COUPLING_CONVENTIONS:
        return COUPLING_CONVENTIONS[value]
    known = ", ".join(sorted(COUPLING_CONVENTIONS))
    raise InvalidInputError(f"unknown coupling_convention {value!r} (known: {known})")


def check_frequency_unit(value: object) -> str:
    """振動数の単位を検査する。cm^-1 以外は `UnsupportedUnitError`。"""
    if value != CANONICAL_FREQUENCY_UNIT:
        raise UnsupportedUnitError(
            f"unsupported frequency_unit {value!r} "
            f"(only {CANONICAL_FREQUENCY_UNIT!r} is supported)"
        )
    return CANONICAL_FREQUENCY_UNIT
