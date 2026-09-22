"""入力ファイルの型（pydantic）と正準化。

このモジュールが扱うのは**ファイルの構造・単位・流儀**だけである。値の範囲は
計算用の値の型に任せ、値の型が送出したエラーにフィールドの位置を添える
（`docs/adr/0051-value-types-validate-their-own-invariants.md`）。

単位の軸は項目ごとに独立している（ADR-0053）。トップレベルの `frequency_unit` は
`modes[].frequency` だけに効き、sigma とグリッドは各ブロックの `unit` を持つ。

有次元の値は `[値, "単位"]` の組でも書け、そのときは添えた単位が既定より優先される
（ADR-0072）。3 つの書き方を 1 つの形へ畳むのは `Quantity` である。

トップレベルの `frequency_unit` / `coupling_convention` / `coupling_unit` は正準化の
際に消費され、
`to_system()` を通った後の表現は常に (frequency [cm^-1], huang_rhys) である。
変換が起こるのはこのモジュールの中だけで（ADR-0054）、以降のコードは流儀も単位も
知らない。

`modes` はモードの配列を直接書くか、`{"path": "modes.csv"}` で CSV のモード表を
参照する。参照はパース時に解決され、パース後は配列で書いた場合と区別がない。

`run` だけが読むブロック（`broadening` / `grid`）と `lines` だけが読むブロック
（`selection`）はどちらも省略でき、無いことが分かるのは読む側の `to_*` である
（ADR-0075）。構造の検査と「その命令に必要か」の判定は別の関心事である。

書式は TOML と JSON の 2 つで、拡張子で振り分ける（ADR-0069）。読んだ後は同じ辞書に
なるので、このモジュールの残りは書式を知らない。利用者が書くのは TOML で、JSON は
実効設定（`to_json`）を読み返す側に残っている。

書き始めるための雛形は `templates/input.toml` に実物のファイルとして持ち、`template_text`
がそれを読むだけである（ADR-0074）。
"""

from __future__ import annotations

import csv
import io
import json
import logging
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from .errors import InvalidInputError, SchemaVersionError
from .logs import stage
from .models import (
    Broadening,
    EnergyGrid,
    Selection,
    VibrationalMode,
    VibrationalSystem,
    validate_temperature,
)
from .units import (
    CANONICAL_ENERGY_UNIT,
    DEFAULT_COUPLING_CONVENTION,
    CouplingConvention,
    coupling_convention,
    energy_conversion_factor,
)

#: つまみの既定値の唯一の出どころ（ADR-0050）。`Selection` は slots 付きの
#: dataclass なのでクラス属性から既定値は読めず、既定のインスタンスから引く。
_DEFAULT_SELECTION = Selection()

logger = logging.getLogger(__name__)

__all__ = [
    "INPUT_FORMATS",
    "INPUT_TEMPLATE",
    "MODES_CSV_COLUMNS",
    "SCHEMA_VERSION",
    "BroadeningSpec",
    "EnergyGridSpec",
    "FCEnvelopeInput",
    "GridPointsSpec",
    "ModeSpec",
    "Quantity",
    "SelectionSpec",
    "read_mode_specs_csv",
    "template_text",
]

#: 入力ファイルの版（`docs/adr/0040-schema-version-2-without-a-compatibility-layer.md`）。
#: 古い版は互換層を置かずに拒否する。3 で `grid.de` が `grid.points` へ移った
#: （ADR-0070）。
SCHEMA_VERSION: Final = 3


def _at(location: str, exc: InvalidInputError) -> InvalidInputError:
    """値の型が送出したエラーに、入力ファイル中の位置を添える（ADR-0051）。"""
    return InvalidInputError(f"{location}: {exc}")


def _missing(block: str, command: str, what: str) -> InvalidInputError:
    """読む側から見て必要なブロックが書かれていないときの報告（ADR-0075）。

    どの命令がそれを必要とするかを添える。省略できるのは**読まない命令から見たとき**
    だけなので、「必須ではない」とだけ言うと直し方が分からない。
    """
    return InvalidInputError(f"{block}: required by `fcenvelope {command}` (add {what})")


