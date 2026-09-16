"""結果クラスの永続化。単一 JSON を round-trip の正準形式とする。

エンベロープ F(E)（`kind` = `"fcenvelope.envelope"`）と離散 FC 因子
（`kind` = `"fcenvelope.fc_lines"`）の 2 種類を扱う。どちらも入力エコーは常に
正準形（`coupling_convention` = `"huang_rhys"`）で書き出す。これにより
読み込み側に流儀の曖昧さが残らない。
"""

from __future__ import annotations

import json
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
from .units import CANONICAL_FREQUENCY_UNIT, HUANG_RHYS, check_frequency_unit
from .result import (
    EnvelopeDiagnostics,
    EnvelopeResult,
    FCLine,
    LinesDiagnostics,
    LinesResult,
    ModeTransition,
)

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

_DIAGNOSTIC_FLOAT_FIELDS = (
    "d_tau",
    "tau_max",
    "damping_at_tau_max",
    "total_area",
    "window_captured_fraction",
    "edge_density_ratio",
    "max_imaginary_ratio",
)

_LINE_DIAGNOSTIC_FLOAT_FIELDS = (
    "captured_weight",
    "mean_energy",
    "min_mode_completeness",
)
_LINE_DIAGNOSTIC_INT_FIELDS = ("n_lines", "max_initial_quanta", "max_final_quanta")
_LINE_DIAGNOSTIC_BOOL_FIELDS = ("beam_truncated", "recurrence_limited")


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


def envelope_to_dict(result: EnvelopeResult) -> dict[str, Any]:
    """結果クラスを出力 JSON の構造（§8.2）へ写す。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": ENVELOPE_KIND,
        "fcenvelope_version": result.fcenvelope_version,
        "created_at": _format_timestamp(result.created_at),
        "energy_unit": result.energy_unit,
        "density_unit": result.density_unit,
        "input": {
            "frequency_unit": CANONICAL_FREQUENCY_UNIT,
            "coupling_convention": HUANG_RHYS.key,
            "modes": [
                {"frequency": mode.frequency, "coupling": mode.huang_rhys}
                for mode in result.modes
            ],
            "temperature": result.temperature,
            "broadening": result.broadening.model_dump(),
            "grid": result.grid.model_dump(),
        },
        "derived": {"reorganization_energy": result.reorganization_energy},
        "diagnostics": {
            "n_fft": result.diagnostics.n_fft,
            **{
                name: getattr(result.diagnostics, name) for name in _DIAGNOSTIC_FLOAT_FIELDS
            },
            "messages": list(result.diagnostics.messages),
        },
        "spectrum": {
            "energy": result.energy.tolist(),
            "density": result.density.tolist(),
        },
    }


def _write_json(payload: dict[str, Any], path: str | Path) -> None:
    """出力 JSON を書き出す。

    浮動小数点は Python 標準 `json` の repr ベース出力により round-trip で完全一致する。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def save_envelope(result: EnvelopeResult, path: str | Path) -> None:
    """エンベロープの結果クラスを JSON として保存する。"""
    _write_json(envelope_to_dict(result), path)


def _require(data: dict[str, Any], key: str, path: str) -> Any:
    if key not in data:
        raise InvalidInputError(f"missing field {path!r} in result file")
    return data[key]


def envelope_from_dict(data: Any) -> EnvelopeResult:
    """出力 JSON の構造から結果クラスを復元する。"""
    if not isinstance(data, dict):
        raise InvalidInputError(f"result file must contain a JSON object, got {type(data).__name__}")

    version = _require(data, "schema_version", "schema_version")
    if version != SCHEMA_VERSION:
        raise SchemaVersionError(
            f"unsupported schema_version {version!r} (this build supports {SCHEMA_VERSION})"
        )

    kind = data.get("kind")
    if kind != ENVELOPE_KIND:
        raise InvalidInputError(f"unexpected kind {kind!r} (expected {ENVELOPE_KIND!r})")

    energy_unit = data.get("energy_unit", CANONICAL_ENERGY_UNIT)
    density_unit = data.get("density_unit", CANONICAL_DENSITY_UNIT)
    if energy_unit != CANONICAL_ENERGY_UNIT:
        raise UnsupportedUnitError(
            f"unsupported energy_unit {energy_unit!r} (only {CANONICAL_ENERGY_UNIT!r} is supported)"
        )
    if density_unit != CANONICAL_DENSITY_UNIT:
        raise UnsupportedUnitError(
            f"unsupported density_unit {density_unit!r} "
            f"(only {CANONICAL_DENSITY_UNIT!r} is supported)"
        )

    echo = _require(data, "input", "input")
    modes = _parse_input_echo(echo)
    broadening = Broadening.from_obj(_require(echo, "broadening", "input.broadening"))
    grid = EnergyGrid.from_obj(_require(echo, "grid", "input.grid"))

    diagnostics_data = _require(data, "diagnostics", "diagnostics")
    try:
        diagnostics = EnvelopeDiagnostics(
            n_fft=int(diagnostics_data["n_fft"]),
            messages=tuple(diagnostics_data.get("messages", ())),
            **{name: float(diagnostics_data[name]) for name in _DIAGNOSTIC_FLOAT_FIELDS},
        )
    except KeyError as exc:
        raise InvalidInputError(f"missing diagnostics field {exc.args[0]!r}") from exc

    spectrum = _require(data, "spectrum", "spectrum")
    energy = np.asarray(_require(spectrum, "energy", "spectrum.energy"), dtype=np.float64)
    density = np.asarray(_require(spectrum, "density", "spectrum.density"), dtype=np.float64)
    if energy.shape != density.shape:
        raise InvalidInputError(
            f"spectrum.energy and spectrum.density length mismatch: "
            f"{energy.shape[0]} vs {density.shape[0]}"
        )

    derived = data.get("derived", {})

    return EnvelopeResult(
        energy=energy,
        density=density,
        modes=modes,
        temperature=float(_require(echo, "temperature", "input.temperature")),
        broadening=broadening,
        grid=grid,
        reorganization_energy=float(_require(derived, "reorganization_energy", "derived.reorganization_energy")),
        diagnostics=diagnostics,
        fcenvelope_version=str(_require(data, "fcenvelope_version", "fcenvelope_version")),
        created_at=_parse_timestamp(_require(data, "created_at", "created_at")),
        energy_unit=energy_unit,
        density_unit=density_unit,
    )


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


