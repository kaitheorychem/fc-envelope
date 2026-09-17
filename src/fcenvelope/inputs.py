"""入力ファイルの型（pydantic）と正準化。

このモジュールが扱うのは**ファイルの構造・単位・流儀**だけである。値の範囲は
計算用の値の型に任せ、値の型が送出したエラーにフィールドの位置を添える
（`docs/adr/0051-value-types-validate-their-own-invariants.md`）。

トップレベルの `frequency_unit` / `coupling_convention` は正準化の際に消費され、
`to_system()` を通った後の表現は常に (frequency [cm^-1], huang_rhys) である。
以降のコードは流儀も単位も知らない。

`modes` はモードの配列を直接書くか、`{"path": "modes.csv"}` で CSV のモード表を
参照する。参照はパース時に解決され、パース後は配列で書いた場合と区別がない。
"""

from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path
from typing import Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
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
    CANONICAL_FREQUENCY_UNIT,
    DEFAULT_COUPLING_CONVENTION,
    CouplingConvention,
    check_frequency_unit,
    coupling_convention,
)

#: つまみの既定値の唯一の出どころ（ADR-0050）。`Selection` は slots 付きの
#: dataclass なのでクラス属性から既定値は読めず、既定のインスタンスから引く。
_DEFAULT_SELECTION = Selection()

logger = logging.getLogger(__name__)

__all__ = [
    "MODES_CSV_COLUMNS",
    "SCHEMA_VERSION",
    "BroadeningSpec",
    "EnergyGridSpec",
    "FCEnvelopeInput",
    "ModeSpec",
    "SelectionSpec",
    "read_mode_specs_csv",
]

#: 入力ファイルの版（`docs/adr/0040-schema-version-2-without-a-compatibility-layer.md`）。
#: 1 は互換層を置かずに拒否する。
SCHEMA_VERSION: Final = 2


def _at(location: str, exc: InvalidInputError) -> InvalidInputError:
    """値の型が送出したエラーに、入力ファイル中の位置を添える（ADR-0051）。"""
    return InvalidInputError(f"{location}: {exc}")


class _Spec(BaseModel):
    """入力ファイル中の 1 ブロック。構造だけを検査する。"""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ModeSpec(_Spec):
    """入力ファイル中の 1 モード。`coupling` の意味は流儀に依存する。"""

    frequency: float
    coupling: float


class BroadeningSpec(_Spec):
    """線形状のブロック。"""

    sigma: float


class EnergyGridSpec(_Spec):
    """エネルギーグリッドのブロック。"""

    e_min: float
    e_max: float
    de: float


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
    `coupling` の流儀と単位は参照元の入力 JSON に従う。

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


class FCEnvelopeInput(BaseModel):
    """入力ファイル全体。

    `run` は `temperature` / `broadening` / `grid` を、`lines` は `temperature` /
    `selection` を読む。どちらの副命令も同じファイルを使える（ADR-0005）。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[2] = SCHEMA_VERSION
    frequency_unit: str = CANONICAL_FREQUENCY_UNIT
    coupling_convention: str = DEFAULT_COUPLING_CONVENTION.name
    """流儀の**名前**。流儀そのものは `convention` から引く。

    ファイルに現れるのは名前なので、pydantic のフィールドも名前のままにする。
    こうしておくと `model_dump()` がそのまま入力ファイルの形に戻り、CLI の上書きが
    同じ経路を通れる（ADR-0050）。
    """

    modes: list[ModeSpec] = Field(min_length=1)
    temperature: float
    broadening: BroadeningSpec
    grid: EnergyGridSpec
    selection: SelectionSpec = SelectionSpec()

    # pydantic の `mode="before"` の検証器は**検証前**の値を受ける。構造が分からない
    # 位置なので `object` で取り、pydantic に渡し返すものだけを返す。

    @field_validator("schema_version", mode="before")
    @classmethod
    def _check_schema_version(cls, value: object) -> Literal[2]:
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
        return check_frequency_unit(value)

    @field_validator("coupling_convention", mode="before")
    @classmethod
    def _check_coupling_convention(cls, value: object) -> str:
        """名前が既知の流儀を指すことを確かめる。保つのは名前のままである。"""
        coupling_convention(value)  # 未知の名前・型はここで報告される
        return str(value)

    @property
    def convention(self) -> CouplingConvention:
        """`coupling_convention` の名前が指す流儀オブジェクト。"""
        return coupling_convention(self.coupling_convention)

    def to_system(self) -> VibrationalSystem:
        """単位と流儀を消費して正準形の系を返す。"""
        convention = self.convention
        # 今の入力フォーマットは coupling の単位を持たない。無次元の流儀ならこれで
        # 正しく、単位を持つ流儀（V, lambda）ならここで弾かれる（ADR-0033）。
        convention.check_coupling_unit(None)
        modes: list[VibrationalMode] = []
        for index, spec in enumerate(self.modes):
            try:
                modes.append(
                    VibrationalMode(
                        frequency=spec.frequency,
                        huang_rhys=convention.to_huang_rhys(
                            spec.coupling, spec.frequency
                        ),
                    )
                )
            except InvalidInputError as exc:
                raise _at(f"modes[{index}]", exc) from exc
        return VibrationalSystem(modes)

    def to_broadening(self) -> Broadening:
        """線形状を計算用の値にする。"""
        try:
            return Broadening(sigma=self.broadening.sigma)
        except InvalidInputError as exc:
            raise _at("broadening", exc) from exc

    def to_grid(self) -> EnergyGrid:
        """エネルギーグリッドを計算用の値にする。"""
        try:
            return EnergyGrid(
                e_min=self.grid.e_min, e_max=self.grid.e_max, de=self.grid.de
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
    def from_json(
        cls, text: str | bytes, *, base_dir: str | Path | None = None
    ) -> "FCEnvelopeInput":
        """JSON 文字列から生成する。"""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise InvalidInputError(f"invalid JSON: {exc}") from exc
        return cls.from_obj(data, base_dir=base_dir)

    @classmethod
    def from_path(cls, path: str | Path) -> "FCEnvelopeInput":
        """入力 JSON ファイルを読み込む。`modes.path` はこのファイルからの相対パス。"""
        p = Path(path)
        with stage(logger, f"read {p}"):
            try:
                text = p.read_text(encoding="utf-8")
            except OSError as exc:
                raise InvalidInputError(f"cannot read input file {p}: {exc}") from exc
            return cls.from_json(text, base_dir=p.parent)