@dataclass(frozen=True, slots=True)
class Quantity:
    """入力ファイル中の有次元の値（ADR-0072）。

    `150.0` / `[150.0]` / `[0.0186, "eV"]` の 3 つの書き方がここへ畳まれる。`unit` が
    `None` なら、その値はブロック（またはトップレベル）の単位で読む。
    """

    value: float
    unit: str | None = None

    def unit_or(self, default: str | None) -> str | None:
        """この値を読むときの単位。添えてなければ既定の単位。"""
        return self.unit if self.unit is not None else default

    def in_canonical(self, default: str) -> float:
        """既定の単位を補って正準単位（cm^-1）の数にする。"""
        return self.value * energy_conversion_factor(self.unit_or(default))


#: 有次元の値として受け付ける書き方。誤りの報告にそのまま載せる。
_QUANTITY_FORMS: Final = 'a number, [value] or [value, "unit"]'


def _to_quantity(written: object) -> object:
    """入力ファイルに書かれた有次元の値を `Quantity` にする（ADR-0072）。

    受けるのは検証前のファイルの値なので `object` で取る。単位が換算表にあることは
    ここで確かめ、保つのは名前のままである。単位と流儀の噛み合わせは正準化で見る。
    """
    if isinstance(written, Quantity):
        return written
    if isinstance(written, list):
        if not 1 <= len(written) <= 2:
            raise ValueError(f"expected {_QUANTITY_FORMS}, got {written!r}")
        number = written[0]
        unit = written[1] if len(written) == 2 else None
    else:
        number, unit = written, None
    if unit is not None:
        energy_conversion_factor(unit)  # 未知の単位・型はここで報告される
        unit = str(unit)
    return Quantity(value=_to_number(number), unit=unit)


def _to_number(written: object) -> float:
    """有次元の値の数の部分。CSV から来る文字列もここで数にする。"""
    if isinstance(written, bool) or not isinstance(written, int | float | str):
        raise ValueError(f"expected {_QUANTITY_FORMS}, got {written!r}")
    try:
        return float(written)
    except ValueError as exc:
        raise ValueError(f"expected {_QUANTITY_FORMS}, got {written!r}") from exc


def _as_written(quantity: Quantity) -> float | list[object]:
    """`Quantity` を書かれたままの姿へ戻す。実効設定の書き出しに使う（ADR-0065）。"""
    if quantity.unit is None:
        return quantity.value
    return [quantity.value, quantity.unit]


#: 有次元の値のフィールド。3 つの書き方を `Quantity` へ畳み、書き出しでは元の姿へ戻す。
Dimensioned = Annotated[
    Quantity, BeforeValidator(_to_quantity), PlainSerializer(_as_written)
]


class _Spec(BaseModel):
    """入力ファイル中の 1 ブロック。構造だけを検査する。"""

    model_config = ConfigDict(frozen=True, extra="forbid")


class _EnergySpec(_Spec):
    """エネルギーの単位を自分で持つブロック。

    単位の軸は項目ごとに独立で、入力ファイル全体で 1 つにはしない（ADR-0053）。
    sigma とグリッドは同じエネルギー軸上の量だが、出どころが違うので指定は
    ブロックごとに分けて持つ。省略時は正準単位である。

    ここの `unit` はブロックの**既定**で、値が自分で単位を持っていればそちらが勝つ
    （ADR-0072）。
    """

    unit: str = CANONICAL_ENERGY_UNIT

    @field_validator("unit", mode="before")
    @classmethod
    def _check_unit(cls, value: object) -> str:
        """単位が換算表にあることを確かめる。保つのは名前のままである。"""
        energy_conversion_factor(value)  # 未知の単位・型はここで報告される
        return str(value)

    def to_canonical(self, quantity: Quantity) -> float:
        """このブロックの値を cm^-1 の数にする。単位はブロックの `unit` で補う。"""
        return quantity.in_canonical(self.unit)


class ModeSpec(_Spec):
    """入力ファイル中の 1 モード。`coupling` の意味は流儀に依存する。

    単位の既定はモードごとではなくトップレベルに置く。CSV でモードを渡すときも
    既定を担うのは入力ファイルの側である（ADR-0019, 0053）。個々の値に組の形で
    単位を添えることはできる（ADR-0072）が、CSV には数しか書けない。
    """

    frequency: Dimensioned
    coupling: Dimensioned


class BroadeningSpec(_EnergySpec):
    """線形状のブロック。"""

    sigma: Dimensioned


