"""単位と振電相互作用の流儀。

エネルギーの正準単位は cm^-1 で、入力に現れる単位はすべてここへ換算される
（ADR-0002, 0054）。換算係数の表は `ENERGY_UNITS`、引き当ては
`energy_conversion_factor` にある。

流儀は Enum と関数表ではなくオブジェクトにする（ADR-0033）。変換式・単位の有無・
振動数への依存の仕方を、流儀自身が知っている必要があるためである。

`docs/theory/vcc.md` の 5 流儀のうち、S への変換に振動数を要するのは V と lambda の
2 つで、この 2 つだけが単位を持つ。

| 流儀 | S への変換 | omega が要るか | coupling の次元 | 登録 |
|---|---|---|---|---|
| g | S = g^2 | 不要 | 無次元 | 済 |
| Delta | S = Delta^2 / 2 | 不要 | 無次元 | 済 |
| huang_rhys | 恒等 | 不要 | 無次元 | 済 |
| lambda | S = lambda / (h_bar omega) | 必要 | エネルギー^1 | 済 |
| vcc (V) | S = V^2 / (2 h_bar omega^3) | 必要 | 未確定 | 保留 |

V の次元が energy^1.5 に見えるのは h_bar = 1 の単位系に限った話で、相手が
eV/(A*sqrt(amu)) のような単位で出す場合は質量の次元が残る。`energy_power` が保証
するのは lambda までである（ADR-0055）。

"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from scipy import constants

from .errors import InvalidInputError, UnsupportedUnitError

__all__ = [
    "CANONICAL_ENERGY_UNIT",
    "COUPLING_CONVENTIONS",
    "DEFAULT_COUPLING_CONVENTION",
    "DELTA",
    "ENERGY_UNITS",
    "G",
    "HUANG_RHYS",
    "LAMBDA",
    "CouplingConvention",
    "coupling_convention",
    "energy_conversion_factor",
]

#: 内部で用いるエネルギーの単位。入力はここへ正準化される。振動数・sigma・グリッド・
#: 有次元の流儀の coupling が、どれもこの単位へ畳まれる（ADR-0002, 0054）。
CANONICAL_ENERGY_UNIT = "cm^-1"

#: 1 J を cm^-1 で表した値。他の係数はすべてこれを経由して導く。
_PER_JOULE = constants.value("joule-inverse meter relationship") / 100.0

#: 単位の名前 -> cm^-1 への換算係数。値に掛けると cm^-1 になる。
#:
#: 係数は `scipy.constants` から導出し、自前の数値定数表は持たない（ADR-0054）。
#: 単位を足す作業はこの表への 1 行で済む。波長（nm）は等間隔のエネルギーグリッドを
#: 表せないので入れない。
ENERGY_UNITS: dict[str, float] = {
    CANONICAL_ENERGY_UNIT: 1.0,
    "eV": constants.e * _PER_JOULE,
    "hartree": constants.value("Hartree energy") * _PER_JOULE,
    # 振動数だが eps = h*nu としてエネルギーに読む。
    "THz": 1.0e12 * constants.h * _PER_JOULE,
    # モルあたりの量なので、1 粒子あたりに直してから換算する。
    "kJ/mol": 1.0e3 / constants.N_A * _PER_JOULE,
    "kcal/mol": 1.0e3 * constants.calorie / constants.N_A * _PER_JOULE,
}


def energy_conversion_factor(unit: object) -> float:
    """エネルギーの単位から cm^-1 への換算係数を引く。

    受けるのは検証前のファイルの値なので `object` で取る。ハッシュできない値
    （辞書やリスト）も、`TypeError` ではなく他の未知の単位と同じ形で報告する。
    """
    try:
        return ENERGY_UNITS[unit]  # type: ignore[index]
    except (KeyError, TypeError) as exc:
        known = ", ".join(ENERGY_UNITS)
        raise UnsupportedUnitError(
            f"unsupported energy unit {unit!r} (known units: {known})"
        ) from exc


@dataclass(frozen=True, slots=True)
class CouplingConvention:
    """結合をどの量で書くかの選択。変換式と単位の扱いを自分で持つ。"""

    name: str
    """入力ファイルの `coupling_convention` に書く名前。"""

    energy_power: float | None
    """coupling の次元を「エネルギーの何乗か」で表したもの。None なら無次元。

    g / Delta / huang_rhys は None、lambda は 1.0。V は保留で、単一のべき指数で
    表せるかどうかも未確定である（ADR-0055）。

    coupling と frequency の単位が揃うことは前提にできない（ADR-0053）。frequency は
    ほぼ常に cm^-1 である一方、coupling の単位は値を出した相手プログラムの都合で
    決まるためである。したがって両者はそれぞれの単位から別々に正準単位へ直してから
    変換式に入る。`energy_power` はそのとき coupling の換算係数に乗せるべきである。
    """

    converter: Callable[[float, float], float]
    """(coupling, frequency) -> S。無次元の流儀は frequency を使わない。"""

    @property
    def is_dimensionless(self) -> bool:
        """単位を持たない流儀か。"""
        return self.energy_power is None

    def to_huang_rhys(self, coupling: float, frequency: float) -> float:
        """coupling を Huang-Rhys 因子 S に変換する。

        `coupling` も `frequency` も正準な単位（cm^-1）で与える。coupling の換算は
        `coupling_to_canonical` が行う。
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

    def coupling_to_canonical(self, unit: str | None) -> float:
        """coupling に掛けると正準単位になる係数。単位の妥当性もここで検査する。

        無次元の流儀では 1 である。有次元の流儀では、エネルギーの換算係数を
        `energy_power` 乗する。coupling の次元はエネルギーの整数乗とは限らないので
        （V は energy^1.5）、係数そのものではなくべきを取ったものが要る。

        係数を引くことと単位を検査することは分けられない。妥当でない単位に対して
        返せる係数がないためで、呼び出し側はこれ 1 つを呼べばよい。
        """
        self.check_coupling_unit(unit)
        power = self.energy_power
        if power is None or unit is None:
            return 1.0
        return energy_conversion_factor(unit) ** power


