"""結果クラスの永続化。単一 JSON を round-trip の正準形式とする。

エンベロープ F(E)（`kind` = `"fcenvelope.envelope"`）と離散 FC 因子
（`kind` = `"fcenvelope.fc_lines"`）の 2 種類を扱う。どちらも入力エコーは常に
正準形（`coupling_convention` = `"huang_rhys"`）で書き出す。これにより
読み込み側に流儀の曖昧さが残らない。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generic, TypeVar, get_type_hints

import numpy as np

from .errors import InvalidInputError, SchemaVersionError, UnsupportedUnitError
from .logs import stage
from .models import (
    Broadening,
    EnergyGrid,
    Selection,
    VibrationalMode,
    VibrationalSystem,
)
from .result import (
    AnyDiagnostics,
    Diagnostics,
    EnvelopeResult,
    FCLine,
    FCLineDiagnostics,
    LinesResult,
    ModeTransition,
    Provenance,
    Result,
)

#: **検証を通る前の** JSON の値。構造が分からないことが分かっている位置にだけ使う。
#: `json.loads` の戻りそのもので、ここを狭められないのは外部ファイルの中身だからである。
#: この別名を使わない裸の `Any` は、型を決めそこねた印として読んでよい。
JsonValue = Any

#: JSON のオブジェクト。キーが `str` であることだけは分かっている。
JsonObject = dict[str, JsonValue]

_D = TypeVar("_D", bound=AnyDiagnostics)
_R = TypeVar("_R", bound=Result)
_T = TypeVar("_T")

__all__ = [
    "ENVELOPE_KIND",
    "LINES_KIND",
    "RESULT_KINDS",
    "kind_for",
    "kind_of",
    "load_any",
    "load_envelope",
    "load_lines",
    "save_any",
    "save_envelope",
    "save_lines",
]

logger = logging.getLogger(__name__)

ENVELOPE_KIND = "fcenvelope.envelope"
LINES_KIND = "fcenvelope.fc_lines"

#: 結果ファイルの版。入力ファイルの版（`inputs.SCHEMA_VERSION`）と同じ番号を共有
#: するが、`io` は `inputs` に依存しないので（ADR-0041）ここに別に持つ。両者が
#: 一致していることはテストで確かめる。
SCHEMA_VERSION = 2

#: 結果ファイルの形式の知識。計算側は常に cm^-1 しか扱わないので、単位は結果クラス
#: ではなく io が持つ（ADR-0047）。入力エコーは常に正準形なので流儀も固定である。
CANONICAL_ENERGY_UNIT = "cm^-1"
CANONICAL_DENSITY_UNIT = "1/cm^-1"
CANONICAL_FREQUENCY_UNIT = "cm^-1"
CANONICAL_COUPLING_CONVENTION = "huang_rhys"

#: 診断値の型 -> JSON からの変換。dataclass の型注釈から引く。受け取るのは検証前の
#: JSON の値なので入力側だけが `JsonValue` で、返すのは診断値の型そのものである。
_SCALAR_READERS: dict[type, Callable[[JsonValue], int | float | bool]] = {
    int: int,
    float: float,
    bool: bool,
}


def _diagnostic_readers(
    cls: type[_D],
) -> dict[str, Callable[[JsonValue], int | float | bool]]:
    """診断値クラスの定義からフィールド名と変換関数を導く（ADR-0036）。

    フィールド名のタプルを手で複製すると、dataclass にフィールドを足してタプルに
    足し忘れたときに静かに壊れる。`messages` だけは他と扱いが違うので除く。
    """
    hints = get_type_hints(cls)
    return {
        field.name: _SCALAR_READERS[hints[field.name]]
        for field in fields(cls)
        if field.name != "messages"
    }


def _diagnostics_to_dict(diagnostics: AnyDiagnostics) -> JsonObject:
    """診断値を JSON の構造へ写す。"""
    return {
        **{
            name: getattr(diagnostics, name)
            for name in _diagnostic_readers(type(diagnostics))
        },
        "messages": list(diagnostics.messages),
    }


def _diagnostics_from_dict(cls: type[_D], data: JsonValue) -> _D:
    """JSON の構造から診断値を復元する。渡した型のインスタンスが返る。"""
    if not isinstance(data, dict):
        raise InvalidInputError(
            f"'diagnostics' must be a JSON object, got {type(data).__name__}"
        )
    # フィールドと型の対応は dataclass から実行時に導くので（ADR-0036）、下の
    # 展開は型検査では追えない。取り違えは `_diagnostic_readers` が見ている。
    values: dict[str, JsonValue]
    try:
        values = {
            name: read(data[name]) for name, read in _diagnostic_readers(cls).items()
        }
    except KeyError as exc:
        raise InvalidInputError(f"missing diagnostics field {exc.args[0]!r}") from exc
    except (TypeError, ValueError) as exc:
        raise InvalidInputError(f"malformed diagnostics: {exc}") from exc
    return cls(messages=_messages_from(data.get("messages", [])), **values)


def _messages_from(data: JsonValue) -> tuple[str, ...]:
    """診断メッセージの列を復元する。"""
    if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
        raise InvalidInputError("diagnostics.messages must be a list of strings")
    return tuple(data)


def _format_timestamp(moment: datetime) -> str:
    """UTC・秒精度の ISO 8601 文字列（末尾 Z）にする。"""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).replace(microsecond=0, tzinfo=None).isoformat() + "Z"


def _parse_timestamp(text: JsonValue) -> datetime:
    if not isinstance(text, str):
        raise InvalidInputError(f"created_at must be a string, got {type(text).__name__}")
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidInputError(f"invalid created_at {text!r}: {exc}") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def envelope_to_dict(result: EnvelopeResult) -> JsonObject:
    """結果クラスを出力 JSON の構造（§8.2）へ写す。"""
    return {
        **_header_to_dict(ENVELOPE_KIND, result.provenance),
        "input": {
            **_system_to_dict(result.system),
            "temperature": result.temperature,
            "broadening": {"sigma": result.broadening.sigma},
            "grid": {
                "e_min": result.grid.e_min,
                "e_max": result.grid.e_max,
                "de": result.grid.de,
            },
        },
        "derived": _derived_to_dict(result.system),
        "diagnostics": _diagnostics_to_dict(result.diagnostics),
        "spectrum": {
            "energy": result.energy.tolist(),
            "density": result.density.tolist(),
        },
    }


def _write_json(payload: JsonObject, path: str | Path) -> None:
    """出力 JSON を書き出す。

    浮動小数点は Python 標準 `json` の repr ベース出力により round-trip で完全一致する。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with stage(logger, f"write {target}"):
        with target.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")


