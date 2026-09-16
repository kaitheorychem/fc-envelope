"""入力の pydantic モデルとモード表 CSV の読み込み。

入力ファイルのトップレベルにある `frequency_unit` / `coupling_convention` は
パース時に消費され、`FCEnvelopeInput.to_modes()` を通った後の内部表現は常に
(frequency [cm^-1], huang_rhys) に正準化されている。以降のコードは流儀も
単位も知らない。

条件は性質ごとに 4 つに分かれる（ADR-0035）。`temperature` は物理（答えが変わる）、
`Broadening` は現象論的なモデルパラメータ、`EnergyGrid` と `Selection` は数値
（どこを標本するか・どれを保持するか）である。エンベロープは temperature /
broadening / grid を、離散線は temperature / selection を読み、互いに相手の節を
無視する。

`modes` はモードの配列を直接書くか、`{"path": "modes.csv"}` で CSV のモード表を
参照する。参照はパース時に解決され、パース後は配列で書いた場合と区別がない。
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Annotated, Any, Literal

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
from .units import (
    CANONICAL_FREQUENCY_UNIT,
    CouplingConvention,
    check_frequency_unit,
    coupling_convention,
)

__all__ = [
    "MODES_CSV_COLUMNS",
    "SCHEMA_VERSION",
    "Broadening",
    "EnergyGrid",
    "FCEnvelopeInput",
    "ModeSpec",
    "Selection",
    "VibrationalMode",
    "read_mode_specs_csv",
]

SCHEMA_VERSION = 2

#: 入力ファイルでは流儀名の文字列、モデルの上では流儀オブジェクトとして扱う。
#: 書き出しでは名前に戻る（ADR-0033）。
_Convention = Annotated[
    CouplingConvention,
    BeforeValidator(coupling_convention),
    PlainSerializer(lambda convention: convention.key, return_type=str),
]


class _ValueModel(BaseModel):
    """凍結された値型の基底。検証の失敗を `InvalidInputError` に揃える。

    pydantic の `ValidationError` をそのまま外へ出すと、利用側が
    `except FCEnvelopeError` で一括捕捉できなくなる（ADR-0013）。直接構築でも
    辞書からの生成でも、送出される例外は `InvalidInputError` に統一する。
    """

    model_config = ConfigDict(frozen=True)

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except ValidationError as exc:
            raise InvalidInputError(str(exc)) from exc

    # pydantic は `__init__` の上書きを見つけると、入れ子の検証もそれを経由させる。
    # そうなると入れ子のモデルが 1 つ落ちた時点で `ValidationError` の積み上げが
    # 止まり、入力ファイル全体の誤りを 1 度に報告できなくなる。この印を付けると
    # `model_validate` は基底の検証器を直に使い、上の `__init__` は Python から
    # 直接構築したときだけ働く。`test_validation.py` がこの両立を固定している。
    __init__.__pydantic_base_init__ = True  # type: ignore[attr-defined]

    @classmethod
    def from_obj(cls, data: Any):
        """辞書から生成する。pydantic の検証失敗は `InvalidInputError` になる。"""
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            raise InvalidInputError(str(exc)) from exc


class VibrationalMode(_ValueModel):
    """正準表現の振動モード。"""

    frequency: float = Field(gt=0.0, description="epsilon_alpha [cm^-1]")
    huang_rhys: float = Field(ge=0.0, description="S_alpha (無次元)")


class Broadening(_ValueModel):
    """線形状。時間領域の減衰因子 exp(-sigma^2 tau^2 / 2 - gamma |tau|) の 2 パラメータ。

    ガウス・ローレンツ・Voigt は別の「種類」ではなく、この 1 つの族の中の点である
    （ADR-0034）。
    """

    sigma: float = Field(ge=0.0, description="ガウス幅 sigma [cm^-1]")
    gamma: float = Field(default=0.0, ge=0.0, description="ローレンツ幅 gamma [cm^-1]")

    @model_validator(mode="after")
    def _check_width(self) -> "Broadening":
        if self.sigma == 0.0 and self.gamma == 0.0:
            raise ValueError("at least one of sigma and gamma must be positive")
        return self


class EnergyGrid(_ValueModel):
    """エンベロープを標本する E 軸上の点列。省略値・自動推定は置かない。"""

    e_min: float = Field(description="出力窓の下端 [cm^-1]")
    e_max: float = Field(description="出力窓の上端 [cm^-1]")
    de: float = Field(gt=0.0, description="出力グリッド間隔 [cm^-1]")

    @model_validator(mode="after")
    def _check_window(self) -> "EnergyGrid":
        if not self.e_min < self.e_max:
            raise ValueError(f"e_min must be smaller than e_max (got {self.e_min} >= {self.e_max})")
        return self


class Selection(_ValueModel):
    """離散線のうちどれを保持するかを決めるつまみの組。

    `LinesResult` はこのオブジェクトを丸ごとエコーする。つまみを足したがエコーを
    足し忘れる、というバグのクラス自体がそれで消える（ADR-0035）。
    """

    min_weight: float = Field(default=1e-4, gt=0.0, le=1.0, description="保持する重みの下限")
    max_lines: int = Field(default=10000, ge=1, description="保持・列挙する線数の上限")
    max_quanta: int | None = Field(
        default=None, ge=0, description="1 モードあたりの振動量子数の上限（既定は自動）"
    )


class ModeSpec(_ValueModel):
    """入力ファイル中の 1 モード。`coupling` の意味は流儀に依存する。"""

    frequency: float = Field(gt=0.0)
    coupling: float = Field(ge=0.0)


#: モード表 CSV の列。ヘッダを省略した場合はこの順に並んでいるものとする。
MODES_CSV_COLUMNS = ("frequency", "coupling")


def read_mode_specs_csv(path: str | Path) -> list[ModeSpec]:
    """モード表 CSV（RFC 4180）を読み込む。

    列はちょうど `MODES_CSV_COLUMNS` の 2 列。ヘッダは省略でき、1 行目がこの列名の
    組（順序は問わない）ならヘッダとして扱い、そうでなければ `frequency, coupling`
    の順のデータ行として扱う。列名は数値にならないため、この判定は曖昧にならない。
    RFC 4180 にないコメント行は受け付けず、空行は空のレコードとしてエラーにする。
    `coupling` の流儀と単位は参照元の入力 JSON に従う。
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
        except (ValidationError, InvalidInputError) as exc:
            raise InvalidInputError(f"{location}: {exc}{hint}") from exc
    return specs