G = CouplingConvention(name="g", energy_power=None, converter=lambda g, _: g * g)
"""無次元化振電相互作用定数。S = g^2。g の符号は S に効かない（ADR-0003）。"""

DELTA = CouplingConvention(
    name="delta", energy_power=None, converter=lambda d, _: 0.5 * d * d
)
"""無次元変位。S = Delta^2 / 2。g とは Delta = sqrt(2) g の関係にある。"""

HUANG_RHYS = CouplingConvention(
    name="huang_rhys", energy_power=None, converter=lambda s, _: s
)
"""正準量そのもの。変換は恒等。"""

LAMBDA = CouplingConvention(
    name="lambda", energy_power=1.0, converter=lambda value, freq: value / freq
)
"""再配列エネルギー。S = lambda / eps。次元は energy^1 で確定している。

coupling も frequency もそれぞれの単位から正準単位へ直したうえで渡るので、この式は
どちらも cm^-1 として割ればよい（ADR-0053, 0054）。
"""

#: 名前 -> 流儀。流儀の追加は 1 エントリの追加で済む。
COUPLING_CONVENTIONS: dict[str, CouplingConvention] = {
    convention.name: convention for convention in (G, DELTA, HUANG_RHYS, LAMBDA)
}

#: 入力ファイルで `coupling_convention` を省略したときの流儀。
DEFAULT_COUPLING_CONVENTION = G


def coupling_convention(name: object) -> CouplingConvention:
    """名前から流儀を引く。未知の名前は `InvalidInputError`。

    受けるのは検証前のファイルの値なので `object` で取る。ハッシュできない値
    （辞書やリスト）も、`TypeError` ではなく他の未知の名前と同じ形で報告する。
    """
    try:
        return COUPLING_CONVENTIONS[name]  # type: ignore[index]
    except (KeyError, TypeError) as exc:
        known = ", ".join(sorted(COUPLING_CONVENTIONS))
        raise InvalidInputError(
            f"unknown coupling_convention {name!r} (known conventions: {known})"
        ) from exc
