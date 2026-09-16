"""結果クラスの永続化。単一 JSON を round-trip の正準形式とする。

エンベロープ F(E)（`kind` = `"fcenvelope.envelope"`）と離散 FC 因子
（`kind` = `"fcenvelope.fc_lines"`）の 2 種類を扱う。どちらも入力エコーは常に
正準形（`coupling_convention` = `"huang_rhys"`）で書き出す。これにより
読み込み側に流儀の曖昧さが残らない。

2 系統のファイルは同じ骨格を持つ。

    schema_version / kind / 来歴 / 単位 / 入力エコー / derived / diagnostics
    + 系統ごとのペイロード（spectrum / selection + lines）

この骨格の読み書きは `_to_dict` と `_common_fields` の 2 つだけが知っている。
診断値のフィールド名も `dataclasses.fields()` から導出し、手書きのタプルを
dataclass と二重に持たない。dataclass にフィールドを足してタプルに足し忘れれば
静かに壊れる、という類の重複だけを機械的に潰している（ADR-0036）。
"""

from __future__ import annotations

import json
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import ValidationError

from .errors import InvalidInputError, SchemaVersionError, UnsupportedUnitError
from .models import (
    SCHEMA_VERSION,
    Broadening,
    EnergyGrid,
    Selection,
    VibrationalMode,
)
from .result import (
    EnvelopeDiagnostics,
    EnvelopeResult,
    FCLine,
    LinesDiagnostics,
    LinesResult,
    ModeTransition,
)
from .units import CANONICAL_FREQUENCY_UNIT, HUANG_RHYS, check_frequency_unit

__all__ = [
    "ENVELOPE_KIND",
    "LINES_KIND",
    "load_any",
    "load_envelope",
    "load_lines",
    "save_envelope",
    "save_lines",
]

ENVELOPE_KIND = "fcenvelope.envelope"
LINES_KIND = "fcenvelope.fc_lines"
CANONICAL_ENERGY_UNIT = "cm^-1"
CANONICAL_DENSITY_UNIT = "1/cm^-1"

#: 系統ごとの単位フィールド: 結果クラスの属性名（= JSON のキー）-> 正準値。
_ENVELOPE_UNITS = {
    "energy_unit": CANONICAL_ENERGY_UNIT,
    "density_unit": CANONICAL_DENSITY_UNIT,
}
_LINES_UNITS = {"energy_unit": CANONICAL_ENERGY_UNIT}

#: 診断値の復元に使う型変換。`dataclasses.fields()` の `type` は文字列で来る
#: （`from __future__ import annotations` のため）。
_SCALAR_PARSERS = {"int": int, "float": float, "bool": bool}


def _format_timestamp(moment: datetime) -> str:
    """UTC・秒精度の ISO 8601 文字列（末尾 Z）にする。"""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).replace(microsecond=0, tzinfo=None).isoformat() + "Z"


def _parse_timestamp(text: Any) -> datetime:
    if not isinstance(text, str):
        raise InvalidInputError(f"created_at must be a string, got {type(text).__name__}")
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidInputError(f"invalid created_at {text!r}: {exc}") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _require(data: dict[str, Any], key: str, path: str) -> Any:
    if key not in data:
        raise InvalidInputError(f"missing field {path!r} in result file")
    return data[key]


# --- 診断値: フィールド表は dataclass から導出する ---


def _diagnostic_fields(diagnostics_type: type) -> tuple[tuple[str, Any], ...]:
    """`messages` 以外の (名前, 変換関数) を宣言順に返す。"""
    table = []
    for entry in fields(diagnostics_type):
        if entry.name == "messages":
            continue
        parser = _SCALAR_PARSERS.get(entry.type)
        if parser is None:  # pragma: no cover - 診断値は int/float/bool のみ
            raise TypeError(
                f"{diagnostics_type.__name__}.{entry.name} has unsupported type "
                f"{entry.type!r}; add it to _SCALAR_PARSERS"
            )
        table.append((entry.name, parser))
    return tuple(table)