def save_envelope(result: EnvelopeResult, path: str | Path) -> None:
    """エンベロープの結果クラスを JSON として保存する。"""
    _write_json(envelope_to_dict(result), path)


def _require(data: JsonValue, key: str, path: str) -> JsonValue:
    if not isinstance(data, dict):
        raise InvalidInputError(f"{path!r}: expected a JSON object in result file")
    if key not in data:
        raise InvalidInputError(f"missing field {path!r} in result file")
    return data[key]


def _require_float(data: JsonValue, key: str, path: str) -> float:
    value = _require(data, key, path)
    # JSON の true / false は Python では int なので、明示的に弾く。数のつもりで
    # 真偽値を書いたファイルを 1.0 として黙って受けたくない（`_require_int` も同じ）。
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidInputError(f"{path!r} must be a number (got {value!r})")
    return float(value)


def _require_int(data: JsonValue, key: str, path: str) -> int:
    value = _require(data, key, path)
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidInputError(f"{path!r} must be an integer (got {value!r})")
    return value


def _optional_int(value: JsonValue) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidInputError(f"max_quanta must be an integer or null (got {value!r})") from exc


def _build(factory: Callable[..., _T], location: str, **kwargs: object) -> _T:
    """値の型を組み立て、不変条件の違反に結果ファイル中の位置を添える。"""
    try:
        return factory(**kwargs)
    except InvalidInputError as exc:
        raise InvalidInputError(f"{location}: {exc}") from exc