def load_envelope(path: str | Path) -> EnvelopeResult:
    """保存済み JSON からエンベロープの結果クラスを復元する。"""
    return envelope_from_dict(_read_json(path))


def lines_to_dict(result: LinesResult) -> dict[str, Any]:
    """離散 FC 因子の結果クラスを出力 JSON の構造へ写す。"""
    diagnostics = result.diagnostics
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": LINES_KIND,
        "fcenvelope_version": result.fcenvelope_version,
        "created_at": _format_timestamp(result.created_at),
        "energy_unit": result.energy_unit,
        "input": {
            "frequency_unit": CANONICAL_FREQUENCY_UNIT,
            "coupling_convention": HUANG_RHYS.key,
            "modes": [
                {"frequency": mode.frequency, "coupling": mode.huang_rhys}
                for mode in result.modes
            ],
            "temperature": result.temperature,
        },
        "selection": result.selection.model_dump(),
        "derived": {"reorganization_energy": result.reorganization_energy},
        "diagnostics": {
            **{
                name: getattr(diagnostics, name)
                for name in (
                    *_LINE_DIAGNOSTIC_INT_FIELDS,
                    *_LINE_DIAGNOSTIC_FLOAT_FIELDS,
                    *_LINE_DIAGNOSTIC_BOOL_FIELDS,
                )
            },
            "messages": list(diagnostics.messages),
        },
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
    if not isinstance(data, dict):
        raise InvalidInputError(
            f"result file must contain a JSON object, got {type(data).__name__}"
        )

    version = _require(data, "schema_version", "schema_version")
    if version != SCHEMA_VERSION:
        raise SchemaVersionError(
            f"unsupported schema_version {version!r} (this build supports {SCHEMA_VERSION})"
        )

    kind = data.get("kind")
    if kind != LINES_KIND:
        raise InvalidInputError(f"unexpected kind {kind!r} (expected {LINES_KIND!r})")

    energy_unit = data.get("energy_unit", CANONICAL_ENERGY_UNIT)
    if energy_unit != CANONICAL_ENERGY_UNIT:
        raise UnsupportedUnitError(
            f"unsupported energy_unit {energy_unit!r} (only {CANONICAL_ENERGY_UNIT!r} is supported)"
        )

    echo = _require(data, "input", "input")
    modes = _parse_input_echo(echo)

    diagnostics_data = _require(data, "diagnostics", "diagnostics")
    try:
        diagnostics = LinesDiagnostics(
            messages=tuple(diagnostics_data.get("messages", ())),
            **{name: int(diagnostics_data[name]) for name in _LINE_DIAGNOSTIC_INT_FIELDS},
            **{name: float(diagnostics_data[name]) for name in _LINE_DIAGNOSTIC_FLOAT_FIELDS},
            **{name: bool(diagnostics_data[name]) for name in _LINE_DIAGNOSTIC_BOOL_FIELDS},
        )
    except KeyError as exc:
        raise InvalidInputError(f"missing diagnostics field {exc.args[0]!r}") from exc

    selection = _require(data, "selection", "selection")
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

    derived = data.get("derived", {})

    return LinesResult(
        lines=lines,
        modes=modes,
        temperature=float(_require(echo, "temperature", "input.temperature")),
        selection=Selection.from_obj(selection),
        reorganization_energy=float(
            _require(derived, "reorganization_energy", "derived.reorganization_energy")
        ),
        diagnostics=diagnostics,
        fcenvelope_version=str(_require(data, "fcenvelope_version", "fcenvelope_version")),
        created_at=_parse_timestamp(_require(data, "created_at", "created_at")),
        energy_unit=energy_unit,
    )


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