def _diagnostics_to_dict(diagnostics: Any) -> dict[str, Any]:
    payload = {
        name: getattr(diagnostics, name)
        for name, _ in _diagnostic_fields(type(diagnostics))
    }
    payload["messages"] = list(diagnostics.messages)
    return payload


def _diagnostics_from_dict(diagnostics_type: type, data: Any):
    if not isinstance(data, dict):
        raise InvalidInputError(
            f"diagnostics must be a JSON object, got {type(data).__name__}"
        )
    try:
        values = {
            name: parser(data[name]) for name, parser in _diagnostic_fields(diagnostics_type)
        }
    except KeyError as exc:
        raise InvalidInputError(f"missing diagnostics field {exc.args[0]!r}") from exc
    except (TypeError, ValueError) as exc:
        raise InvalidInputError(f"malformed diagnostics: {exc}") from exc
    return diagnostics_type(messages=tuple(data.get("messages", ())), **values)


# --- 共通の骨格 ---


def _to_dict(
    result: Any,
    *,
    kind: str,
    units: dict[str, str],
    input_extra: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """両系統に共通する骨格を組み、系統ごとの節を差し込む。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "fcenvelope_version": result.fcenvelope_version,
        "created_at": _format_timestamp(result.created_at),
        **{name: getattr(result, name) for name in units},
        "input": {
            "frequency_unit": CANONICAL_FREQUENCY_UNIT,
            "coupling_convention": HUANG_RHYS.key,
            "modes": [
                {"frequency": mode.frequency, "coupling": mode.huang_rhys}
                for mode in result.modes
            ],
            "temperature": result.temperature,
            **input_extra,
        },
        "derived": {"reorganization_energy": result.reorganization_energy},
        "diagnostics": _diagnostics_to_dict(result.diagnostics),
        **payload,
    }


def _parse_input_echo(echo: Any) -> tuple[VibrationalMode, ...]:
    """入力エコーの単位と流儀を検査し、正準表現のモード列を取り出す。

    エコーは常に正準形（`coupling_convention` = `"huang_rhys"`）で書き出される。
    他の流儀は読み込み側に曖昧さを残すので受け付けない。
    """
    if not isinstance(echo, dict):
        raise InvalidInputError(f"input must be a JSON object, got {type(echo).__name__}")

    check_frequency_unit(echo.get("frequency_unit", CANONICAL_FREQUENCY_UNIT))
    convention = echo.get("coupling_convention", HUANG_RHYS.key)
    if convention != HUANG_RHYS.key:
        raise InvalidInputError(
            f"input.coupling_convention must be {HUANG_RHYS.key!r} (got {convention!r})"
        )
    try:
        return tuple(
            VibrationalMode(frequency=spec["frequency"], huang_rhys=spec["coupling"])
            for spec in _require(echo, "modes", "input.modes")
        )
    except (KeyError, TypeError, ValidationError, InvalidInputError) as exc:
        raise InvalidInputError(f"malformed input.modes: {exc}") from exc


def _common_fields(
    data: Any,
    *,
    kind: str,
    units: dict[str, str],
    diagnostics_type: type,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """骨格を検査して復元し、(結果クラスの共通引数, 入力エコー) を返す。"""
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

    resolved = {}
    for name, canonical in units.items():
        value = data.get(name, canonical)
        if value != canonical:
            raise UnsupportedUnitError(
                f"unsupported {name} {value!r} (only {canonical!r} is supported)"
            )
        resolved[name] = value

    echo = _require(data, "input", "input")
    derived = data.get("derived", {})

    common = {
        "modes": _parse_input_echo(echo),
        "temperature": float(_require(echo, "temperature", "input.temperature")),
        "reorganization_energy": float(
            _require(derived, "reorganization_energy", "derived.reorganization_energy")
        ),
        "diagnostics": _diagnostics_from_dict(
            diagnostics_type, _require(data, "diagnostics", "diagnostics")
        ),
        "fcenvelope_version": str(
            _require(data, "fcenvelope_version", "fcenvelope_version")
        ),
        "created_at": _parse_timestamp(_require(data, "created_at", "created_at")),
        **resolved,
    }
    return common, echo


def _write_json(payload: dict[str, Any], path: str | Path) -> None:
    """出力 JSON を書き出す。

    浮動小数点は Python 標準 `json` の repr ベース出力により round-trip で完全一致する。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def _read_json(path: str | Path) -> Any:
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise InvalidInputError(f"cannot read result file {source}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidInputError(f"invalid JSON in {source}: {exc}") from exc


# --- エンベロープ ---


def envelope_to_dict(result: EnvelopeResult) -> dict[str, Any]:
    """エンベロープの結果クラスを出力 JSON の構造へ写す。"""
    return _to_dict(
        result,
        kind=ENVELOPE_KIND,
        units=_ENVELOPE_UNITS,
        input_extra={
            "broadening": result.broadening.model_dump(),
            "grid": result.grid.model_dump(),
        },
        payload={
            "spectrum": {
                "energy": result.energy.tolist(),
                "density": result.density.tolist(),
            }
        },
    )


def envelope_from_dict(data: Any) -> EnvelopeResult:
    """出力 JSON の構造からエンベロープの結果クラスを復元する。"""
    common, echo = _common_fields(
        data,
        kind=ENVELOPE_KIND,
        units=_ENVELOPE_UNITS,
        diagnostics_type=EnvelopeDiagnostics,
    )

    spectrum = _require(data, "spectrum", "spectrum")
    energy = np.asarray(_require(spectrum, "energy", "spectrum.energy"), dtype=np.float64)
    density = np.asarray(_require(spectrum, "density", "spectrum.density"), dtype=np.float64)
    if energy.shape != density.shape:
        raise InvalidInputError(
            f"spectrum.energy and spectrum.density length mismatch: "
            f"{energy.shape[0]} vs {density.shape[0]}"
        )

    return EnvelopeResult(
        energy=energy,
        density=density,
        broadening=Broadening.from_obj(_require(echo, "broadening", "input.broadening")),
        grid=EnergyGrid.from_obj(_require(echo, "grid", "input.grid")),
        **common,
    )


def save_envelope(result: EnvelopeResult, path: str | Path) -> None:
    """エンベロープの結果クラスを JSON として保存する。"""
    _write_json(envelope_to_dict(result), path)


def load_envelope(path: str | Path) -> EnvelopeResult:
    """保存済み JSON からエンベロープの結果クラスを復元する。"""
    return envelope_from_dict(_read_json(path))


# --- 離散 FC 因子 ---


def lines_to_dict(result: LinesResult) -> dict[str, Any]:
    """離散 FC 因子の結果クラスを出力 JSON の構造へ写す。"""
    return _to_dict(
        result,
        kind=LINES_KIND,
        units=_LINES_UNITS,
        input_extra={},
        payload={
            "selection": result.selection.model_dump(),
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
        },
    )


def _parse_transitions(data: Any, index: int) -> tuple[ModeTransition, ...]:
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


def lines_from_dict(data: Any) -> LinesResult:
    """出力 JSON の構造から離散 FC 因子の結果クラスを復元する。"""
    common, _ = _common_fields(
        data,
        kind=LINES_KIND,
        units=_LINES_UNITS,
        diagnostics_type=LinesDiagnostics,
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

    return LinesResult(
        lines=lines,
        selection=Selection.from_obj(_require(data, "selection", "selection")),
        **common,
    )


def save_lines(result: LinesResult, path: str | Path) -> None:
    """離散 FC 因子の結果クラスを JSON として保存する。"""
    _write_json(lines_to_dict(result), path)


def load_lines(path: str | Path) -> LinesResult:
    """保存済み JSON から離散 FC 因子の結果クラスを復元する。"""
    return lines_from_dict(_read_json(path))


def load_any(path: str | Path) -> EnvelopeResult | LinesResult:
    """`kind` を見てエンベロープ / 離散 FC 因子のどちらかを復元する。"""
    data = _read_json(path)
    kind = data.get("kind") if isinstance(data, dict) else None
    if kind == LINES_KIND:
        return lines_from_dict(data)
    return envelope_from_dict(data)