class GridPointsSpec(_Spec):
    """全域グリッドの取り方のブロック（`grid.points`）。

    FFT の基数は 2 の冪なので、グリッド数 `n` を直接書くのが素直な指定である。
    丸い dE が欲しいときのために、その下位の書き方として `de` を置く（ADR-0070）。
    `n` と `de` はどちらか一方だけを書く。`shift` は `de` と一緒のときだけ意味を持つ。

    `de` の単位は親の `grid.unit` に従う。`n` と `shift` は無次元である。
    """

    n: int | None = None
    """全域グリッドの点数。2 の冪のみ。dE = 全域幅 / n は端数になりうる。"""

    de: Dimensioned | None = None
    """出力グリッド間隔。これを満たす最小の 2 の冪が n になる。"""

    shift: int = 0
    """`de` 指定のときだけ使う、冪のずらし幅。

    全域幅は変えずに n を 2^shift 倍する。刻みは 2^shift 分の 1 に細かくなる。
    """

    @model_validator(mode="after")
    def _exactly_one_way(self) -> "GridPointsSpec":
        """指定の仕方が 1 つに決まっていることを確かめる（構造だけ、値は見ない）。"""
        if (self.n is None) == (self.de is None):
            raise ValueError("write exactly one of n or de")
        if self.n is not None and self.shift:
            raise ValueError("shift applies to de only; n is already the grid count")
        return self


class EnergyGridSpec(_EnergySpec):
    """エネルギーグリッドのブロック。`e_min` / `e_max` は出力窓である。"""

    e_min: Dimensioned
    e_max: Dimensioned
    points: GridPointsSpec


class SelectionSpec(_Spec):
    """選択条件のブロック。省略されたつまみは `Selection` の既定値になる。"""

    min_weight: float = _DEFAULT_SELECTION.min_weight
    max_lines: int = _DEFAULT_SELECTION.max_lines
    max_quanta: int | None = _DEFAULT_SELECTION.max_quanta


#: モード表 CSV の列。ヘッダを省略した場合はこの順に並んでいるものとする。
MODES_CSV_COLUMNS = ("frequency", "coupling")


def read_mode_specs_csv(path: str | Path) -> list[ModeSpec]:
    """モード表 CSV（RFC 4180）を読み込む。

    列はちょうど `MODES_CSV_COLUMNS` の 2 列。ヘッダは省略でき、1 行目がこの列名の
    組（順序は問わない）ならヘッダとして扱い、そうでなければ `frequency, coupling`
    の順のデータ行として扱う。列名は数値にならないため、この判定は曖昧にならない。
    RFC 4180 にないコメント行は受け付けず、空行は空のレコードとしてエラーにする。
    `coupling` の流儀と単位は参照元の入力ファイルに従う。

    見るのは構造と数値として読めるかまでで、値の範囲は検査しない（ADR-0051）。
    """
    p = Path(path)
    try:
        with p.open(encoding="utf-8-sig", newline="") as stream:
            text = stream.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise InvalidInputError(f"cannot read modes file {p}: {exc}") from exc

    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        records = [(reader.line_num, fields) for fields in reader]
    except csv.Error as exc:
        raise InvalidInputError(f"{p}:{reader.line_num}: malformed CSV: {exc}") from exc

    if not records:
        raise InvalidInputError(f"{p}: modes file is empty")
    first = records[0][1]
    has_header = len(first) == len(MODES_CSV_COLUMNS) and set(first) == set(MODES_CSV_COLUMNS)
    columns = first if has_header else list(MODES_CSV_COLUMNS)
    rows = records[1:] if has_header else records
    if not rows:
        raise InvalidInputError(f"{p}: modes file has no mode rows")

    specs: list[ModeSpec] = []
    for index, (lineno, fields) in enumerate(rows):
        location = f"{p}:{lineno}"
        hint = (
            f" (a header, if present, must consist of exactly the columns "
            f"{list(MODES_CSV_COLUMNS)})"
            if index == 0 and not has_header
            else ""
        )
        if len(fields) != len(columns):
            blank = " (blank lines are not allowed)" if not fields else ""
            raise InvalidInputError(
                f"{location}: expected {len(columns)} fields, got {len(fields)}{blank}{hint}"
            )
        try:
            specs.append(ModeSpec.model_validate(dict(zip(columns, fields))))
        except ValidationError as exc:
            raise InvalidInputError(f"{location}: {exc}{hint}") from exc
    logger.info("read %d modes from %s", len(specs), p)
    return specs


