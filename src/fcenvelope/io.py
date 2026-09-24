"""結果クラスの永続化。単一 JSON を round-trip の正準形式とする。

エンベロープ F(E)（`kind` = `"fcenvelope.envelope"`）と離散 FC 因子
（`kind` = `"fcenvelope.fc_lines"`）の 2 種類を扱う。どちらも計算に使った系と
条件（`conditions`）を結果ファイル側の固定の形で持ち、入力ファイルの形には合わせない
（ADR-0080）。モードは振動数と Huang-Rhys 因子 S で書くので、読み込み側に流儀の
曖昧さが残らない。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Sequence
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

#: 結果ファイルの版。入力ファイルの版（`inputs.SCHEMA_VERSION`）とは別に数える。
#: 結果ファイルは入力ファイルの形を写さないので（ADR-0080）、入力の書き方が変わっても
#: この版は上がらない。上がるのは結果ファイルそのものの形が変わるときだけである。
SCHEMA_VERSION = 4

#: 結果ファイルの形式の知識。計算側は常に cm^-1 しか扱わないので、単位は結果クラス
#: ではなく io が持つ（ADR-0047）。有次元の値は `[値, "単位"]` の組、表は `columns` に
#: `[列名, "単位"]` を並べる（入力ファイルの値と CSV の列と同じ書き方、ADR-0081）。
#: 読み込みはこの単位だけを受け、ほかの単位は `UnsupportedUnitError` で止める。
CANONICAL_ENERGY_UNIT = "cm^-1"
CANONICAL_DENSITY_UNIT = "1/cm^-1"
CANONICAL_TAU_UNIT = "cm"

_Column = tuple[str, str | None]
"""表の列。列名と、その列の値の単位（無次元なら None）。"""

#: 結果ファイルの表の列。書き出す並びもこの順である（ADR-0081）。
_MODE_COLUMNS: tuple[_Column, ...] = (("frequency", CANONICAL_ENERGY_UNIT), ("huang_rhys", None))
_SPECTRUM_COLUMNS: tuple[_Column, ...] = (
    ("energy", CANONICAL_ENERGY_UNIT),
    ("density", CANONICAL_DENSITY_UNIT),
)
_LINE_COLUMNS: tuple[_Column, ...] = (
    ("energy", CANONICAL_ENERGY_UNIT),
    ("fc_factor", None),
    ("weight", None),
    ("transitions", None),
)

#: 単位を持つ診断値。ここにないものは無次元（点数・割合・比・真偽）で、素の数で書く。
_DIAGNOSTIC_UNITS: dict[str, str] = {
    "d_tau": CANONICAL_TAU_UNIT,
    "tau_max": CANONICAL_TAU_UNIT,
    "mean_energy": CANONICAL_ENERGY_UNIT,
}

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
    """診断値を JSON の構造へ写す。単位を持つものは組にする。"""
    return {
        **{
            name: _with_unit(getattr(diagnostics, name), _DIAGNOSTIC_UNITS.get(name))
            for name in _diagnostic_readers(type(diagnostics))
        },
        "messages": list(diagnostics.messages),
    }


def _diagnostics_from_dict(cls: type[_D], data: JsonValue) -> _D:
    """JSON の構造から診断値を復元する。渡した型のインスタンスが返る。"""
    if not isinstance(data, dict):
        raise InvalidInputError(f"'diagnostics' must be a JSON object, got {type(data).__name__}")
    # フィールドと型の対応は dataclass から実行時に導くので（ADR-0036）、下の
    # 展開は型検査では追えない。取り違えは `_diagnostic_readers` が見ている。
    values: dict[str, JsonValue]
    try:
        values = {
            name: read(
                _without_unit(data[name], _DIAGNOSTIC_UNITS.get(name), f"diagnostics.{name}")
            )
            for name, read in _diagnostic_readers(cls).items()
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
        "conditions": {
            **_system_to_dict(result.system),
            "temperature": result.temperature,
            "broadening": {"sigma": _with_unit(result.broadening.sigma, CANONICAL_ENERGY_UNIT)},
            "grid": {
                "e_min": _with_unit(result.grid.e_min, CANONICAL_ENERGY_UNIT),
                "e_max": _with_unit(result.grid.e_max, CANONICAL_ENERGY_UNIT),
                "de": _with_unit(result.grid.de, CANONICAL_ENERGY_UNIT),
                "n_fft": result.grid.n_fft,
            },
        },
        "derived": _derived_to_dict(result.system),
        "diagnostics": _diagnostics_to_dict(result.diagnostics),
        "spectrum": _table_to_dict(
            _SPECTRUM_COLUMNS, zip(result.energy.tolist(), result.density.tolist())
        ),
    }


def _write_json(payload: JsonObject, path: str | Path) -> None:
    """出力 JSON を書き出す。

    浮動小数点は Python 標準 `json` の repr ベース出力により round-trip で完全一致する。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with stage(logger, f"write {target}"):
        with target.open("w", encoding="utf-8") as stream:
            stream.write(_format_json(payload))
            stream.write("\n")


