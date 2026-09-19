"""作図スクリプトの生成。雛形を読み、生成ヘッダの区画だけを差し替えて書き出す。

このモジュールは**図を描かない**。matplotlib に依存せず、テキストを書くだけである。
描画の設定は生成されたスクリプトの中にあり、書き出した後は利用者のものになる
（ADR-0057, 0058）。

雛形は `templates/` にそのまま走る Python ファイルとして置いてある（ADR-0059）。
生成が触るのは生成ヘッダのマーカーに挟まれた範囲だけで、それより下は写すだけである。
"""

from __future__ import annotations

import logging
import os
from importlib import resources
from pathlib import Path

from .errors import InvalidInputError
from .io import SCHEMA_VERSION, kind_of
from .logs import stage
from .result import EnvelopeResult, LinesResult, Result

__all__ = [
    "OVERLAY_TEMPLATE",
    "TEMPLATES",
    "image_path_for",
    "script_path_for",
    "write_overlay_script",
    "write_script",
]

logger = logging.getLogger(__name__)

#: 結果の型 -> 雛形の名前。種類を足すときはここに 1 行足す（ADR-0049）。
#: 重ね描きは表に載せない。種類ごとの処理ではなく「エンベロープと線」という特定の
#: 組み合わせに対する処理だからである（`plotting.DRAWERS` と同じ扱い）。
TEMPLATES: dict[type, str] = {
    EnvelopeResult: "envelope",
    LinesResult: "lines",
}

OVERLAY_TEMPLATE = "overlay"
"""重ね描きの雛形。表には載せず名前で呼ぶ。"""

HEADER_BEGIN = "# --- generated header (fcenvelope)"
"""生成ヘッダの開始マーカー。行頭の一致だけを見る。"""

HEADER_END = "# --- end generated header"
"""生成ヘッダの終了マーカー。"""

SCRIPT_SUFFIX = "_plot"
"""結果ファイルの名前に足して作図スクリプトの名前にする語。"""

IMAGE_PREFIX = "fcenvelope-"
"""画像ファイルの名前の頭。単独で持ち出されたときに出どころが残る（ADR-0061）。"""


def script_path_for(output: Path) -> Path:
    """結果ファイルの隣に置く作図スクリプトの既定の場所。

    スクリプトはデータの隣に残るものなので、結果ファイルの名前を継ぐ。
    """
    return output.with_name(f"{output.stem}{SCRIPT_SUFFIX}.py")


def image_path_for(script: Path) -> Path:
    """作図スクリプトが書き出す画像の既定の場所。

    画像は単独で持ち出されるので、どのプログラムが作った図かを名前に残す。名前に
    負わせるのはそこまでで、規則で情報を厳密に持たせようとはしない（ADR-0061）。
    """
    stem = script.stem.removesuffix(SCRIPT_SUFFIX)
    return script.with_name(f"{IMAGE_PREFIX}{stem}.png")


def write_script(
    result: Result, data: Path, script: Path, *, force: bool = False
) -> bool:
    """結果 1 つを描く作図スクリプトを書き出す。書いたなら True。

    生成先が既にあれば書かずに残す（ADR-0060）。調整の成果はスクリプトの側にしか
    ないので、生成が既存のファイルを黙って潰してはならない。
    """
    try:
        template = TEMPLATES[type(result)]
    except KeyError as exc:
        raise InvalidInputError(
            f"no plot script template for a {type(result).__name__}"
        ) from exc

    header = [
        _provenance(result, [data]),
        f"DATA = {_reference(data, script)}",
        f"OUTPUT = {_reference(image_path_for(script), script)}",
        f"KIND = {kind_of(result)!r}",
        f"SCHEMA_VERSION = {SCHEMA_VERSION}",
    ]
    return _write(template, header, script, force=force)


def write_overlay_script(
    envelope: EnvelopeResult,
    envelope_path: Path,
    lines: LinesResult,
    lines_path: Path,
    script: Path,
    *,
    force: bool = False,
) -> bool:
    """エンベロープと線を 1 枚に重ねる作図スクリプトを書き出す。書いたなら True。"""
    header = [
        _provenance(envelope, [envelope_path, lines_path]),
        f"ENVELOPE = {_reference(envelope_path, script)}",
        f"LINES = {_reference(lines_path, script)}",
        f"OUTPUT = {_reference(image_path_for(script), script)}",
        f"ENVELOPE_KIND = {kind_of(envelope)!r}",
        f"LINES_KIND = {kind_of(lines)!r}",
        f"SCHEMA_VERSION = {SCHEMA_VERSION}",
    ]
    return _write(OVERLAY_TEMPLATE, header, script, force=force)


def _provenance(result: Result, data: list[Path]) -> str:
    """生成ヘッダの先頭に置く 1 行。どの版が何から作ったかだけを書く。

    計算時刻は結果ファイルの側にあり、スクリプトは実行時にそれを読むので、ここには
    書き写さない（時刻の書式を 2 か所に持たないため）。
    """
    sources = " + ".join(path.name for path in data)
    return f"# fcenvelope {result.provenance.fcenvelope_version} -- {sources}"


def _reference(target: Path, script: Path) -> str:
    """スクリプトから見たファイルの位置を、スクリプトの中の式として書く。

    スクリプトと結果ファイルを一緒に別の場所へ移しても動くように、スクリプトからの
    相対で解決する。相対にできない位置なら絶対パスに落とす。
    """
    try:
        relative = os.path.relpath(target, script.parent)
    except ValueError:  # pragma: no cover - 別ドライブ（Windows）でしか起きない
        return f"Path({str(target.resolve())!r})"
    return f"Path(__file__).parent / {relative!r}"


def _write(template: str, header: list[str], script: Path, *, force: bool) -> bool:
    """雛形の生成ヘッダを差し替えて書き出す。既にあるなら書かない。"""
    if script.exists() and not force:
        return False

    text = _replace_header(_template_text(template), header)
    script.parent.mkdir(parents=True, exist_ok=True)
    with stage(logger, f"write {script}"):
        script.write_text(text, encoding="utf-8")
    return True


def _template_text(name: str) -> str:
    """雛形をパッケージデータとして読む。"""
    return (
        resources.files(__package__)
        .joinpath("templates", f"{name}.py")
        .read_text(encoding="utf-8")
    )


def _replace_header(text: str, header: list[str]) -> str:
    """マーカーに挟まれた範囲だけを差し替える。マーカーの行は残す。"""
    lines = text.splitlines()
    begins = [i for i, line in enumerate(lines) if line.startswith(HEADER_BEGIN)]
    ends = [i for i, line in enumerate(lines) if line.startswith(HEADER_END)]
    if len(begins) != 1 or len(ends) != 1 or ends[0] < begins[0]:
        raise InvalidInputError(
            "the plot script template does not have exactly one generated header"
        )
    replaced = lines[: begins[0] + 1] + header + lines[ends[0] :]
    return "\n".join(replaced) + "\n"