def _as_text(text: str | bytes) -> str:
    """バイト列で渡された入力を UTF-8 のテキストにする。"""
    if isinstance(text, bytes):
        try:
            return text.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidInputError(f"input file must be UTF-8 text: {exc}") from exc
    return text


def _parse_toml(text: str) -> object:
    """TOML のテキストを辞書にする。"""
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise InvalidInputError(f"invalid TOML: {exc}") from exc


def _parse_json(text: str) -> object:
    """JSON のテキストを辞書にする。"""
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidInputError(f"invalid JSON: {exc}") from exc


#: 拡張子 -> テキストを辞書にする関数（ADR-0049, 0069）。入力ファイルの**書式**を
#: 知っているのはこの表だけで、以降の検証・正準化はどちらの書式でも同じ辞書を見る。
#: 書式を足すときはここに 1 行足す。
INPUT_FORMATS: dict[str, Callable[[str], object]] = {
    ".toml": _parse_toml,
    ".json": _parse_json,
}


def _parser_for(path: Path) -> Callable[[str], object]:
    """拡張子から書式を決める。中身は見ない（ADR-0069）。

    中身から推測すると、書き間違えた TOML が JSON として読まれて別の失敗の仕方を
    するなど、誤りの報告が読みにくくなる。拡張子が分からなければその場で止める。
    """
    parse = INPUT_FORMATS.get(path.suffix.lower())
    if parse is None:
        known = ", ".join(sorted(INPUT_FORMATS))
        raise InvalidInputError(
            f"cannot tell the format of input file {path} from its extension "
            f"{path.suffix!r} (expected one of {known})"
        )
    return parse


#: 入力ファイルの雛形。パッケージデータとして `templates/` に置く（ADR-0074）。
INPUT_TEMPLATE: Final = "input.toml"


def template_text() -> str:
    """入力ファイルの雛形のテキスト（ADR-0074）。

    雛形は作図スクリプトのそれと同じく**実物のファイル**で、ここは読むだけである
    （ADR-0059）。項目ごとの短いコメントが雛形の中身なので、コメントを書けない JSON の
    雛形は置かない。
    """
    return (
        resources.files(__package__)
        .joinpath("templates", INPUT_TEMPLATE)
        .read_text(encoding="utf-8")
    )


