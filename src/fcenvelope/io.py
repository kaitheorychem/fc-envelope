"""結果クラスの永続化。単一 JSON を round-trip の正準形式とする。

入力エコーは常に正準形（`coupling_convention` = `"huang_rhys"`）で書き出す。
これにより `load_result` に流儀の曖昧さが残らない。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .errors import InvalidInputError, SchemaVersionError, UnsupportedUnitError
from .models import (
    CANONICAL_FREQUENCY_UNIT,
    SCHEMA_VERSION,
    CouplingConvention,
    FCEnvelopeInput,
)
from .result import Diagnostics, FCEnvelopeResult

__all__ = ["RESULT_KIND", "load_result", "save_result"]

RESULT_KIND = "fcenvelope.result"
CANONICAL_ENERGY_UNIT = "cm^-1"
CANONICAL_INTENSITY_UNIT = "1/cm^-1"

_DIAGNOSTIC_FLOAT_FIELDS = (
    "d_tau",
    "tau_max",
    "sigma_tau_max",
    "total_area",
    "window_captured_fraction",
    "edge_intensity_ratio",
    "max_imaginary_ratio",
)


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


def result_to_dict(result: FCEnvelopeResult) -> dict[str, Any]:
    """結果クラスを出力 JSON の構造（§8.2）へ写す。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": RESULT_KIND,
        "fcenvelope_version": result.fcenvelope_version,
        "created_at": _format_timestamp(result.created_at),
        "energy_unit": result.energy_unit,
        "intensity_unit": result.intensity_unit,
        "input": {
            "frequency_unit": CANONICAL_FREQUENCY_UNIT,
            "coupling_convention": CouplingConvention.HUANG_RHYS.value,
            "modes": [
                {"frequency": mode.frequency, "coupling": mode.huang_rhys}
                for mode in result.modes
            ],
            "conditions": result.conditions.model_dump(),
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
            "intensity": result.intensity.tolist(),
        },
    }


def save_result(result: FCEnvelopeResult, path: str | Path) -> None:
    """結果クラスを JSON として保存する。

    浮動小数点は Python 標準 `json` の repr ベース出力により round-trip で完全一致する。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as stream:
        json.dump(result_to_dict(result), stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def _require(data: dict[str, Any], key: str, path: str) -> Any:
    if key not in data:
        raise InvalidInputError(f"missing field {path!r} in result file")
    return data[key]


def result_from_dict(data: Any) -> FCEnvelopeResult:
    """出力 JSON の構造から結果クラスを復元する。"""
    if not isinstance(data, dict):
        raise InvalidInputError(f"result file must contain a JSON object, got {type(data).__name__}")

    version = _require(data, "schema_version", "schema_version")
    if version != SCHEMA_VERSION:
        raise SchemaVersionError(
            f"unsupported schema_version {version!r} (this build supports {SCHEMA_VERSION})"
        )

    kind = data.get("kind")
    if kind != RESULT_KIND:
        raise InvalidInputError(f"unexpected kind {kind!r} (expected {RESULT_KIND!r})")

    energy_unit = data.get("energy_unit", CANONICAL_ENERGY_UNIT)
    intensity_unit = data.get("intensity_unit", CANONICAL_INTENSITY_UNIT)
    if energy_unit != CANONICAL_ENERGY_UNIT:
        raise UnsupportedUnitError(
            f"unsupported energy_unit {energy_unit!r} (only {CANONICAL_ENERGY_UNIT!r} is supported)"
        )
    if intensity_unit != CANONICAL_INTENSITY_UNIT:
        raise UnsupportedUnitError(
            f"unsupported intensity_unit {intensity_unit!r} "
            f"(only {CANONICAL_INTENSITY_UNIT!r} is supported)"
        )

    echo = dict(_require(data, "input", "input"))
    echo.setdefault("schema_version", SCHEMA_VERSION)
    parsed_input = FCEnvelopeInput.from_obj(echo)

    diagnostics_data = _require(data, "diagnostics", "diagnostics")
    try:
        diagnostics = Diagnostics(
            n_fft=int(diagnostics_data["n_fft"]),
            messages=tuple(diagnostics_data.get("messages", ())),
            **{name: float(diagnostics_data[name]) for name in _DIAGNOSTIC_FLOAT_FIELDS},
        )
    except KeyError as exc:
        raise InvalidInputError(f"missing diagnostics field {exc.args[0]!r}") from exc

    spectrum = _require(data, "spectrum", "spectrum")
    energy = np.asarray(_require(spectrum, "energy", "spectrum.energy"), dtype=np.float64)
    intensity = np.asarray(_require(spectrum, "intensity", "spectrum.intensity"), dtype=np.float64)
    if energy.shape != intensity.shape:
        raise InvalidInputError(
            f"spectrum.energy and spectrum.intensity length mismatch: "
            f"{energy.shape[0]} vs {intensity.shape[0]}"
        )

    derived = data.get("derived", {})

    return FCEnvelopeResult(
        energy=energy,
        intensity=intensity,
        modes=tuple(parsed_input.to_modes()),
        conditions=parsed_input.conditions,
        reorganization_energy=float(_require(derived, "reorganization_energy", "derived.reorganization_energy")),
        diagnostics=diagnostics,
        fcenvelope_version=str(_require(data, "fcenvelope_version", "fcenvelope_version")),
        created_at=_parse_timestamp(_require(data, "created_at", "created_at")),
        energy_unit=energy_unit,
        intensity_unit=intensity_unit,
    )


def load_result(path: str | Path) -> FCEnvelopeResult:
    """保存済み JSON から結果クラスを復元する。"""
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise InvalidInputError(f"cannot read result file {source}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidInputError(f"invalid JSON in {source}: {exc}") from exc
    return result_from_dict(data)
