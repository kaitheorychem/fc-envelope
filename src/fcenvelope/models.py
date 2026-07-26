"""入力の pydantic モデル、振電相互作用の流儀レジストリ、単位検証。

入力ファイルのトップレベルにある `frequency_unit` / `coupling_convention` は
パース時に消費され、`FCEnvelopeInput.to_modes()` を通った後の内部表現は常に
(frequency [cm^-1], huang_rhys) に正準化されている。以降のコードは流儀も
単位も知らない。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .errors import InvalidInputError, SchemaVersionError, UnsupportedUnitError

__all__ = [
    "CANONICAL_FREQUENCY_UNIT",
    "SCHEMA_VERSION",
    "CouplingConvention",
    "Conditions",
    "FCEnvelopeInput",
    "ModeSpec",
    "VibrationalMode",
    "to_huang_rhys",
]

SCHEMA_VERSION = 1
CANONICAL_FREQUENCY_UNIT = "cm^-1"


class CouplingConvention(str, Enum):
    """入力ファイルが用いる振電相互作用パラメータの流儀。"""

    G = "g"
    HUANG_RHYS = "huang_rhys"


#: 流儀 -> Huang-Rhys 因子 S への変換関数。
#: 流儀の追加は 1 エントリの追加で済む。
COUPLING_REGISTRY: dict[CouplingConvention, Callable[[float], float]] = {
    CouplingConvention.G: lambda g: g * g,
    CouplingConvention.HUANG_RHYS: lambda s: s,
}


def to_huang_rhys(value: float, convention: CouplingConvention) -> float:
    """流儀に従った coupling 値を Huang-Rhys 因子 S に変換する。"""
    return COUPLING_REGISTRY[convention](value)


class VibrationalMode(BaseModel):
    """正準表現の振動モード。"""

    model_config = ConfigDict(frozen=True)

    frequency: float = Field(gt=0.0, description="epsilon_alpha [cm^-1]")
    huang_rhys: float = Field(ge=0.0, description="S_alpha (無次元)")


class Conditions(BaseModel):
    """計算条件。正準表現とファイル表現が一致するため共用する。"""

    model_config = ConfigDict(frozen=True)

    temperature: float = Field(ge=0.0, description="T [K]")
    sigma: float = Field(gt=0.0, description="sigma [cm^-1]")
    e_min: float = Field(description="出力窓の下端 [cm^-1]")
    e_max: float = Field(description="出力窓の上端 [cm^-1]")
    de: float = Field(gt=0.0, description="出力グリッド間隔 [cm^-1]")

    @model_validator(mode="after")
    def _check_window(self) -> "Conditions":
        if not self.e_min < self.e_max:
            raise ValueError(f"e_min must be smaller than e_max (got {self.e_min} >= {self.e_max})")
        return self

    @classmethod
    def from_obj(cls, data: Any) -> "Conditions":
        """辞書から生成する。pydantic の検証失敗は `InvalidInputError` になる。"""
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            raise InvalidInputError(str(exc)) from exc


class ModeSpec(BaseModel):
    """入力ファイル中の 1 モード。`coupling` の意味は流儀に依存する。"""

    model_config = ConfigDict(frozen=True)

    frequency: float = Field(gt=0.0)
    coupling: float = Field(ge=0.0)


class FCEnvelopeInput(BaseModel):
    """入力ファイル全体。"""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = SCHEMA_VERSION
    frequency_unit: str = CANONICAL_FREQUENCY_UNIT
    coupling_convention: CouplingConvention = CouplingConvention.G
    modes: list[ModeSpec] = Field(min_length=1)
    conditions: Conditions

    @field_validator("schema_version", mode="before")
    @classmethod
    def _check_schema_version(cls, value: Any) -> Any:
        if value != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"unsupported schema_version {value!r} (this build supports {SCHEMA_VERSION})"
            )
        return value

    @field_validator("frequency_unit", mode="before")
    @classmethod
    def _check_frequency_unit(cls, value: Any) -> Any:
        if value != CANONICAL_FREQUENCY_UNIT:
            raise UnsupportedUnitError(
                f"unsupported frequency_unit {value!r} "
                f"(only {CANONICAL_FREQUENCY_UNIT!r} is supported)"
            )
        return value

    def to_modes(self) -> list[VibrationalMode]:
        """流儀を消費して正準表現のモード列を返す。"""
        convention = self.coupling_convention
        return [
            VibrationalMode(
                frequency=spec.frequency,
                huang_rhys=to_huang_rhys(spec.coupling, convention),
            )
            for spec in self.modes
        ]

    @classmethod
    def from_obj(cls, data: Any) -> "FCEnvelopeInput":
        """辞書から生成する。pydantic の検証失敗は `InvalidInputError` になる。"""
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            raise InvalidInputError(str(exc)) from exc

    @classmethod
    def from_json(cls, text: str | bytes) -> "FCEnvelopeInput":
        """JSON 文字列から生成する。"""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise InvalidInputError(f"invalid JSON: {exc}") from exc
        return cls.from_obj(data)

    @classmethod
    def from_path(cls, path: str | Path) -> "FCEnvelopeInput":
        """入力 JSON ファイルを読み込む。"""
        p = Path(path)
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            raise InvalidInputError(f"cannot read input file {p}: {exc}") from exc
        return cls.from_json(text)