class FCEnvelopeInput(BaseModel):
    """入力ファイル全体。

    `run` は `temperature` / `broadening` / `grid` を、`lines` は `temperature` /
    `selection` を読む。どちらの副命令も同じファイルを使える（ADR-0005）。

    片方だけが読むブロックはどれも省略でき、読む命令に必要なものが無いことは
    `to_broadening()` / `to_grid()` が言う（ADR-0075）。`lines` しか使わない入力に
    使われないグリッドを書かせない、というのがこの形の狙いである。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[3] = SCHEMA_VERSION
    frequency_unit: str = CANONICAL_ENERGY_UNIT
    coupling_convention: str = DEFAULT_COUPLING_CONVENTION.name
    """流儀の**名前**。流儀そのものは `convention` から引く。

    ファイルに現れるのは名前なので、pydantic のフィールドも名前のままにする。
    こうしておくと `model_dump()` がそのまま入力ファイルの形に戻り、CLI の上書きが
    同じ経路を通れる（ADR-0050）。
    """

    coupling_unit: str | None = None
    """有次元の流儀の `coupling` の単位。無次元の流儀では書いてはならない。

    位置はトップレベルで、モードごとではない。CSV でモードを渡すときも単位を担うのは
    入力ファイルの側である（ADR-0019, 0053）。
    """

    modes: list[ModeSpec] = Field(min_length=1)
    temperature: float

    broadening: BroadeningSpec | None = None
    """線形状のブロック。`run` だけが読む（ADR-0075）。"""

    grid: EnergyGridSpec | None = None
    """エネルギーグリッドのブロック。`run` だけが読む（ADR-0075）。"""

    selection: SelectionSpec = SelectionSpec()
    """選択条件のブロック。`lines` だけが読む。

    こちらは省略すると既定値で埋まる。σ や E 窓と違って、つまみの既定値には
    分子によらない意味があるからである（ADR-0021, 0075）。
    """

    # pydantic の `mode="before"` の検証器は**検証前**の値を受ける。構造が分からない
    # 位置なので `object` で取り、pydantic に渡し返すものだけを返す。

    @field_validator("schema_version", mode="before")
    @classmethod
    def _check_schema_version(cls, value: object) -> Literal[3]:
        if value != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"unsupported schema_version {value!r} (this build supports {SCHEMA_VERSION})"
            )
        return SCHEMA_VERSION

    @field_validator("modes", mode="before")
    @classmethod
    def _resolve_modes_file(cls, value: object, info: ValidationInfo) -> object:
        """`{"path": ...}` を CSV から読んだモードの並びに置き換える。

        相対パスは検証コンテキストの `base_dir`（`from_path` では入力ファイルの
        ディレクトリ）を基準に解決する。
        """
        if not isinstance(value, dict):
            return value
        path = value.get("path")
        if set(value) != {"path"} or not isinstance(path, str) or not path:
            raise ValueError('modes must be a list of modes or {"path": "<modes>.csv"}')
        base_dir = Path((info.context or {}).get("base_dir") or ".")
        return read_mode_specs_csv(base_dir / path)

    @field_validator("frequency_unit", mode="before")
    @classmethod
    def _check_frequency_unit(cls, value: object) -> str:
        """単位が換算表にあることを確かめる。保つのは名前のままである。"""
        energy_conversion_factor(value)  # 未知の単位・型はここで報告される
        return str(value)

    @field_validator("coupling_convention", mode="before")
    @classmethod
    def _check_coupling_convention(cls, value: object) -> str:
        """名前が既知の流儀を指すことを確かめる。保つのは名前のままである。"""
        coupling_convention(value)  # 未知の名前・型はここで報告される
        return str(value)

    @field_validator("coupling_unit", mode="before")
    @classmethod
    def _check_coupling_unit(cls, value: object) -> str | None:
        """単位が換算表にあることを確かめる。流儀との噛み合わせは正準化で見る。

        省略（`None`）はここでは通す。単位が要るかどうかは流儀が決めることなので、
        流儀の分からないこの位置では判定できない。
        """
        if value is None:
            return None
        energy_conversion_factor(value)  # 未知の単位・型はここで報告される
        return str(value)

    @property
    def convention(self) -> CouplingConvention:
        """`coupling_convention` の名前が指す流儀オブジェクト。"""
        return coupling_convention(self.coupling_convention)

    def to_system(self) -> VibrationalSystem:
        """単位と流儀を消費して正準形の系を返す。"""
        convention = self.convention
        modes: list[VibrationalMode] = []
        for index, spec in enumerate(self.modes):
            # 軸は独立なので、frequency と coupling はそれぞれの単位から別々に正準単位
            # へ直す（ADR-0053）。単位はモードが自分で持っていればそれ、なければ
            # トップレベルの既定である（ADR-0072）。coupling の係数は流儀の次元の
            # ぶんだけべきが乗る。
            try:
                frequency = spec.frequency.in_canonical(self.frequency_unit)
                coupling = spec.coupling.value * convention.coupling_to_canonical(
                    spec.coupling.unit_or(self.coupling_unit)
                )
            except InvalidInputError as exc:
                raise _at(f"modes[{index}]", exc) from exc
            try:
                modes.append(
                    VibrationalMode(
                        frequency=frequency,
                        huang_rhys=convention.to_huang_rhys(coupling, frequency),
                    )
                )
            except InvalidInputError as exc:
                raise _at(f"modes[{index}]", exc) from exc
        return VibrationalSystem(modes)

    def to_broadening(self) -> Broadening:
        """単位を消費して線形状を計算用の値にする。

        ブロックが無ければここで止める。σ は現象論的なモデルパラメータで分子ごとに
        決まるから、既定値では埋めない（ADR-0021, 0035, 0075）。
        """
        if self.broadening is None:
            raise _missing("broadening", "run", "a [broadening] block with sigma")
        try:
            return Broadening(sigma=self.broadening.to_canonical(self.broadening.sigma))
        except InvalidInputError as exc:
            raise _at("broadening", exc) from exc

    def to_grid(self) -> EnergyGrid:
        """単位を消費してエネルギーグリッドを計算用の値にする。

        全域グリッドの解決（2 の冪への丸め、`shift` の適用）は `EnergyGrid` の
        コンストラクタが持つ。ここが決めるのは**どちらの書き方か**だけである
        （ADR-0070）。

        ブロックが無ければここで止める。E 窓に分子によらない既定値は無い（ADR-0075）。
        """
        if self.grid is None:
            raise _missing(
                "grid",
                "run",
                "a [grid] block with e_min, e_max and [grid.points]",
            )
        e_min = self.grid.to_canonical(self.grid.e_min)
        e_max = self.grid.to_canonical(self.grid.e_max)
        points = self.grid.points
        try:
            if points.n is not None:
                return EnergyGrid.from_points(e_min=e_min, e_max=e_max, n=points.n)
            assert points.de is not None  # `_exactly_one_way` が保証する
            return EnergyGrid.from_spacing(
                e_min=e_min,
                e_max=e_max,
                de=self.grid.to_canonical(points.de),
                shift=points.shift,
            )
        except InvalidInputError as exc:
            raise _at("grid", exc) from exc

    def to_selection(self) -> Selection:
        """選択条件を計算用の値にする。"""
        try:
            return Selection(
                min_weight=self.selection.min_weight,
                max_lines=self.selection.max_lines,
                max_quanta=self.selection.max_quanta,
            )
        except InvalidInputError as exc:
            raise _at("selection", exc) from exc

    def to_temperature(self) -> float:
        """温度を検証して返す。"""
        try:
            return validate_temperature(self.temperature)
        except InvalidInputError as exc:
            raise _at("temperature", exc) from exc

    def to_json(self) -> str:
        """実効設定の JSON テキスト（ADR-0065）。

        書き出すのは正準化**前**の姿、すなわち入力ファイルと同じ単位・流儀の値である。
        省略された項目は既定値で埋まり、`{"path": ...}` で渡したモードは行に展開されて
        埋め込まれる。この文字列をそのまま入力ファイルとして与えれば、同じ計算が再現
        できる。結果ファイルの入力エコーが正準形なのとは狙いが違う（ADR-0010, 0065）。

        有次元の値は書いたままの姿で出る。素の数値で書けば素の数値、組で書けば組で
        ある（ADR-0072）。単位フィールドは既定値で埋まって必ず書かれるので、どちらで
        書いてもこのファイルだけを見れば単位は分かる。

        書き出しは TOML ではなく JSON である。機械が書いて機械が読み返すファイルなので、
        `max_quanta` の `null` をそのまま書ける書式のほうが都合がよい（ADR-0069）。
        """
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"

    def save(self, path: str | Path) -> None:
        """実効設定を書き出す。`from_path` で読み返せる形である（ADR-0065）。"""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with stage(logger, f"write {target}"):
            target.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def from_obj(
        cls, data: object, *, base_dir: str | Path | None = None
    ) -> "FCEnvelopeInput":
        """辞書から生成する。pydantic の検証失敗は `InvalidInputError` になる。

        `base_dir` は `modes.path` の相対パスの基準。省略時はカレントディレクトリ。
        """
        try:
            return cls.model_validate(data, context={"base_dir": base_dir})
        except ValidationError as exc:
            raise InvalidInputError(str(exc)) from exc

    @classmethod
    def from_toml(
        cls, text: str | bytes, *, base_dir: str | Path | None = None
    ) -> "FCEnvelopeInput":
        """TOML 文字列から生成する。"""
        return cls.from_obj(_parse_toml(_as_text(text)), base_dir=base_dir)

    @classmethod
    def from_json(
        cls, text: str | bytes, *, base_dir: str | Path | None = None
    ) -> "FCEnvelopeInput":
        """JSON 文字列から生成する。"""
        return cls.from_obj(_parse_json(_as_text(text)), base_dir=base_dir)

    @classmethod
    def from_path(cls, path: str | Path) -> "FCEnvelopeInput":
        """入力ファイルを読み込む。`modes.path` はこのファイルからの相対パス。

        書式は拡張子で決まる（`.toml` / `.json`、ADR-0069）。どちらで書いても読んだ
        後は同じで、以降の扱いは変わらない。
        """
        p = Path(path)
        parse = _parser_for(p)
        with stage(logger, f"read {p}"):
            try:
                text = p.read_text(encoding="utf-8")
            except OSError as exc:
                raise InvalidInputError(f"cannot read input file {p}: {exc}") from exc
            except UnicodeDecodeError as exc:
                raise InvalidInputError(f"input file {p} must be UTF-8 text: {exc}") from exc
            return cls.from_obj(parse(text), base_dir=p.parent)