class FCEnvelopeInput(BaseModel):
    """入力ファイル全体。"""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    schema_version: Literal[2] = SCHEMA_VERSION
    frequency_unit: str = CANONICAL_FREQUENCY_UNIT
    coupling_convention: _Convention = CouplingConvention.G
    modes: list[ModeSpec] = Field(min_length=1)
    temperature: float = Field(ge=0.0, description="T [K]")
    broadening: Broadening
    grid: EnergyGrid
    selection: Selection = Selection()

    @field_validator("schema_version", mode="before")
    @classmethod
    def _check_schema_version(cls, value: Any) -> Any:
        if value != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"unsupported schema_version {value!r} (this build supports {SCHEMA_VERSION})"
            )
        return value

    @field_validator("modes", mode="before")
    @classmethod
    def _resolve_modes_file(cls, value: Any, info: ValidationInfo) -> Any:
        """`{"path": ...}` を CSV から読んだモード列に置き換える。

        相対パスは検証コンテキストの `base_dir`（`from_path` では入力ファイルの
        ディレクトリ）を基準に解決する。
        """
        if not isinstance(value, dict):
            return value
        if set(value) != {"path"} or not isinstance(value["path"], str) or not value["path"]:
            raise ValueError('modes must be a list of modes or {"path": "<modes>.csv"}')
        base_dir = Path((info.context or {}).get("base_dir") or ".")
        return read_mode_specs_csv(base_dir / value["path"])

    @field_validator("frequency_unit", mode="before")
    @classmethod
    def _check_frequency_unit(cls, value: Any) -> Any:
        return check_frequency_unit(value)

    @property
    def coupling_unit(self) -> str | None:
        """`modes[].coupling` が持つ単位。無次元の流儀では None。"""
        return self.coupling_convention.coupling_unit(self.frequency_unit)

    def to_modes(self) -> list[VibrationalMode]:
        """流儀を消費して正準表現のモード列を返す。

        単位変換も流儀変換も情報を失わない可逆な写像なので、失敗しないという契約を
        置ける（ADR-0037）。数値計算である対角化をここに入れないのはこのためである。
        """
        convention = self.coupling_convention
        return [
            VibrationalMode(
                frequency=spec.frequency,
                huang_rhys=convention.to_huang_rhys(spec.coupling, spec.frequency),
            )
            for spec in self.modes
        ]

    @classmethod
    def from_obj(
        cls, data: Any, *, base_dir: str | Path | None = None
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
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            raise InvalidInputError(f"cannot read input file {p}: {exc}") from exc
        return cls.from_json(text, base_dir=p.parent)
