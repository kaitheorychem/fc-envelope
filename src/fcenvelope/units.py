"""単位と振電相互作用の流儀。

エネルギーの正準単位は cm^-1 で、入力に現れる単位はすべてここへ換算される
（ADR-0002, 0054）。換算係数の表は `ENERGY_UNITS`、引き当ては
`ENERGY_UNIT_KIND.resolve`（と薄い `energy_conversion_factor`）にある。

単位の文字列は**正式名**・**別名**・**倍率**の 3 つからなる（ADR-0076）。別名は
入力ファイルでだけ使える書き方で、どの欄に書かれたか（単位の種類 `UnitKind`）で
正式名が決まる。倍率は名前の前に空白で区切って置く正の数である。`resolve` は
別名を正式名へ置き換えた**正式形**と、倍率を掛けた換算係数を返す。

流儀は Enum と関数表ではなくオブジェクトにする（ADR-0033）。変換式・単位の有無・
振動数への依存の仕方を、流儀自身が知っている必要があるためである。

`docs/theory/vcc.md` の 5 流儀のうち、S への変換に振動数を要するのは V と lambda の
2 つで、この 2 つだけが単位を持つ。

| 流儀 | S への変換 | omega が要るか | coupling の正準単位 | 登録 |
|---|---|---|---|---|
| g | S = g^2 | 不要 | 無次元 | 済 |
| Delta | S = Delta^2 / 2 | 不要 | 無次元 | 済 |
| huang_rhys | 恒等 | 不要 | 無次元 | 済 |
| lambda | S = lambda / (h_bar omega) | 必要 | cm^-1 | 済 |
| vcc (V) | S = V^2 / (2 h_bar omega^3) | 必要 | (cm^-1)^{3/2} | 済 |

coupling の単位の種類は流儀が持つ（`CouplingConvention.unit_kind`）。V を
「エネルギーの 1.5 乗」というべき指数で持たないのは、`eV` のような実在しない V の
単位まで受け付けてしまい、逆に質量を含む実在の単位は表せないからである（ADR-0077）。

"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final

from scipy import constants

from .errors import InvalidInputError, UnsupportedUnitError

__all__ = [
    "CANONICAL_ENERGY_UNIT",
    "COUPLING_CONVENTIONS",
    "DEFAULT_COUPLING_CONVENTION",
    "DELTA",
    "ENERGY_UNITS",
    "ENERGY_UNIT_ALIASES",
    "ENERGY_UNIT_KIND",
    "G",
    "HUANG_RHYS",
    "LAMBDA",
    "UNIT_FORMS",
    "VCC",
    "VCC_UNIT",
    "VCC_UNIT_KIND",
    "CouplingConvention",
    "ResolvedUnit",
    "UnitKind",
    "coupling_convention",
    "energy_conversion_factor",
    "split_unit",
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


#: 受け付ける単位の書き方。誤りの報告にそのまま載せる（ADR-0076）。
UNIT_FORMS: Final = '"<name>" or "<scale> <name>"'

#: 倍率として受け付ける字面。小数・指数表記か、10 の整数乗（ADR-0076）。負号は
#: ここで弾かれる。
_SCALE = re.compile(r"[+]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?|10\^([+-]?\d+)")


def _scale_value(text: str) -> float:
    """倍率の字面を数にする。正の有限な数でなければ `ValueError`。"""
    match = _SCALE.fullmatch(text)
    if match is None:
        raise ValueError(f"the scale {text!r} is not a number")
    exponent = match.group(4)
    # 10^k は float(1ek) として読む。10.0**k は大きな k で OverflowError になるが、
    # こちらは inf / 0 になるので下の検査 1 つで報告できる。
    value = float(f"1e{exponent}") if exponent is not None else float(text)
    if not (value > 0.0 and math.isfinite(value)):
        raise ValueError(f"the scale {text!r} must be a positive finite number")
    return value


def _split(written: object) -> tuple[str | None, str]:
    """単位の文字列を (倍率の字面, 名前) に分ける。書き方の誤りは `ValueError`。"""
    if not isinstance(written, str):
        raise ValueError("a unit must be a string")
    words = written.split()
    if len(words) == 1:
        return None, words[0]
    if len(words) == 2:
        _scale_value(words[0])
        return words[0], words[1]
    if not words:
        raise ValueError("the unit is empty")
    raise ValueError("too many words")


def split_unit(written: object) -> tuple[str | None, str]:
    """単位の文字列を (倍率の字面, 名前) に分ける（ADR-0076）。

    単位の種類に依存しない**書き方だけ**の検査である。名前が既知かどうかは見ない。
    流儀が分かる前の coupling の欄が、これで書き方だけを確かめる。

    前後の空白を除いて空白で区切り、1 語なら名前、2 語なら倍率と名前とする。
    倍率は正の有限な数でなければならない。
    """
    try:
        return _split(written)
    except ValueError as exc:
        raise UnsupportedUnitError(
            f"malformed unit {written!r}: {exc} (write {UNIT_FORMS})"
        ) from exc


@dataclass(frozen=True, slots=True)
class ResolvedUnit:
    """`UnitKind.resolve` の結果。"""

    text: str
    """正式形。別名を正式名に置き換え、倍率は書かれた字面のまま前に置いたもの。"""

    factor: float
    """値に掛けると正準単位になる係数。倍率 × 正式名の係数である。"""


@dataclass(frozen=True, slots=True, eq=False)
class UnitKind:
    """単位の種類。その欄の値がどの次元の量かの区別（ADR-0076）。

    正式名の表と別名の表を持つ。同じ別名（`a.u.`）でも、種類が違えば違う正式名を
    指す。インスタンスはモジュールに 1 つずつ置く定数なので、等しさは同一性で見る。
    """

    name: str
    """誤りの報告に使う名前。"""

    factors: Mapping[str, float]
    """正式名 -> 正準単位への係数。"""

    aliases: Mapping[str, str]
    """別名 -> 正式名。入力ファイルでだけ使える。"""

    def _describe(self) -> str:
        known = ", ".join(self.factors)
        aliases = ", ".join(f"{alias} = {name}" for alias, name in self.aliases.items())
        return (
            f"known units: {known}"
            + (f"; aliases: {aliases}" if aliases else "")
            + f"; write {UNIT_FORMS}"
        )

    def resolve(self, written: object) -> ResolvedUnit:
        """書かれた単位を正式形と換算係数にする。

        受けるのは検証前のファイルの値なので `object` で取る。文字列でない値・書き方の
        誤り・未知の名前は、どれも `UnsupportedUnitError` として同じ形で報告する。
        正式形を渡せば同じ正式形が返る（冪等）。
        """
        try:
            scale, name = _split(written)
        except ValueError as exc:
            raise UnsupportedUnitError(
                f"unsupported {self.name} unit {written!r}: {exc} ({self._describe()})"
            ) from exc
        formal = self.aliases.get(name, name)
        if formal not in self.factors:
            raise UnsupportedUnitError(
                f"unsupported {self.name} unit {written!r} ({self._describe()})"
            )
        factor = self.factors[formal]
        if scale is None:
            return ResolvedUnit(text=formal, factor=factor)
        return ResolvedUnit(text=f"{scale} {formal}", factor=_scale_value(scale) * factor)


#: 別名 -> エネルギーの単位の正式名。入力ファイルでだけ使える（ADR-0076）。
ENERGY_UNIT_ALIASES: dict[str, str] = {
    "a.u.": "hartree",
}

#: エネルギーの単位の種類。振動数・sigma・グリッドと、流儀 lambda の coupling の欄。
ENERGY_UNIT_KIND = UnitKind(
    name="energy", factors=ENERGY_UNITS, aliases=ENERGY_UNIT_ALIASES
)


def energy_conversion_factor(unit: object) -> float:
    """エネルギーの単位から cm^-1 への換算係数を引く。

    `ENERGY_UNIT_KIND.resolve(unit).factor` の薄い包みで、別名も倍率も受ける。
    """
    return ENERGY_UNIT_KIND.resolve(unit).factor


#: 振電相互作用定数 V の正式名（ADR-0077）。質量重み付き基準座標 Q = sqrt(m) x に
#: ついての dE/dQ で、質量は電子の質量で測る。
VCC_UNIT = "hartree/(bohr*sqrt(m_e))"

#: 振電相互作用定数 V の単位の種類。正準単位は (cm^-1)^{3/2} である。
VCC_UNIT_KIND = UnitKind(
    name="vibronic coupling constant",
    # 原子単位では E_h = h_bar^2 / (m_e a_0^2) なので 1 E_h/(a_0 sqrt(m_e)) =
    # E_h^{3/2} h_bar^{-1/2}。h_bar = 1 と置けば E_h を cm^-1 で表した数の 1.5 乗になる。
    factors={VCC_UNIT: ENERGY_UNITS["hartree"] ** 1.5},
    aliases={"a.u.": VCC_UNIT},
)


@dataclass(frozen=True, slots=True)
class CouplingConvention:
    """結合をどの量で書くかの選択。変換式と単位の扱いを自分で持つ。"""

    name: str
    """入力ファイルの `coupling_convention` に書く名前。"""

    unit_kind: UnitKind | None
    """coupling の単位の種類。None なら無次元。

    g / Delta / huang_rhys は None、lambda はエネルギー（`ENERGY_UNIT_KIND`）、vcc は
    振電相互作用定数（`VCC_UNIT_KIND`）である（ADR-0076, 0077）。

    coupling と frequency の単位が揃うことは前提にできない（ADR-0053）。frequency は
    ほぼ常に cm^-1 である一方、coupling の単位は値を出した相手プログラムの都合で
    決まるためである。したがって両者はそれぞれの単位から別々に正準単位へ直してから
    変換式に入る。
    """

    converter: Callable[[float, float], float]
    """(coupling, frequency) -> S。無次元の流儀は frequency を使わない。"""

    @property
    def is_dimensionless(self) -> bool:
        """単位を持たない流儀か。"""
        return self.unit_kind is None

    def to_huang_rhys(self, coupling: float, frequency: float) -> float:
        """coupling を Huang-Rhys 因子 S に変換する。

        `coupling` も `frequency` も正準な単位（cm^-1）で与える。coupling の換算は
        `coupling_to_canonical` が行う。
        """
        return self.converter(coupling, frequency)

    def check_coupling_unit(self, unit: str | None) -> None:
        """coupling に添えられた単位が、この流儀にとって妥当かを検査する。

        無次元の流儀に単位を添えるのは誤りであり、単位を持つ流儀では単位が要る。
        `None` は単位が書かれていないことを表す。
        """
        if self.is_dimensionless:
            if unit is not None:
                raise InvalidInputError(
                    f"coupling_convention {self.name!r} is dimensionless; "
                    f"a coupling unit ({unit!r}) must not be given"
                )
            return
        if unit is None:
            assert self.unit_kind is not None  # is_dimensionless で分けた
            raise UnsupportedUnitError(
                f"coupling_convention {self.name!r} carries units "
                f"({self.unit_kind.name}); a coupling unit must be given"
            )

    def coupling_to_canonical(self, unit: str | None) -> float:
        """coupling に掛けると正準単位になる係数。単位の妥当性もここで検査する。

        無次元の流儀では 1 である。有次元の流儀では、流儀の単位の種類で単位を
        引き当てた係数（倍率込み）である。

        係数を引くことと単位を検査することは分けられない。妥当でない単位に対して
        返せる係数がないためで、呼び出し側はこれ 1 つを呼べばよい。
        """
        self.check_coupling_unit(unit)
        if self.unit_kind is None or unit is None:
            return 1.0
        return self.unit_kind.resolve(unit).factor


G = CouplingConvention(name="g", unit_kind=None, converter=lambda g, _: g * g)
"""無次元化振電相互作用定数。S = g^2。g の符号は S に効かない（ADR-0003）。"""

DELTA = CouplingConvention(
    name="delta", unit_kind=None, converter=lambda d, _: 0.5 * d * d
)
"""無次元変位。S = Delta^2 / 2。g とは Delta = sqrt(2) g の関係にある。"""

HUANG_RHYS = CouplingConvention(
    name="huang_rhys", unit_kind=None, converter=lambda s, _: s
)
"""正準量そのもの。変換は恒等。"""

LAMBDA = CouplingConvention(
    name="lambda",
    unit_kind=ENERGY_UNIT_KIND,
    converter=lambda value, freq: value / freq,
)
"""再配列エネルギー。S = lambda / eps。単位はエネルギーの単位である。

coupling も frequency もそれぞれの単位から正準単位へ直したうえで渡るので、この式は
どちらも cm^-1 として割ればよい（ADR-0053, 0054）。
"""

VCC = CouplingConvention(
    name="vcc",
    unit_kind=VCC_UNIT_KIND,
    converter=lambda v, eps: v * v / (2.0 * eps**3),
)
"""振電相互作用定数。S = V^2 / (2 eps^3)。V の符号は S に効かない（ADR-0077）。

V は正準単位 (cm^-1)^{3/2}、eps は cm^-1 で渡る。S は V^2 と eps^3 の比なので、
エネルギーの単位をそろえてさえいれば単位系によらない。
"""

#: 名前 -> 流儀。流儀の追加は 1 エントリの追加で済む。
COUPLING_CONVENTIONS: dict[str, CouplingConvention] = {
    convention.name: convention for convention in (G, DELTA, HUANG_RHYS, LAMBDA, VCC)
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
