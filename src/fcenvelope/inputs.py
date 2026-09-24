"""入力ファイルの型（pydantic）と正準化。

このモジュールが扱うのは**ファイルの構造・単位・流儀**だけである。値の範囲は
計算用の値の型に任せ、値の型が送出したエラーにフィールドの位置を添える
（`docs/adr/0051-value-types-validate-their-own-invariants.md`）。

単位の軸は項目ごとに独立している（ADR-0053）。単位の既定はそれを使うブロックが持ち、
トップレベルには置かない。モード表は列ごとの既定（`modes.frequency_unit` /
`modes.coupling_unit`）を、sigma とグリッドは各ブロックの `unit` を持つ（ADR-0079）。

有次元の値は `[値, "単位"]` の組でも書け、そのときは添えた単位が既定より優先される
（ADR-0072）。3 つの書き方を 1 つの形へ畳むのは `Quantity` である。

単位は検証を通った時点で**正式形**になっている（ADR-0076）。別名（`a.u.`）は欄の単位の
種類が決める正式名へ置き換わる。倍率は配列の要素として数で書き（`[0.0001, "a.u."]`、
値に添えるなら `[-0.3, 0.0001, "a.u."]`、ADR-0078）、そのまま残る。
エネルギーの欄は欄そのものが種類を決めるのでフィールドの検証器で置き換える。
coupling の欄は種類を流儀が決めるので、流儀の見えるモデルの検証器
（`ModesSpec._read_rows`）で置き換える。

`[modes]` の `frequency_unit` / `coupling_convention` / `coupling_unit` は正準化の
際に消費され、`to_system()` を通った後の表現は常に (frequency [cm^-1], huang_rhys) で
ある。
変換が起こるのはこのモジュールの中だけで（ADR-0054）、以降のコードは流儀も単位も
知らない。

モード表の行は `[[modes.rows]]` に直接書くか、`csv = {path = "modes.csv", columns = ...}`
で CSV の列の並びと単位を書いて読み込む（ADR-0079）。参照はパース時に解決され、パース
後は行を直接書いた場合と区別がない。

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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Annotated, Final, Literal, TypeVar

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

from .errors import InvalidInputError, SchemaVersionError, UnsupportedUnitError
from .logs import stage
from .models import (
    Broadening,
    EnergyGrid,
    Selection,
    VibrationalMode,
    VibrationalSystem,
    validate_frequency,
    validate_temperature,
)
from .units import (
    CANONICAL_ENERGY_UNIT,
    DEFAULT_COUPLING_CONVENTION,
    ENERGY_UNIT_KIND,
    CouplingConvention,
    UnitForm,
    coupling_convention,
    split_unit,
    unit_form,
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
    "CsvColumn",
    "EnergyGridSpec",
    "FCEnvelopeInput",
    "GridPointsSpec",
    "ModeSpec",
    "ModesSpec",
    "Quantity",
    "SelectionSpec",
    "read_csv_table",
    "read_mode_specs_csv",
    "template_text",
]

#: 入力ファイルの版（`docs/adr/0040-schema-version-2-without-a-compatibility-layer.md`）。
#: 古い版は互換層を置かずに拒否する。3 で `grid.de` が `grid.points` へ移り
#: （ADR-0070）、4 でモード表が単位と流儀を持つ `[modes]` ブロックになった（ADR-0079）。
SCHEMA_VERSION: Final = 4


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

    `150.0` / `[150.0]` / `[0.0186, "eV"]` / `[18.6, 0.001, "eV"]` の書き方がここへ
    畳まれる（ADR-0072, 0078）。`unit` が `None` なら、その値はブロック（または
    モード表の列）の既定の単位で読む。
    """

    value: float
    unit: UnitForm | None = None

    def unit_or(self, default: UnitForm | None) -> UnitForm | None:
        """この値を読むときの単位。添えてなければ既定の単位。"""
        return self.unit if self.unit is not None else default

    def in_canonical(self, default: UnitForm) -> float:
        """既定の単位を補って正準単位（cm^-1）の数にする。

        エネルギーの値のためのもので、coupling の換算は流儀が行う。保存されている
        単位は正式形で、正式形は冪等に読めるので、ここは別名も倍率も意識しない。
        """
        return self.value * ENERGY_UNIT_KIND.resolve(self.unit_or(default)).factor


