"""単位と振電相互作用の流儀。

流儀は Enum と関数表ではなくオブジェクトにする（ADR-0033）。変換式・単位の有無・
振動数への依存の仕方を、流儀自身が知っている必要があるためである。

`docs/theory/vcc.md` の 5 流儀のうち、S への変換に振動数を要するのは V と lambda の
2 つで、この 2 つだけが単位を持つ。

| 流儀 | S への変換 | omega が要るか | coupling の次元 |
|---|---|---|---|
| g | S = g^2 | 不要 | 無次元 |
| Delta | S = Delta^2 / 2 | 不要 | 無次元 |
| huang_rhys | 恒等 | 不要 | 無次元 |
| vcc (V) | S = V^2 / (2 h_bar omega^3) | 必要 | エネルギー^(3/2) |
| lambda | S = lambda / (h_bar omega) | 必要 | エネルギー |

**このリファクタリングで実装するのは g と huang_rhys だけである。** V と lambda を
足すことは目的ではなく、足せる構造にすることが目的なので、登録するのは 2 つに留める。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .errors import InvalidInputError, UnsupportedUnitError

__all__ = [
    "CANONICAL_FREQUENCY_UNIT",
    "COUPLING_CONVENTIONS",
    "DEFAULT_COUPLING_CONVENTION",
    "G",
    "HUANG_RHYS",
    "CouplingConvention",
    "check_frequency_unit",
    "coupling_convention",
]

#: 内部で用いる振動数の単位。入力はここへ正準化される。
CANONICAL_FREQUENCY_UNIT = "cm^-1"


def check_frequency_unit(unit: str) -> str:
    """振動数の単位を検証して返す。

    単位変換を入れるときに、ここが変換係数の引き当てになる。今は正準な単位しか
    受け付けない。
    """
    if unit != CANONICAL_FREQUENCY_UNIT:
        raise UnsupportedUnitError(
            f"unsupported frequency_unit {unit!r} "
            f"(only {CANONICAL_FREQUENCY_UNIT!r} is supported)"
        )
    return unit


@dataclass(frozen=True, slots=True)
class CouplingConvention:
    """結合をどの量で書くかの選択。変換式と単位の扱いを自分で持つ。"""

    name: str
    """入力ファイルの `coupling_convention` に書く名前。"""

    energy_power: float | None
    """coupling の次元を「エネルギーの何乗か」で表したもの。None なら無次元。

    g / Delta / huang_rhys は None、V は 1.5、lambda は 1.0。単位を持つ流儀では
    coupling と frequency を同じエネルギー単位で表しておけば、変換式の中で次元が
    打ち消し合う（V なら V^2 / omega^3、lambda なら lambda / omega）。これが
    「frequency の単位とどう組み合わさるか」の中身である。
    """

    converter: Callable[[float, float], float]
    """(coupling, frequency) -> S。無次元の流儀は frequency を使わない。"""

    @property
    def is_dimensionless(self) -> bool:
        """単位を持たない流儀か。"""
        return self.energy_power is None

    def to_huang_rhys(self, coupling: float, frequency: float) -> float:
        """coupling を Huang-Rhys 因子 S に変換する。

        `frequency` は正準な単位（cm^-1）で与える。単位を持つ流儀では `coupling` も
        同じエネルギー単位に揃えてから渡す。
        """
        return self.converter(coupling, frequency)

    def check_coupling_unit(self, unit: str | None) -> None:
        """coupling に添えられた単位が、この流儀にとって妥当かを検査する。

        無次元の流儀に単位を添えるのは誤りであり、単位を持つ流儀では単位が要る。
        今の入力フォーマットは coupling の単位を持たないので `None` が渡る。
        """
        if self.is_dimensionless:
            if unit is not None:
                raise InvalidInputError(
                    f"coupling_convention {self.name!r} is dimensionless; "
                    f"a coupling unit ({unit!r}) must not be given"
                )
            return
        if unit is None:
            raise UnsupportedUnitError(
                f"coupling_convention {self.name!r} carries units "
                f"(energy^{self.energy_power:g}); a coupling unit must be given"
            )


G = CouplingConvention(name="g", energy_power=None, converter=lambda g, _: g * g)
"""無次元化振電相互作用定数。S = g^2。g の符号は S に効かない（ADR-0003）。"""

HUANG_RHYS = CouplingConvention(
    name="huang_rhys", energy_power=None, converter=lambda s, _: s
)
"""正準量そのもの。変換は恒等。"""

#: 名前 -> 流儀。流儀の追加は 1 エントリの追加で済む。
COUPLING_CONVENTIONS: dict[str, CouplingConvention] = {
    convention.name: convention for convention in (G, HUANG_RHYS)
}

#: 入力ファイルで `coupling_convention` を省略したときの流儀。
DEFAULT_COUPLING_CONVENTION = G


def coupling_convention(name: str) -> CouplingConvention:
    """名前から流儀を引く。未知の名前は `InvalidInputError`。"""
    try:
        return COUPLING_CONVENTIONS[name]
    except (KeyError, TypeError) as exc:
        known = ", ".join(sorted(COUPLING_CONVENTIONS))
        raise InvalidInputError(
            f"unknown coupling_convention {name!r} (known conventions: {known})"
        ) from exc