def _inline(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def _is_flat(value: object) -> bool:
    """1 行に収める並びか。数・文字列と、それだけの並び（`[値, "単位"]` や `columns`）。"""
    if isinstance(value, list):
        return all(not isinstance(item, (dict, list)) or _is_flat(item) for item in value)
    return not isinstance(value, dict)


def _format_json(value: object, depth: int = 0, key: str | None = None) -> str:
    """JSON を人が覗いて読める形で書く。

    入れ子は字下げし、`[値, "単位"]` のような平たい並びは 1 行に、表の `rows` は 1 行ずつ
    書く（CSV を開いたときと同じ見え方にする）。値の書き方は `json` そのままなので、
    浮動小数点の round-trip は変わらない（ADR-0008）。
    """
    pad, inner = "  " * depth, "  " * (depth + 1)
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = (
            f"{inner}{_inline(name)}: {_format_json(item, depth + 1, name)}"
            for name, item in value.items()
        )
        return "{\n" + ",\n".join(items) + f"\n{pad}}}"
    if isinstance(value, list):
        if key == "rows" and value:
            return "[\n" + ",\n".join(f"{inner}{_inline(row)}" for row in value) + f"\n{pad}]"
        if _is_flat(value):
            return _inline(value)
        return (
            "[\n"
            + ",\n".join(f"{inner}{_format_json(item, depth + 1)}" for item in value)
            + f"\n{pad}]"
        )
    return _inline(value)


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
    return _as_float(_require(data, key, path), path)


def _as_float(value: JsonValue, path: str) -> float:
    # JSON の true / false は Python では int なので、明示的に弾く。数のつもりで
    # 真偽値を書いたファイルを 1.0 として黙って受けたくない（`_require_int` も同じ）。
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidInputError(f"{path!r} must be a number (got {value!r})")
    return float(value)


def _with_unit(value: object, unit: str | None) -> JsonValue:
    """有次元の値を `[値, "単位"]` の組にする。無次元（`unit` が None）なら素の値のまま。"""
    return value if unit is None else [value, unit]  # type: ignore[return-value]


def _check_unit(written: JsonValue, unit: str, path: str) -> None:
    if written != unit:
        raise UnsupportedUnitError(
            f"{path!r}: unsupported unit {written!r} (only {unit!r} is supported)"
        )


def _without_unit(value: JsonValue, unit: str | None, path: str) -> JsonValue:
    """`[値, "単位"]` の組から、単位を確かめて値を取り出す。無次元なら素の値のまま。"""
    if unit is None:
        return value
    if not isinstance(value, list) or len(value) != 2:
        raise InvalidInputError(f'{path!r} must be a [value, "unit"] pair (got {value!r})')
    _check_unit(value[1], unit, path)
    return value[0]


def _require_quantity(data: JsonValue, key: str, path: str, unit: str) -> float:
    """`[値, "単位"]` の組で書かれた有次元の値を読む。"""
    return _as_float(_without_unit(_require(data, key, path), unit, path), path)


def _table_to_dict(columns: Sequence[_Column], rows: Iterable[Sequence[object]]) -> JsonObject:
    """表を `columns` と `rows` の形へ写す。列は入力の CSV の `columns` と同じ書き方で、
    有次元の列は `[列名, "単位"]`、無次元の列は列名だけ（ADR-0081）。"""
    return {
        "columns": [name if unit is None else [name, unit] for name, unit in columns],
        "rows": [list(row) for row in rows],
    }


def _read_table(
    data: JsonValue, key: str, path: str, columns: Sequence[_Column]
) -> list[dict[str, JsonValue]]:
    """`columns` と `rows` の表を読み、各行を「列名 -> 値」の辞書にする。

    列の並びは問わないが、`columns` の列をちょうど 1 回ずつ並べ、有次元の列には正準単位を
    添えていなければならない。結果ファイルには既定の単位がないので、単位は省けない。
    """
    table = _require(data, key, path)
    written = _require(table, "columns", f"{path}.columns")
    if not isinstance(written, list):
        raise InvalidInputError(f"{path}.columns must be a list, got {type(written).__name__}")
    names: list[str] = []
    units: dict[str, JsonValue] = {}
    for index, spec in enumerate(written):
        if isinstance(spec, str):
            name, unit = spec, None
        elif isinstance(spec, list) and len(spec) == 2 and isinstance(spec[0], str):
            name, unit = spec
        else:
            raise InvalidInputError(
                f'{path}.columns[{index}] must be a name or a [name, "unit"] pair (got {spec!r})'
            )
        names.append(name)
        units[name] = unit
    expected = dict(columns)
    if len(set(names)) != len(names) or set(names) != set(expected):
        raise InvalidInputError(
            f"{path}.columns must list {list(expected)} once each (got {names})"
        )
    for name, unit in expected.items():
        location = f"{path}.columns[{names.index(name)}]"
        if unit is None:
            if units[name] is not None:
                raise InvalidInputError(f"{location}: {name!r} is dimensionless and takes no unit")
        else:
            _check_unit(units[name], unit, location)

    rows = _require(table, "rows", f"{path}.rows")
    if not isinstance(rows, list):
        raise InvalidInputError(f"{path}.rows must be a list, got {type(rows).__name__}")
    read: list[dict[str, JsonValue]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != len(names):
            raise InvalidInputError(
                f"{path}.rows[{index}] must be a list of {len(names)} values (got {row!r})"
            )
        read.append(dict(zip(names, row)))
    return read


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
    # null は float64 にすると黙って NaN になり、真偽値は 0 / 1 になるので、先に弾く。
    if not isinstance(data, list) or not all(
        isinstance(value, (int, float)) and not isinstance(value, bool) for value in data
    ):
        raise InvalidInputError(f"{path!r} must be a list of numbers")
    try:
        return np.asarray(data, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise InvalidInputError(f"{path!r} must be a list of numbers: {exc}") from exc


def _header_to_dict(kind: str, provenance: Provenance) -> JsonObject:
    """どの結果ファイルにも共通する先頭部分。1 箇所で書く（ADR-0036）。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "fcenvelope_version": provenance.fcenvelope_version,
        "created_at": _format_timestamp(provenance.created_at),
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


def _system_to_dict(system: VibrationalSystem) -> JsonObject:
    """系を計算条件の構造へ写す。結果ファイル側の固定の形で、入力ファイルの形には
    合わせない（ADR-0080）。モード表は `columns` と `rows` の表で書き、coupling は
    キー名どおり Huang-Rhys 因子 S である（無次元）。"""
    return {
        "modes": _table_to_dict(
            _MODE_COLUMNS, ((mode.frequency, mode.huang_rhys) for mode in system.modes)
        ),
    }


def _derived_to_dict(system: VibrationalSystem) -> JsonObject:
    """系から導かれる量。結果クラスは持たず、io が書き出す（ADR-0047）。"""
    return {
        "reorganization_energy": _with_unit(system.reorganization_energy, CANONICAL_ENERGY_UNIT)
    }


def _provenance_from_dict(data: JsonValue) -> Provenance:
    return Provenance(
        fcenvelope_version=str(_require(data, "fcenvelope_version", "fcenvelope_version")),
        created_at=_parse_timestamp(_require(data, "created_at", "created_at")),
    )


def _system_from_conditions(conditions: JsonValue) -> VibrationalSystem:
    """計算条件のモード表から系を組み立てる。"""
    return _build(VibrationalSystem, "conditions.modes", modes=_modes_from_conditions(conditions))


def _modes_from_conditions(conditions: JsonValue) -> tuple[VibrationalMode, ...]:
    """計算条件のモード表の各行を値の型にする。"""
    rows = _read_table(conditions, "modes", "conditions.modes", _MODE_COLUMNS)
    modes: list[VibrationalMode] = []
    for index, spec in enumerate(rows):
        location = f"conditions.modes.rows[{index}]"
        modes.append(
            _build(
                VibrationalMode,
                location,
                frequency=_require_float(spec, "frequency", f"{location}.frequency"),
                huang_rhys=_require_float(spec, "huang_rhys", f"{location}.huang_rhys"),
            )
        )
    return tuple(modes)


def envelope_from_dict(data: JsonValue) -> EnvelopeResult:
    """出力 JSON の構造から結果クラスを復元する。"""
    _check_header(data, ENVELOPE_KIND)

    conditions = _require(data, "conditions", "conditions")
    system = _system_from_conditions(conditions)
    broadening_conditions = _require(conditions, "broadening", "conditions.broadening")
    broadening = _build(
        Broadening,
        "conditions.broadening",
        sigma=_require_quantity(
            broadening_conditions,
            "sigma",
            "conditions.broadening.sigma",
            CANONICAL_ENERGY_UNIT,
        ),
    )
    grid_conditions = _require(conditions, "grid", "conditions.grid")
    grid = _build(
        EnergyGrid,
        "conditions.grid",
        e_min=_require_quantity(
            grid_conditions, "e_min", "conditions.grid.e_min", CANONICAL_ENERGY_UNIT
        ),
        e_max=_require_quantity(
            grid_conditions, "e_max", "conditions.grid.e_max", CANONICAL_ENERGY_UNIT
        ),
        de=_require_quantity(grid_conditions, "de", "conditions.grid.de", CANONICAL_ENERGY_UNIT),
        n_fft=_require_int(grid_conditions, "n_fft", "conditions.grid.n_fft"),
    )

    diagnostics = _diagnostics_from_dict(Diagnostics, _require(data, "diagnostics", "diagnostics"))

    spectrum = _read_table(data, "spectrum", "spectrum", _SPECTRUM_COLUMNS)
    energy = _float_array([row["energy"] for row in spectrum], "spectrum energy column")
    density = _float_array([row["density"] for row in spectrum], "spectrum density column")

    # `derived` は系から一意に決まる控えなので読み飛ばす（ADR-0047）。

    return EnvelopeResult(
        system=system,
        temperature=_require_float(conditions, "temperature", "conditions.temperature"),
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
        "conditions": {
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
        "lines": _table_to_dict(
            _LINE_COLUMNS,
            (
                (
                    line.energy,
                    line.fc_factor,
                    line.weight,
                    [
                        {
                            "mode": transition.mode_number,
                            "initial": transition.initial,
                            "final": transition.final,
                        }
                        for transition in line.transitions
                    ],
                )
                for line in result.lines
            ),
        ),
    }


def save_lines(result: LinesResult, path: str | Path) -> None:
    """離散 FC 因子の結果クラスを JSON として保存する。"""
    _write_json(lines_to_dict(result), path)


def _parse_transitions(
    data: JsonValue, index: int, n_modes: int
) -> tuple[ModeTransition, ...]:
    """線の遷移を読む。`mode` はモード表の行の番号で、1 から数える。"""
    if not isinstance(data, list):
        raise InvalidInputError(f"lines.rows[{index}].transitions must be a list")
    try:
        transitions = tuple(
            ModeTransition(
                mode_index=int(item["mode"]) - 1,
                initial=int(item["initial"]),
                final=int(item["final"]),
            )
            for item in data
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidInputError(f"lines.rows[{index}]: malformed transition: {exc}") from exc
    for transition in transitions:
        if not 1 <= transition.mode_number <= n_modes:
            raise InvalidInputError(
                f"lines.rows[{index}]: mode {transition.mode_number} is out of range "
                f"(modes are numbered 1 to {n_modes})"
            )
    return transitions


def lines_from_dict(data: JsonValue) -> LinesResult:
    """出力 JSON の構造から離散 FC 因子の結果クラスを復元する。"""
    _check_header(data, LINES_KIND)

    conditions = _require(data, "conditions", "conditions")
    system = _system_from_conditions(conditions)

    diagnostics = _diagnostics_from_dict(
        FCLineDiagnostics, _require(data, "diagnostics", "diagnostics")
    )

    selection_conditions = _require(conditions, "selection", "conditions.selection")
    selection = _build(
        Selection,
        "conditions.selection",
        min_weight=_require_float(
            selection_conditions, "min_weight", "conditions.selection.min_weight"
        ),
        max_lines=_require_int(selection_conditions, "max_lines", "conditions.selection.max_lines"),
        max_quanta=_optional_int(selection_conditions.get("max_quanta")),
    )
    lines_data = _read_table(data, "lines", "lines", _LINE_COLUMNS)
    try:
        lines = tuple(
            FCLine(
                energy=float(item["energy"]),
                fc_factor=float(item["fc_factor"]),
                weight=float(item["weight"]),
                transitions=_parse_transitions(item["transitions"], index, len(system.modes)),
            )
            for index, item in enumerate(lines_data)
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidInputError(f"malformed lines entry: {exc}") from exc

    # `derived` は系から一意に決まる控えなので読み飛ばす（ADR-0047）。

    return LinesResult(
        system=system,
        temperature=_require_float(conditions, "temperature", "conditions.temperature"),
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
        to_dict=envelope_to_dict,
        from_dict=envelope_from_dict,
    ),
    LINES_KIND: _ResultKind(
        kind=LINES_KIND,
        result_type=LinesResult,
        to_dict=lines_to_dict,
        from_dict=lines_from_dict,
    ),
}

_KIND_BY_TYPE: dict[type, str] = {spec.result_type: spec.kind for spec in RESULT_KINDS.values()}


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