def _float_array(data: JsonValue, path: str) -> np.ndarray:
    """数値の並びを float64 の 1 次元配列にする。"""
    if not isinstance(data, list):
        raise InvalidInputError(f"{path!r} must be a list of numbers")
    try:
        return np.asarray(data, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise InvalidInputError(f"{path!r} must be a list of numbers: {exc}") from exc


def _check_echo_header(echo: JsonValue) -> None:
    """入力エコーが正準形（cm^-1・huang_rhys）であることを確かめる。"""
    if not isinstance(echo, dict):
        raise InvalidInputError(f"'input' must be a JSON object, got {type(echo).__name__}")
    frequency_unit = echo.get("frequency_unit", CANONICAL_FREQUENCY_UNIT)
    if frequency_unit != CANONICAL_FREQUENCY_UNIT:
        raise UnsupportedUnitError(
            f"unsupported frequency_unit {frequency_unit!r} "
            f"(only {CANONICAL_FREQUENCY_UNIT!r} is supported)"
        )
    convention = echo.get("coupling_convention", CANONICAL_COUPLING_CONVENTION)
    if convention != CANONICAL_COUPLING_CONVENTION:
        raise InvalidInputError(
            f"input.coupling_convention must be "
            f"{CANONICAL_COUPLING_CONVENTION!r} (got {convention!r})"
        )


def _header_to_dict(kind: str, provenance: Provenance) -> JsonObject:
    """どの結果ファイルにも共通する先頭部分。1 箇所で書く（ADR-0036）。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "fcenvelope_version": provenance.fcenvelope_version,
        "created_at": _format_timestamp(provenance.created_at),
        **RESULT_KINDS[kind].units,
    }


def _check_header(data: JsonValue, kind: str) -> None:
    """共通の先頭部分を検査する。1 箇所で読む（ADR-0036）。"""
    if not isinstance(data, dict):
        raise InvalidInputError(
            f"result file must contain a JSON object, got {type(data).__name__}"
        )
    version = _require(data, "schema_version", "schema_version")
    if version != SCHEMA_VERSION:
        raise SchemaVersionError(
            f"unsupported schema_version {version!r} (this build supports {SCHEMA_VERSION})"
        )
    found = data.get("kind")
    if found != kind:
        raise InvalidInputError(f"unexpected kind {found!r} (expected {kind!r})")
    for key, canonical in RESULT_KINDS[kind].units.items():
        unit = data.get(key, canonical)
        if unit != canonical:
            raise UnsupportedUnitError(
                f"unsupported {key} {unit!r} (only {canonical!r} is supported)"
            )


def _system_to_dict(system: VibrationalSystem) -> JsonObject:
    """系を入力エコーの構造へ写す。エコーは常に正準形（ADR-0010）。"""
    return {
        "frequency_unit": CANONICAL_FREQUENCY_UNIT,
        "coupling_convention": CANONICAL_COUPLING_CONVENTION,
        "modes": [
            {"frequency": mode.frequency, "coupling": mode.huang_rhys}
            for mode in system.modes
        ],
    }


def _derived_to_dict(system: VibrationalSystem) -> JsonObject:
    """系から導かれる量。結果クラスは持たず、io が書き出す（ADR-0047）。"""
    return {"reorganization_energy": system.reorganization_energy}


def _provenance_from_dict(data: JsonValue) -> Provenance:
    return Provenance(
        fcenvelope_version=str(_require(data, "fcenvelope_version", "fcenvelope_version")),
        created_at=_parse_timestamp(_require(data, "created_at", "created_at")),
    )


def _system_from_echo(echo: JsonValue) -> VibrationalSystem:
    """入力エコーのモードから正準形の系を組み立てる。"""
    return _build(VibrationalSystem, "input.modes", modes=_modes_from_echo(echo))


def _modes_from_echo(echo: JsonValue) -> tuple[VibrationalMode, ...]:
    """入力エコーの各モードを正準形の値の型にする。"""
    specs = _require(echo, "modes", "input.modes")
    if not isinstance(specs, list):
        raise InvalidInputError(f"input.modes must be a list, got {type(specs).__name__}")
    modes: list[VibrationalMode] = []
    for index, spec in enumerate(specs):
        location = f"input.modes[{index}]"
        modes.append(
            _build(
                VibrationalMode,
                location,
                frequency=_require_float(spec, "frequency", f"{location}.frequency"),
                huang_rhys=_require_float(spec, "coupling", f"{location}.coupling"),
            )
        )
    return tuple(modes)


def envelope_from_dict(data: JsonValue) -> EnvelopeResult:
    """出力 JSON の構造から結果クラスを復元する。"""
    _check_header(data, ENVELOPE_KIND)

    echo = _require(data, "input", "input")
    _check_echo_header(echo)
    system = _system_from_echo(echo)
    broadening_echo = _require(echo, "broadening", "input.broadening")
    broadening = _build(
        Broadening,
        "input.broadening",
        sigma=_require_float(broadening_echo, "sigma", "input.broadening.sigma"),
    )
    grid_echo = _require(echo, "grid", "input.grid")
    grid = _build(
        EnergyGrid,
        "input.grid",
        e_min=_require_float(grid_echo, "e_min", "input.grid.e_min"),
        e_max=_require_float(grid_echo, "e_max", "input.grid.e_max"),
        de=_require_float(grid_echo, "de", "input.grid.de"),
    )

    diagnostics = _diagnostics_from_dict(
        Diagnostics, _require(data, "diagnostics", "diagnostics")
    )

    spectrum = _require(data, "spectrum", "spectrum")
    energy = _float_array(_require(spectrum, "energy", "spectrum.energy"), "spectrum.energy")
    density = _float_array(_require(spectrum, "density", "spectrum.density"), "spectrum.density")
    if energy.shape != density.shape:
        raise InvalidInputError(
            f"spectrum.energy and spectrum.density length mismatch: "
            f"{energy.size} vs {density.size}"
        )

    # `derived` は系から一意に決まる控えなので読み飛ばす（ADR-0047）。

    return EnvelopeResult(
        system=system,
        temperature=_require_float(echo, "temperature", "input.temperature"),
        broadening=broadening,
        grid=grid,
        energy=energy,
        density=density,
        diagnostics=diagnostics,
        provenance=_provenance_from_dict(data),
    )


def _read_json(path: str | Path) -> JsonValue:
    source = Path(path)
    with stage(logger, f"read {source}"):
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise InvalidInputError(f"cannot read result file {source}: {exc}") from exc
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise InvalidInputError(f"invalid JSON in {source}: {exc}") from exc


def load_envelope(path: str | Path) -> EnvelopeResult:
    """保存済み JSON からエンベロープの結果クラスを復元する。"""
    return envelope_from_dict(_read_json(path))


def lines_to_dict(result: LinesResult) -> JsonObject:
    """離散 FC 因子の結果クラスを出力 JSON の構造へ写す。"""
    return {
        **_header_to_dict(LINES_KIND, result.provenance),
        "input": {
            **_system_to_dict(result.system),
            "temperature": result.temperature,
            "selection": {
                "min_weight": result.selection.min_weight,
                "max_lines": result.selection.max_lines,
                "max_quanta": result.selection.max_quanta,
            },
        },
        "derived": _derived_to_dict(result.system),
        "diagnostics": _diagnostics_to_dict(result.diagnostics),
        "lines": [
            {
                "energy": line.energy,
                "fc_factor": line.fc_factor,
                "weight": line.weight,
                "transitions": [
                    {
                        "mode": transition.mode_index,
                        "initial": transition.initial,
                        "final": transition.final,
                    }
                    for transition in line.transitions
                ],
            }
            for line in result.lines
        ],
    }


def save_lines(result: LinesResult, path: str | Path) -> None:
    """離散 FC 因子の結果クラスを JSON として保存する。"""
    _write_json(lines_to_dict(result), path)


def _parse_transitions(data: JsonValue, index: int) -> tuple[ModeTransition, ...]:
    if not isinstance(data, list):
        raise InvalidInputError(f"lines[{index}].transitions must be a list")
    try:
        return tuple(
            ModeTransition(
                mode_index=int(item["mode"]),
                initial=int(item["initial"]),
                final=int(item["final"]),
            )
            for item in data
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidInputError(f"lines[{index}]: malformed transition: {exc}") from exc


def lines_from_dict(data: JsonValue) -> LinesResult:
    """出力 JSON の構造から離散 FC 因子の結果クラスを復元する。"""
    _check_header(data, LINES_KIND)

    echo = _require(data, "input", "input")
    _check_echo_header(echo)
    system = _system_from_echo(echo)

    diagnostics = _diagnostics_from_dict(
        FCLineDiagnostics, _require(data, "diagnostics", "diagnostics")
    )

    selection_echo = _require(echo, "selection", "input.selection")
    selection = _build(
        Selection,
        "input.selection",
        min_weight=_require_float(selection_echo, "min_weight", "input.selection.min_weight"),
        max_lines=_require_int(
            selection_echo, "max_lines", "input.selection.max_lines"
        ),
        max_quanta=_optional_int(selection_echo.get("max_quanta")),
    )
    lines_data = _require(data, "lines", "lines")
    if not isinstance(lines_data, list):
        raise InvalidInputError(f"lines must be a list, got {type(lines_data).__name__}")
    try:
        lines = tuple(
            FCLine(
                energy=float(item["energy"]),
                fc_factor=float(item["fc_factor"]),
                weight=float(item["weight"]),
                transitions=_parse_transitions(item.get("transitions", []), index),
            )
            for index, item in enumerate(lines_data)
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidInputError(f"malformed lines entry: {exc}") from exc

    # `derived` は系から一意に決まる控えなので読み飛ばす（ADR-0047）。

    return LinesResult(
        system=system,
        temperature=_require_float(echo, "temperature", "input.temperature"),
        selection=selection,
        lines=lines,
        diagnostics=diagnostics,
        provenance=_provenance_from_dict(data),
    )


def load_lines(path: str | Path) -> LinesResult:
    """保存済み JSON から離散 FC 因子の結果クラスを復元する。"""
    return lines_from_dict(_read_json(path))


@dataclass(frozen=True, slots=True)
class _ResultKind(Generic[_R]):
    """結果の 1 種類について、`io` が持つ関心をまとめたもの（ADR-0049）。

    種類ごとに結果クラスが違うので `_R` で束ねる。こうすると 1 行を組み立てる時点で
    `result_type` と `to_dict` / `from_dict` の食い違いが型として見える。
    """

    kind: str
    """出力ファイルの `kind`。"""

    result_type: type[_R]
    """対応する結果クラス。"""

    units: dict[str, str]
    """ファイルに書く単位のフィールド。読み込み時はこの値と突き合わせる。"""

    to_dict: Callable[[_R], JsonObject]
    """結果クラス -> JSON。"""

    from_dict: Callable[[JsonValue], _R]
    """検証前の JSON -> 結果クラス。"""


#: `kind` -> 保存・読み込み。種類を足すときはここに 1 行足す。
#: 描画は `plotting.DRAWERS`、報告は `cli.REPORTERS` にそれぞれの表がある。
#: 表そのものは種類をまたぐので `_R` を固定できない。個々の行は上の型で検査される。
RESULT_KINDS: dict[str, _ResultKind[Any]] = {
    ENVELOPE_KIND: _ResultKind(
        kind=ENVELOPE_KIND,
        result_type=EnvelopeResult,
        units={
            "energy_unit": CANONICAL_ENERGY_UNIT,
            "density_unit": CANONICAL_DENSITY_UNIT,
        },
        to_dict=envelope_to_dict,
        from_dict=envelope_from_dict,
    ),
    LINES_KIND: _ResultKind(
        kind=LINES_KIND,
        result_type=LinesResult,
        units={"energy_unit": CANONICAL_ENERGY_UNIT},
        to_dict=lines_to_dict,
        from_dict=lines_from_dict,
    ),
}

_KIND_BY_TYPE: dict[type, str] = {
    spec.result_type: spec.kind for spec in RESULT_KINDS.values()
}


def kind_for(result_type: type) -> str:
    """結果クラスに対応する `kind` を返す。種類名を直書きしないための引き口。"""
    try:
        return _KIND_BY_TYPE[result_type]
    except KeyError as exc:
        raise InvalidInputError(f"unknown result type {result_type.__name__}") from exc


def kind_of(result: Result) -> str:
    """結果に対応する `kind` を返す。"""
    return kind_for(type(result))


def save_any(result: Result, path: str | Path) -> None:
    """結果の種類を見て保存する。"""
    _write_json(RESULT_KINDS[kind_of(result)].to_dict(result), path)


def load_any(path: str | Path) -> Result:
    """`kind` を見てエンベロープ / 離散 FC 因子のどちらかを復元する。"""
    data = _read_json(path)
    kind = data.get("kind") if isinstance(data, dict) else None
    # `kind` は JSON から来るので、文字列とは限らない（辞書ならハッシュもできない）。
    spec = RESULT_KINDS.get(kind) if isinstance(kind, str) else None
    if spec is None:
        known = ", ".join(sorted(RESULT_KINDS))
        raise InvalidInputError(f"unknown kind {kind!r} (known kinds: {known})")
    return spec.from_dict(data)