#: 有次元の値として受け付ける書き方。誤りの報告にそのまま載せる。
_QUANTITY_FORMS: Final = 'a number, [value], [value, "unit"] or [value, scale, "unit"]'


def _split_value(written: list[object]) -> tuple[object, object | None]:
    """配列で書かれた有次元の値を (数, 単位の書き方) に分ける（ADR-0072, 0078）。

    `[値]` は単位なし、`[値, "単位"]` は名前だけ、`[値, 倍率, "単位"]` は倍率つきの
    単位である。倍率つきの単位は、単位の欄に書く `[倍率, "単位"]` の形にして返す。
    """
    if len(written) == 1:
        return written[0], None
    if len(written) == 2:
        return written[0], written[1]
    if len(written) == 3:
        return written[0], [written[1], written[2]]
    raise ValueError(f"expected {_QUANTITY_FORMS}, got {written!r}")


def _join_value(value: object, unit: UnitForm | None) -> float | list[object]:
    """`_split_value` の逆。数と単位の書き方を入力ファイルの書き方へ戻す。"""
    if unit is None:
        return value  # type: ignore[return-value]
    if isinstance(unit, str):
        return [value, unit]
    return [value, *unit]


def _energy_unit(written: object) -> UnitForm:
    """エネルギーの欄の単位を正式形にする（ADR-0076）。未知の単位・型はここで報告される。"""
    return ENERGY_UNIT_KIND.resolve(written).form


def _coupling_unit(written: object) -> UnitForm:
    """coupling の欄の単位の書き方だけを確かめ、そのまま保つ（ADR-0076）。

    この欄の単位の種類は流儀が決めるので、ここでは名前を引き当てない。有次元の流儀
    なら `ModesSpec._read_rows` がすでに正式形へ置き換えている。無次元の流儀に
    添えた単位は `to_system` が報告する。
    """
    return unit_form(*split_unit(written))


def _quantity_with(
    check_unit: Callable[[object], UnitForm],
) -> Callable[[object], object]:
    """単位の扱い方を決めて、書かれた有次元の値を `Quantity` にする関数を作る。"""

    def to_quantity(written: object) -> object:
        """入力ファイルに書かれた有次元の値を `Quantity` にする（ADR-0072）。

        受けるのは検証前のファイルの値なので `object` で取る。単位と流儀の噛み合わせは
        正準化で見る。
        """
        if isinstance(written, Quantity):
            return written
        if isinstance(written, list):
            number, unit = _split_value(written)
        else:
            number, unit = written, None
        return Quantity(
            value=_to_number(number),
            unit=None if unit is None else check_unit(unit),
        )

    return to_quantity


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
    return _join_value(quantity.value, quantity.unit)


#: エネルギーの値のフィールド。3 つの書き方を `Quantity` へ畳み、書き出しでは元の姿へ
#: 戻す。添えた単位は正式形になる。
Dimensioned = Annotated[
    Quantity,
    BeforeValidator(_quantity_with(_energy_unit)),
    PlainSerializer(_as_written),
]

