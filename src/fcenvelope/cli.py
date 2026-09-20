"""typer による CLI。

終了コード: 0 正常 / 1 `FCEnvelopeError` / 2 typer の使用法エラー。

図は描かない。計算に添えて**作図スクリプト**を書き出し、図はそれを走らせて作る
（ADR-0057, 0061）。図のつまみは CLI に置かない——調整はスクリプトを直して行う。

入力ファイルの項目を差し替えるつまみは `--override key=value` 1 つに畳んである
（ADR-0064）。キーは入力ファイル中の項目の位置そのもので、CLI 側にその写しを持たない。
実際に使われた設定は、計算を始める前に `RESULT_config.json` へ書き出す（ADR-0065）。

`-o` は省略できる。省略時の出力は入力ファイルの名前を継いで、その隣に置く（ADR-0063）。

節目のログは `--log` で指定したファイルに書く。指定がなければメモリに溜めるだけで、
異常終了したときにだけ出力先の隣へ書き出す（ADR-0052）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Annotated, Optional, TypeVar

import typer

from . import emit, logs
from .envelope import compute_envelope
from .errors import FCEnvelopeError
from .inputs import FCEnvelopeInput
from .io import JsonObject, JsonValue, kind_for, load_any, save_any
from .lines import compute_fc_lines
from .result import EnvelopeResult, FCLine, LinesResult, Result
from .version import __version__

__all__ = ["app"]

logger = logging.getLogger(__name__)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Franck-Condon envelope F(E) from vibronic couplings, frequencies and temperature.",
)


#: `--log` の宣言。3 つの副命令で同じものを使う（ADR-0036）。
LogFile = Annotated[
    Optional[Path],
    typer.Option(
        "--log",
        help=(
            "Write the stage-by-stage log to this file. "
            "Without it, the log is kept in memory and only written next to "
            "the output when the run fails."
        ),
    ),
]


#: 作図スクリプトのつまみ。`run` と `lines` で同じものを使う（ADR-0036）。
ScriptFile = Annotated[
    Optional[Path],
    typer.Option(
        "--script",
        help=(
            "Write the plot script here. "
            "Without it, the script goes next to the output (RESULT_plot.py)."
        ),
    ),
]

NoScript = Annotated[
    bool,
    typer.Option(
        "--no-script",
        help="Do not write a plot script. Use this when sweeping conditions.",
    ),
]

ForceScript = Annotated[
    bool,
    typer.Option(
        "--force-script",
        help="Overwrite the plot script instead of keeping the existing one.",
    ),
]


#: 上書きの口。`run` と `lines` で同じものを使う（ADR-0036, 0064）。
Overrides = Annotated[
    Optional[list[str]],
    typer.Option(
        "--override",
        metavar="KEY=VALUE",
        help=(
            "Override one field of the input file, e.g. --override temperature=0 "
            "or --override grid.de=2.5. Nested fields are dotted, values are read "
            "as JSON (null, numbers, strings) and in the input file's own units "
            "and convention. Repeatable. modes cannot be overridden."
        ),
    ),
]


#: 実効設定の書き出し。`run` と `lines` で同じものを使う（ADR-0036, 0065）。
ConfigFile = Annotated[
    Optional[Path],
    typer.Option(
        "--config",
        help=(
            "Write the settings this run actually uses here. "
            "Without it, they go next to the output (RESULT_config.json)."
        ),
    ),
]

NoConfig = Annotated[
    bool,
    typer.Option("--no-config", help="Do not write the effective settings."),
]


#: `-o` を省いたときの出力名に入れる種類の接尾辞（ADR-0063）。これがないと既定の
#: 出力名が入力ファイルと一致して入力を踏み潰し、`run` と `lines` の出力も衝突する。
ENVELOPE_SUFFIX = "_envelope"
LINES_SUFFIX = "_lines"

#: 実効設定の書き出し先に付ける接尾辞（ADR-0065）。
CONFIG_SUFFIX = "_config"


def _output_path(output: Path | None, input_path: Path, suffix: str) -> Path:
    """結果の置き場。`-o` がなければ入力ファイルの隣に、その名前を継いで置く。

    `modes` の相対パスと同じく入力ファイルの位置を基準にするので、どこから呼んでも
    結果の置き場が変わらない（ADR-0063）。
    """
    if output is not None:
        return output
    return input_path.with_name(f"{input_path.stem}{suffix}.json")


def _config_path(output: Path) -> Path:
    """`--config` がないときの実効設定の置き場。結果の隣に置く。"""
    return output.with_name(f"{output.stem}{CONFIG_SUFFIX}.json")


def _emit_config(
    parsed: FCEnvelopeInput,
    output: Path,
    *,
    config: Path | None,
    no_config: bool,
) -> None:
    """その実行で実際に使われる設定を、計算を始める前に書き出す（ADR-0065）。

    作図スクリプトと違って既にあるものは常に上書きする。古いものを残すと「この実行の
    設定」という名目が嘘になるし、手で直して使うものでもない。
    """
    if no_config:
        if config is not None:
            raise typer.BadParameter(
                "--config and --no-config cannot be used together",
                param_hint="--no-config",
            )
        return

    target = config if config is not None else _config_path(output)
    parsed.save(target)
    typer.echo(f"wrote {target}")


def _emit_script(
    result: Result,
    data: Path,
    *,
    script: Path | None,
    no_script: bool,
    force: bool,
) -> None:
    """計算に添えて作図スクリプトを書き出す（ADR-0060）。

    生成は既定で行い、既にあるものは上書きせずに残す。調整の成果はスクリプトの側に
    しかないので、条件を振って計算をやり直しても図の設定は生き残る。
    """
    if no_script:
        if script is not None:
            raise typer.BadParameter(
                "--script and --no-script cannot be used together",
                param_hint="--no-script",
            )
        return

    target = script if script is not None else emit.script_path_for(data)
    if emit.write_script(result, data, target, force=force):
        typer.echo(f"wrote {target}")
    else:
        typer.echo(f"kept {target} (--force-script to regenerate)")


def _trace_path(output: Path) -> Path:
    """`--log` がないとき、異常終了の痕跡を残す場所。出力ファイルの隣に置く。"""
    return output.with_suffix(".log")


def _echo_trace(written: Path | None) -> None:
    """痕跡を残した場所を知らせる。残せなかった場合は何も言わない。"""
    if written is not None:
        typer.secho(f"wrote the log up to the failure to {written}", err=True)


#: 痕跡を残さずに投げ返す例外。使用法の誤りと、typer 自身の終了の合図で、どちらも
#: 「どこまで進んで止まったか」の話ではない。
_NOT_A_FAILURE = (typer.Exit, typer.Abort, typer.BadParameter)


@contextmanager
def _traced(log: Path | None, output: Path) -> Iterator[None]:
    """節目の記録と `FCEnvelopeError` の扱いをまとめる（ADR-0052）。

    `--log` が指定されていればそのファイルへ直に書く。指定がなければ記録はメモリに
    溜まるだけで、異常終了したときにだけ `_trace_path(output)` へ書き出す。正常に
    終わった実行はログのためのファイル IO を 1 回も行わない。
    """
    trace = logs.Trace(log)
    try:
        yield
    except FCEnvelopeError as exc:
        logger.error("%s", exc)
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        _echo_trace(trace.dump(_trace_path(output)))
        raise typer.Exit(1) from exc
    except (Exception, KeyboardInterrupt) as exc:
        # 想定外の異常終了と Ctrl-C。痕跡を残す値打ちがいちばんあるのはここで、
        # 止まった節目が最後の `begin` として残る。例外はそのまま投げ返す。
        if not isinstance(exc, _NOT_A_FAILURE):
            logger.error("%s: %s", type(exc).__name__, exc)
            _echo_trace(trace.dump(_trace_path(output)))
        raise
    finally:
        trace.close()


#: 上書きできない位置（ADR-0012, 0064）。`modes` は分子固有のデータで、コマンド
#: ラインで差し替えるとどの分子を計算したかが履歴に残らない。`schema_version` は
#: ファイルの版そのもので、実行のたびに変えるものではない。
UNOVERRIDABLE = ("modes", "schema_version")


def _parse_override(item: str) -> tuple[list[str], JsonValue]:
    """`KEY=VALUE` を、入力ファイル中の位置と値に分ける（ADR-0064）。

    値は JSON として読み、読めなければ文字列として扱う。`null` も `2.5` も `eV` も
    同じ規則で通る。ここで見るのは**書式そのもの**だけで、キーの存在と値の妥当性は
    入力ファイルの型が見る。使用法エラーで止まるのもここまでである。
    """
    key, separator, raw = item.partition("=")
    if not separator or not key:
        raise typer.BadParameter(
            f"expected KEY=VALUE, got {item!r}", param_hint="--override"
        )
    path = key.split(".")
    if "" in path:
        raise typer.BadParameter(
            f"empty field name in {key!r}", param_hint="--override"
        )
    if path[0] in UNOVERRIDABLE:
        raise typer.BadParameter(
            f"{path[0]} cannot be overridden", param_hint="--override"
        )
    try:
        value: JsonValue = json.loads(raw)
    except json.JSONDecodeError:
        value = raw
    return path, value


def _apply_override(data: JsonObject, item: str) -> None:
    """入力ファイルの形をした辞書に、上書きを 1 つ当てる。

    知らない名前のブロックはそのまま作る。入力ファイルの型が `extra="forbid"` なので、
    誤字は検証で未知のフィールドとして報告される（ADR-0064）。
    """
    path, value = _parse_override(item)
    block = data
    for depth, name in enumerate(path[:-1], start=1):
        nested = block.setdefault(name, {})
        if not isinstance(nested, dict):
            raise typer.BadParameter(
                f"{'.'.join(path[:depth])} is not a block",
                param_hint="--override",
            )
        block = nested
    block[path[-1]] = value


def _with_overrides(
    parsed: FCEnvelopeInput, overrides: Sequence[str]
) -> FCEnvelopeInput:
    """CLI の上書きを入力ファイルの型に適用し、同じ経路で検証し直す。

    上書きの値は入力ファイルと同じ単位・流儀で読む。正準化の前に差し替えるので、
    ファイルに書いてある値をそのまま CLI に移しても結果は変わらない（ADR-0050）。
    キーが入力ファイル中の位置そのものなので、どの単位で読まれるかはキーから分かる。
    """
    if not overrides:
        return parsed
    data = parsed.model_dump(mode="json")
    for item in overrides:
        _apply_override(data, item)
    return FCEnvelopeInput.from_obj(data)


def _report_envelope(result: EnvelopeResult, output: Path, *, top: int = 0) -> None:
    del top  # エンベロープには行ごとの表示がない。
    diagnostics = result.diagnostics
    typer.echo(
        f"wrote {output} "
        f"({result.energy.size} points, N={diagnostics.n_fft}, "
        f"area={diagnostics.total_area:.9g}, "
        f"captured={diagnostics.window_captured_fraction:.6g})"
    )
    _echo_warnings(diagnostics.messages)


def _echo_warnings(messages) -> None:
    for message in messages:
        typer.secho(f"warning: {message}", fg=typer.colors.YELLOW, err=True)


@app.command()
def run(
    input_path: Annotated[
        Path,
        typer.Argument(metavar="INPUT.json", help="Input JSON with modes (inline or a CSV reference) and the computation conditions."),
    ],
    output: Annotated[
        Optional[Path],
        typer.Option(
            "-o",
            "--output",
            help=(
                "Destination for the result JSON. Without it, INPUT_envelope.json "
                "next to the input file."
            ),
        ),
    ] = None,
    override: Overrides = None,
    script: ScriptFile = None,
    no_script: NoScript = False,
    force_script: ForceScript = False,
    config: ConfigFile = None,
    no_config: NoConfig = False,
    log: LogFile = None,
) -> None:
    """Compute the Franck-Condon envelope and write it to a result JSON.

    The settings this run actually uses are written before the computation starts,
    and a plot script is written next to the result; run it to draw the figure.
    """
    destination = _output_path(output, input_path, ENVELOPE_SUFFIX)
    with _traced(log, destination):
        parsed = _with_overrides(
            FCEnvelopeInput.from_path(input_path), override or ()
        )
        _emit_config(parsed, destination, config=config, no_config=no_config)
        result = compute_envelope(
            parsed.to_system(),
            temperature=parsed.to_temperature(),
            broadening=parsed.to_broadening(),
            grid=parsed.to_grid(),
        )
        save_any(result, destination)

        _report_any(result, destination)
        _emit_script(
            result, destination, script=script, no_script=no_script, force=force_script
        )


@app.command()
def lines(
    input_path: Annotated[
        Path,
        typer.Argument(
            metavar="INPUT.json",
            help="Input JSON with modes (inline or a CSV reference) and the computation conditions.",
        ),
    ],
    output: Annotated[
        Optional[Path],
        typer.Option(
            "-o",
            "--output",
            help=(
                "Destination for the FC line JSON. Without it, INPUT_lines.json "
                "next to the input file."
            ),
        ),
    ] = None,
    override: Overrides = None,
    top: Annotated[
        int, typer.Option("--top", help="Print this many of the strongest lines (0 disables).")
    ] = 10,
    script: ScriptFile = None,
    no_script: NoScript = False,
    force_script: ForceScript = False,
    config: ConfigFile = None,
    no_config: NoConfig = False,
    log: LogFile = None,
) -> None:
    """List the discrete Franck-Condon factors with their transition energies.

    The settings this run actually uses are written before the computation starts,
    and a plot script is written next to the result; run it to draw the figure.
    """
    destination = _output_path(output, input_path, LINES_SUFFIX)
    with _traced(log, destination):
        parsed = _with_overrides(
            FCEnvelopeInput.from_path(input_path), override or ()
        )
        _emit_config(parsed, destination, config=config, no_config=no_config)
        result = compute_fc_lines(
            parsed.to_system(),
            temperature=parsed.to_temperature(),
            selection=parsed.to_selection(),
        )
        save_any(result, destination)

        _report_any(result, destination, top=top)
        _emit_script(
            result, destination, script=script, no_script=no_script, force=force_script
        )


@app.command()
def script(
    result_paths: Annotated[
        list[Path],
        typer.Argument(
            metavar="RESULT.json...",
            help=(
                "Result JSON written by `fcenvelope run` or `fcenvelope lines`. "
                "Pass one of each to overlay the envelope and the stick spectrum."
            ),
        ),
    ],
    output: Annotated[
        Path,
        typer.Option("-o", "--output", help="Destination for the plot script (.py)."),
    ],
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing script."),
    ] = False,
    log: LogFile = None,
) -> None:
    """Write a plot script for stored results, then run it to draw the figure.

    One file draws either an envelope or a stick spectrum; the `kind` field decides.
    Two files -- one envelope result and one FC line list, in either order -- give a
    script that draws both on one axes (ADR-0030).

    Everything about how the figure looks lives in the script, so this is also the
    way to get a fresh one back after editing yours beyond repair.
    """
    with _traced(log, output):
        results = [load_any(result_path) for result_path in result_paths]

        if len(results) == 1:
            written = emit.write_script(
                results[0], result_paths[0], output, force=force
            )
        else:
            envelope, envelope_path, line_list, lines_path = _pair_for_overlay(
                results, result_paths
            )
            written = emit.write_overlay_script(
                envelope, envelope_path, line_list, lines_path, output, force=force
            )

        if written:
            typer.echo(f"wrote {output}")
        else:
            typer.echo(f"kept {output} (--force to regenerate)")


def _transition_label(line: FCLine) -> str:
    """`#0:0->1, #2:1->0` の形。すべて 0 なら ZPL。"""
    if not line.transitions:
        return "ZPL"
    return ", ".join(
        f"#{transition.mode_index}:{transition.initial}->{transition.final}"
        for transition in line.transitions
    )


def _report_lines(result: LinesResult, output: Path, *, top: int = 0) -> None:
    diagnostics = result.diagnostics
    typer.echo(
        f"wrote {output} "
        f"({diagnostics.n_lines} lines, "
        f"captured={diagnostics.captured_weight:.6g}, "
        f"<E>={diagnostics.mean_energy:.6g} cm^-1, "
        f"lambda={result.system.reorganization_energy:.6g} cm^-1)"
    )
    if top > 0 and result.lines:
        typer.echo(f"  {'E / cm^-1':>12}  {'FC':>12}  {'weight':>12}  transition")
    for line in result.lines[: max(top, 0)]:
        typer.echo(
            f"  {line.energy:12.4g}  {line.fc_factor:12.6g}  "
            f"{line.weight:12.6g}  {_transition_label(line)}"
        )
    if top > 0 and diagnostics.n_lines > top:
        typer.echo(f"  ... {diagnostics.n_lines - top} more (see {output})")
    _echo_warnings(diagnostics.messages)


#: 報告関数に共通の署名。`--top` を使うのは線だけだが、表に載せるために揃えてある。
Reporter = Callable[..., None]

#: 結果の型 -> 報告。種類を足すときはここに 1 行足す（ADR-0049）。
#: 保存・読み込みの表は `io.RESULT_KINDS`、描画の表は `plotting.DRAWERS`、作図
#: スクリプトの雛形の表は `emit.TEMPLATES` にある。
REPORTERS: dict[type, Reporter] = {
    EnvelopeResult: _report_envelope,
    LinesResult: _report_lines,
}


def _report_any(result: Result, output: Path, *, top: int = 0) -> None:
    """結果の種類を見て報告する。"""
    REPORTERS[type(result)](result, output, top=top)


#: 重ね描きが取る組み合わせ。表には載せず専用の関数のままにする（ADR-0049）。
OVERLAY_TYPES = (EnvelopeResult, LinesResult)

_R = TypeVar("_R", bound=Result)


def _of_type(
    results: Sequence[Result], result_type: type[_R], paths: Sequence[Path]
) -> list[tuple[_R, Path]]:
    """与えられた結果のうち、その型のものだけを読み込み元と組にして取り出す。"""
    return [
        (item, path)
        for item, path in zip(results, paths)
        if isinstance(item, result_type)
    ]


def _pair_for_overlay(
    results: list[Result], paths: list[Path]
) -> tuple[EnvelopeResult, Path, LinesResult, Path]:
    """重ね描き用に、エンベロープと線リストを 1 つずつ取り出す。与える順序は問わない。

    作図スクリプトは 2 つのファイルの位置を書き込むので、結果と一緒にその位置も返す。
    使用法エラーの種類名は `io` の表から引く。`kind` 文字列を直接書かない（ADR-0049）。
    """
    envelopes = _of_type(results, EnvelopeResult, paths)
    line_lists = _of_type(results, LinesResult, paths)

    if len(results) != 2 or len(envelopes) != 1 or len(line_lists) != 1:
        found = ", ".join(
            f"{path}: {kind_for(type(item))}" for path, item in zip(paths, results)
        )
        expected = " and one ".join(kind_for(t) for t in OVERLAY_TYPES)
        raise typer.BadParameter(
            f"overlaying takes exactly one {expected}, in either order (got {found})",
            param_hint="RESULT.json...",
        )
    return (*envelopes[0], *line_lists[0])


@app.callback(invoke_without_command=True)
def main(
    version: Annotated[
        bool,
        typer.Option("--version", help="Show the package version and exit.", is_eager=True),
    ] = False,
) -> None:
    if version:
        typer.echo(__version__)
        raise typer.Exit()