#: coupling の値のフィールド。畳み方は `Dimensioned` と同じだが、単位は書き方だけを
#: 確かめて字面のまま保つ。種類を決める流儀がこの位置からは見えないためである。
DimensionedCoupling = Annotated[
    Quantity,
    BeforeValidator(_quantity_with(_coupling_unit)),
    PlainSerializer(_as_written),
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

    unit: UnitForm = CANONICAL_ENERGY_UNIT

    @field_validator("unit", mode="before")
    @classmethod
    def _check_unit(cls, value: object) -> UnitForm:
        """単位を正式形にする（ADR-0076）。"""
        return _energy_unit(value)

    def to_canonical(self, quantity: Quantity) -> float:
        """このブロックの値を cm^-1 の数にする。単位はブロックの `unit` で補う。"""
        return quantity.in_canonical(self.unit)


class ModeSpec(_Spec):
    """モード表の 1 行。`coupling` の意味は表の流儀に依存する。

    単位の既定は行ごとではなく表（`ModesSpec`）が持つ。個々の値に組の形で単位を
    添えることはでき（ADR-0072）、CSV から読んだ行では列に添えた単位がこの形で
    各値に添えられる（ADR-0079）。
    """

    frequency: Dimensioned
    coupling: DimensionedCoupling


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


#: CSV の 1 行から作る値の型。
_Row = TypeVar("_Row")


@dataclass(frozen=True, slots=True)
class CsvColumn:
    """CSV の 1 列。列名と、その列の値に添える単位（ADR-0079）。

    `unit` が `None` の列の値は単位を添えずに渡るので、表のブロックの既定の単位で
    読まれる。
    """

    name: str
    unit: UnitForm | None = None


def read_csv_table(
    path: str | Path,
    columns: Sequence[CsvColumn],
    build: Callable[[dict[str, object]], _Row],
    *,
    explicit: bool = False,
) -> list[_Row]:
    """表の CSV（RFC 4180）を読み、各行を「列名 -> 値」の辞書にする（ADR-0020, 0079）。

    列は `columns` の列をちょうど 1 回ずつ。ヘッダは省略でき、1 行目が列名の組
    （順序は問わない）ならヘッダとして扱う。列名は数値にならないため、この判定は
    曖昧にならない。ヘッダが無ければ `columns` の順に並んでいるものとする。
    ヘッダがあるとき、`explicit`（列の並びを入力ファイルに書いた）なら並びが一致
    しなければ誤り、そうでなければヘッダの並びで読む。

    値は列の単位を添えた形（`[値, "単位"]`）にしてから `build` に渡す。CSV を読んだ
    後は、行を直接書いた場合と区別がない。`build` の検証の誤りには `ファイル:行` を
    添える。RFC 4180 にないコメント行は受け付けず、空行は空のレコードとしてエラーに
    する。
    """
    p = Path(path)
    try:
        with p.open(encoding="utf-8-sig", newline="") as stream:
            text = stream.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise InvalidInputError(f"cannot read table file {p}: {exc}") from exc

    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        records = [(reader.line_num, fields) for fields in reader]
    except csv.Error as exc:
        raise InvalidInputError(f"{p}:{reader.line_num}: malformed CSV: {exc}") from exc

    if not records:
        raise InvalidInputError(f"{p}: table file is empty")
    names = [column.name for column in columns]
    first = records[0][1]
    has_header = len(first) == len(names) and set(first) == set(names)
    if has_header and explicit and first != names:
        raise InvalidInputError(
            f"{p}:{records[0][0]}: the header {first} does not match the columns "
            f"{names} given in the input file (write them in the same order, or "
            f"leave out one of them)"
        )
    order = first if has_header else names
    units = {column.name: column.unit for column in columns}
    rows = records[1:] if has_header else records
    if not rows:
        raise InvalidInputError(f"{p}: table file has no data rows")

    table: list[_Row] = []
    for index, (lineno, fields) in enumerate(rows):
        location = f"{p}:{lineno}"
        # 1 行目がヘッダにもデータ行にもならなかったときに添える案内
        hint = (
            f" (a header, if present, must consist of exactly the columns {names})"
            if index == 0 and not has_header
            else ""
        )
        if len(fields) != len(order):
            blank = " (blank lines are not allowed)" if not fields else ""
            raise InvalidInputError(
                f"{location}: expected {len(order)} fields, got {len(fields)}{blank}{hint}"
            )
        record = {
            name: _join_value(field, units[name])
            for name, field in zip(order, fields, strict=True)
        }
        try:
            table.append(build(record))
        except ValidationError as exc:
            raise InvalidInputError(f"{location}: {exc}{hint}") from exc
    logger.info("read %d rows from %s", len(table), p)
    return table


#: モード表の列。列の並びを書かなければこの順に並んでいるものとする（ADR-0079）。
MODES_CSV_COLUMNS = ("frequency", "coupling")


def read_mode_specs_csv(
    path: str | Path, columns: Sequence[CsvColumn] | None = None
) -> list[ModeSpec]:
    """モード表の CSV を読み込む。

    `columns` は列の並びと単位で、省略すると `MODES_CSV_COLUMNS` の順・単位なしで
    ある（ADR-0079）。単位を添えない列の値は `[modes]` の既定の単位で読まれる。
    見るのは構造と数値として読めるかまでで、値の範囲は検査しない（ADR-0051）。
    """
    explicit = columns is not None
    if columns is None:
        columns = [CsvColumn(name) for name in MODES_CSV_COLUMNS]
    return read_csv_table(path, columns, ModeSpec.model_validate, explicit=explicit)


def _csv_columns(
    written: object, units: dict[str, Callable[[object], UnitForm]]
) -> list[CsvColumn]:
    """入力ファイルに書かれた列の並びを `CsvColumn` の並びにする（ADR-0079）。

    各要素は列名か、列名に単位を添えた組（`["coupling", "a.u."]` /
    `["coupling", 1e-4, "a.u."]`）である。組の形は値に単位を添える形と同じで、値の
    位置に列名が入る。`units` は列名から、その列の単位を正式形にする関数を引く表で、
    この表の列をちょうど 1 回ずつ並べる。
    """
    location = "modes.csv.columns"
    forms = '"<column>", ["<column>", "<unit>"] or ["<column>", <scale>, "<unit>"]'
    if not isinstance(written, list):
        raise InvalidInputError(f"{location}: expected a list of columns, got {written!r}")
    columns: list[CsvColumn] = []
    for entry in written:
        name, unit = entry, None
        if isinstance(entry, list) and 1 <= len(entry) <= 3:
            name, unit = _split_value(entry)
        if not isinstance(name, str) or name not in units:
            raise InvalidInputError(
                f"{location}: expected {forms} with a column among {list(units)}, "
                f"got {entry!r}"
            )
        try:
            form = None if unit is None else units[name](unit)
        except (InvalidInputError, UnsupportedUnitError, ValueError) as exc:
            raise type(exc)(f"{location}: {name}: {exc}") from exc
        columns.append(CsvColumn(name, form))
    names = [column.name for column in columns]
    if sorted(names) != sorted(units):
        raise InvalidInputError(
            f"{location}: list each of the columns {list(units)} exactly once, got {names}"
        )
    return columns


class ModesSpec(_Spec):
    """モード表のブロック（`[modes]`、ADR-0079）。

    表の既定、すなわち coupling の流儀と各列の既定の単位を持つ。単位の軸は列ごとに
    独立している（ADR-0053）。行は `rows` に直接書くか、`csv` で CSV の列の並びと
    単位を書いて読み込む。CSV の参照はパース時に解決され、パース後は `rows` に
    直接書いた場合と区別がない。

    単位は検証を通った時点で正式形になっている（ADR-0076）。frequency の列は列その
    ものが種類を決めるのでフィールドの検証器で、coupling の列は種類を流儀が決めるので
    流儀の見えるモデルの検証器（`_read_rows`）で置き換える。
    """

    coupling_convention: str = DEFAULT_COUPLING_CONVENTION.name
    """流儀の**名前**。流儀そのものは `convention` から引く。

    ファイルに現れるのは名前なので、pydantic のフィールドも名前のままにする。
    こうしておくと `model_dump()` がそのまま入力ファイルの形に戻る（ADR-0050）。
    """

    frequency_unit: UnitForm = CANONICAL_ENERGY_UNIT
    """frequency の列の既定の単位。"""

    coupling_unit: UnitForm | None = None
    """coupling の列の既定の単位。有次元の流儀でだけ書き、無次元の流儀では書いては
    ならない。"""

    rows: list[ModeSpec] = Field(min_length=1)

    # pydantic の `mode="before"` の検証器は**検証前**の値を受ける。構造が分からない
    # 位置なので `object` で取り、pydantic に渡し返すものだけを返す。

    @model_validator(mode="before")
    @classmethod
    def _read_rows(cls, data: object, info: ValidationInfo) -> object:
        """coupling の単位を正式形へ置き換え、`csv` を読んだ行に差し替える。

        同じ `a.u.` でも、流儀 lambda なら `hartree`、vcc なら
        `hartree/(bohr*sqrt(m_e))` になる（ADR-0076）。フィールドの検証器からは流儀が
        見えないので、生の辞書の段階でここが置き換える。置き換えるのは形が分かる位置
        だけで、それ以外は触らずに残す。構造の誤りはフィールドの検証器が、流儀の名前の
        誤りは `_check_coupling_convention` が、無次元の流儀に添えた単位は `to_system`
        が報告する。

        `csv` の相対パスは検証コンテキストの `base_dir`（`from_path` では入力ファイルの
        ディレクトリ）を基準に解決する。呼び出し側の辞書は書き換えず、写しを返す。
        """
        if not isinstance(data, dict):
            return data
        try:
            kind = coupling_convention(
                data.get("coupling_convention", DEFAULT_COUPLING_CONVENTION.name)
            ).unit_kind
        except InvalidInputError:
            kind = None

        def resolve(location: str, written: object) -> UnitForm:
            if kind is None:
                return _coupling_unit(written)
            try:
                return kind.resolve(written).form
            except UnsupportedUnitError as exc:
                raise UnsupportedUnitError(f"{location}: {exc}") from exc

        resolved = dict(data)
        unit = resolved.get("coupling_unit")
        if kind is not None and isinstance(unit, str | list):
            resolved["coupling_unit"] = resolve("modes.coupling_unit", unit)
        rows = resolved.get("rows")
        if kind is not None and isinstance(rows, list):
            new_rows: list[object] = []
            for index, row in enumerate(rows):
                coupling = row.get("coupling") if isinstance(row, dict) else None
                # 単位が添えてある形（最後の要素が名前の 2 要素か 3 要素の配列）だけを
                # 置き換える。それ以外の形はフィールドの検証器が報告する。
                if (
                    isinstance(coupling, list)
                    and len(coupling) in (2, 3)
                    and isinstance(coupling[-1], str)
                ):
                    number, written = _split_value(coupling)
                    form = resolve(f"modes.rows[{index}].coupling", written)
                    row = {**row, "coupling": _join_value(number, form)}
                new_rows.append(row)
            resolved["rows"] = new_rows

        if "csv" not in resolved:
            if "rows" not in resolved:
                raise InvalidInputError(_ROWS_OR_CSV)
            return resolved
        if "rows" in resolved:
            raise InvalidInputError(f"{_ROWS_OR_CSV}, not both")
        reference = resolved.pop("csv")
        path = reference.get("path") if isinstance(reference, dict) else None
        if (
            not isinstance(reference, dict)
            or not set(reference) <= {"path", "columns"}
            or not isinstance(path, str)
            or not path
        ):
            raise InvalidInputError(
                'modes.csv: expected {path = "<modes>.csv"} with optional columns, '
                f"got {reference!r}"
            )
        columns = None
        if "columns" in reference:
            columns = _csv_columns(
                reference["columns"],
                {
                    "frequency": _energy_unit,
                    "coupling": lambda written: resolve("coupling", written),
                },
            )
        base_dir = Path((info.context or {}).get("base_dir") or ".")
        resolved["rows"] = read_mode_specs_csv(base_dir / path, columns)
        return resolved

    @field_validator("frequency_unit", mode="before")
    @classmethod
    def _check_frequency_unit(cls, value: object) -> UnitForm:
        """単位を正式形にする（ADR-0076）。"""
        return _energy_unit(value)

    @field_validator("coupling_convention", mode="before")
    @classmethod
    def _check_coupling_convention(cls, value: object) -> str:
        """名前が既知の流儀を指すことを確かめる。保つのは名前のままである。"""
        coupling_convention(value)  # 未知の名前・型はここで報告される
        return str(value)

    @field_validator("coupling_unit", mode="before")
    @classmethod
    def _check_coupling_unit(cls, value: object) -> UnitForm | None:
        """単位の書き方だけを確かめる。流儀との噛み合わせは正準化で見る。

        名前の引き当てと正式形への置き換えは `_read_rows` が済ませている（有次元の
        流儀のとき）。省略（`None`）はここでは通す。単位が要るかどうかは流儀が決める
        ことなので、流儀の分からないこの位置では判定できない。
        """
        if value is None:
            return None
        return _coupling_unit(value)

    @property
    def convention(self) -> CouplingConvention:
        """`coupling_convention` の名前が指す流儀オブジェクト。"""
        return coupling_convention(self.coupling_convention)

    def to_system(self) -> VibrationalSystem:
        """単位と流儀を消費して正準形の系を返す。"""
        convention = self.convention
        modes: list[VibrationalMode] = []
        for index, spec in enumerate(self.rows):
            # 軸は独立なので、frequency と coupling はそれぞれの単位から別々に正準単位
            # へ直す（ADR-0053）。単位は値が自分で持っていればそれ、なければ表の既定
            # である（ADR-0072, 0079）。coupling の係数は流儀の次元のぶんだけべきが乗る。
            # 振動数は変換式より先に検証する。lambda と vcc の変換式は振動数で割るので、
            # 0 だと `VibrationalMode` の検査に届く前に落ちる（ADR-0077）。
            location = f"modes.rows[{index}]"
            try:
                frequency = validate_frequency(
                    spec.frequency.in_canonical(self.frequency_unit)
                )
                coupling = spec.coupling.value * convention.coupling_to_canonical(
                    spec.coupling.unit_or(self.coupling_unit)
                )
            except InvalidInputError as exc:
                raise _at(location, exc) from exc
            try:
                modes.append(
                    VibrationalMode(
                        frequency=frequency,
                        huang_rhys=convention.to_huang_rhys(coupling, frequency),
                    )
                )
            except InvalidInputError as exc:
                raise _at(location, exc) from exc
        return VibrationalSystem(modes)


#: `[modes]` に行をどう書くかの案内。どちらも無い・両方あるときに出す。
_ROWS_OR_CSV: Final = (
    "modes: give the rows either inline ([[modes.rows]]) "
    'or from a CSV file (csv = {path = "<modes>.csv"})'
)


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

    schema_version: Literal[4] = SCHEMA_VERSION
    modes: ModesSpec
    """モード表。単位と流儀は表が自分で持つ（ADR-0079）。"""

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

    @field_validator("schema_version", mode="before")
    @classmethod
    def _check_schema_version(cls, value: object) -> Literal[4]:
        if value != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"unsupported schema_version {value!r} (this build supports {SCHEMA_VERSION})"
            )
        return SCHEMA_VERSION

    @field_validator("modes", mode="before")
    @classmethod
    def _check_modes_is_a_block(cls, value: object) -> object:
        """版 3 までの `[[modes]]` の並びを、版 4 の書き方を添えて断る（ADR-0079）。"""
        if isinstance(value, list):
            raise InvalidInputError(
                "modes: expected a [modes] block with [[modes.rows]] or csv, "
                "got a list of modes (write the rows under [[modes.rows]])"
            )
        return value

    def to_system(self) -> VibrationalSystem:
        """単位と流儀を消費して正準形の系を返す。"""
        return self.modes.to_system()

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
