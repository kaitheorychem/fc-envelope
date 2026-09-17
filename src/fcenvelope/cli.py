"""typer による CLI。

終了コード: 0 正常 / 1 `FCEnvelopeError` / 2 typer の使用法エラー。

節目のログは `--log` で指定したファイルに書く。指定がなければメモリに溜めるだけで、
異常終了したときにだけ出力先の隣へ書き出す（ADR-0052）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING, Annotated, Optional, TypeVar

import typer

if TYPE_CHECKING:  # pragma: no cover - 型注釈のためだけの import
    import matplotlib.figure

from . import logs
from .envelope import compute_envelope
from .errors import FCEnvelopeError
from .inputs import FCEnvelopeInput
from .io import kind_for, load_any, save_any
from .lines import compute_fc_lines
from .logs import stage
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


#: CLI が上書きできる値。入力ファイルと同じ単位・流儀で読む生の値で、正準化の前に
#: 差し替える（ADR-0050）。`None` は「上書きしない」を意味する。
Override = float | int | None


def _override(
    parsed: FCEnvelopeInput,
    *,
    temperature: float | None = None,
    **blocks: dict[str, Override],
) -> FCEnvelopeInput:
    """CLI の上書きを入力ファイルの型に適用し、同じ経路で検証し直す。

    上書きの値は入力ファイルと同じ単位・流儀で読む。正準化の前に差し替えるので、
    ファイルに書いてある値をそのまま CLI に移しても結果は変わらない（ADR-0050）。
    指定のないオプションは `None`、すなわち「上書きしない」を意味する。
    """
    data = parsed.model_dump(mode="json")
    if temperature is not None:
        data["temperature"] = temperature
    for name, values in blocks.items():
        given = {key: value for key, value in values.items() if value is not None}
        if given:
            data[name] = {**data[name], **given}
    return FCEnvelopeInput.from_obj(data)


def _report_envelope(result: EnvelopeResult, output: Path, *, show: int = 0) -> None:
    del show  # エンベロープには行ごとの表示がない。
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
        Path,
        typer.Option("-o", "--output", help="Destination for the result JSON."),
    ],
    plot: Annotated[
        Optional[Path],
        typer.Option("--plot", help="Also render the envelope to this image file."),
    ] = None,
    temperature: Annotated[
        Optional[float],
        typer.Option("--temperature", help="Override temperature [K]."),
    ] = None,
    sigma: Annotated[
        Optional[float],
        typer.Option("--sigma", help="Override broadening.sigma, in the input file's broadening unit."),
    ] = None,
    e_min: Annotated[
        Optional[float],
        typer.Option("--e-min", help="Override grid.e_min, in the input file's grid unit."),
    ] = None,
    e_max: Annotated[
        Optional[float],
        typer.Option("--e-max", help="Override grid.e_max, in the input file's grid unit."),
    ] = None,
    de: Annotated[
        Optional[float],
        typer.Option("--de", help="Override grid.de, in the input file's grid unit."),
    ] = None,
    dpi: Annotated[int, typer.Option("--dpi", help="Resolution of --plot.")] = 150,
    log: LogFile = None,
) -> None:
    """Compute the Franck-Condon envelope and write it to a result JSON."""
    with _traced(log, output):
        parsed = _override(
            FCEnvelopeInput.from_path(input_path),
            temperature=temperature,
            broadening={"sigma": sigma},
            grid={"e_min": e_min, "e_max": e_max, "de": de},
        )
        result = compute_envelope(
            parsed.to_system(),
            temperature=parsed.to_temperature(),
            broadening=parsed.to_broadening(),
            grid=parsed.to_grid(),
        )
        save_any(result, output)

        _report_any(result, output)

        if plot is not None:
            _save_figure(result, plot, title=None, dpi=dpi)


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
        Path,
        typer.Option("-o", "--output", help="Destination for the FC line JSON."),
    ],
    plot: Annotated[
        Optional[Path],
        typer.Option("--plot", help="Also render the stick spectrum to this image file."),
    ] = None,
    temperature: Annotated[
        Optional[float],
        typer.Option("--temperature", help="Override temperature [K]."),
    ] = None,
    min_weight: Annotated[
        Optional[float],
        typer.Option("--min-weight", help="Override selection.min_weight."),
    ] = None,
    max_lines: Annotated[
        Optional[int],
        typer.Option("--max-lines", help="Override selection.max_lines."),
    ] = None,
    max_quanta: Annotated[
        Optional[int],
        typer.Option("--max-quanta", help="Override selection.max_quanta."),
    ] = None,
    show: Annotated[
        int, typer.Option("--show", help="Print this many of the strongest lines (0 disables).")
    ] = 10,
    dpi: Annotated[int, typer.Option("--dpi", help="Resolution of --plot.")] = 150,
    log: LogFile = None,
) -> None:
    """List the discrete Franck-Condon factors with their transition energies."""
    with _traced(log, output):
        parsed = _override(
            FCEnvelopeInput.from_path(input_path),
            temperature=temperature,
            selection={
                "min_weight": min_weight,
                "max_lines": max_lines,
                "max_quanta": max_quanta,
            },
        )
        result = compute_fc_lines(
            parsed.to_system(),
            temperature=parsed.to_temperature(),
            selection=parsed.to_selection(),
        )
        save_any(result, output)

        _report_any(result, output, show=show)

        if plot is not None:
            _save_figure(result, plot, title=None, dpi=dpi)


@app.command()
def plot(
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
        typer.Option("-o", "--output", help="Destination image file."),
    ],
    title: Annotated[
        Optional[str], typer.Option("--title", help="Title drawn above the axes.")
    ] = None,
    magnify: Annotated[
        float,
        typer.Option(
            "--magnify",
            help="Blow up the sticks by this factor when overlaying (shown in the legend).",
        ),
    ] = 1.0,
    dpi: Annotated[int, typer.Option("--dpi", help="Resolution of the output image.")] = 150,
    log: LogFile = None,
) -> None:
    """Render stored results without recomputing them.

    One file draws either an envelope or a stick spectrum; the `kind` field decides.
    Two files -- one envelope result and one FC line list, in either order -- are
    drawn on one axes, with the lines scaled into the unit of F(E).
    """
    with _traced(log, output):
        results = [load_any(result_path) for result_path in result_paths]

        if len(results) == 1:
            if magnify != 1.0:
                raise typer.BadParameter(
                    "--magnify only applies when overlaying two results",
                    param_hint="--magnify",
                )
            _save_figure(results[0], output, title=title, dpi=dpi)
            return

        envelope, line_list = _pair_for_overlay(results, result_paths)
        _save_overlay(
            envelope, line_list, output, title=title, magnify=magnify, dpi=dpi
        )


def _transition_label(line: FCLine) -> str:
    """`#0:0->1, #2:1->0` の形。すべて 0 なら ZPL。"""
    if not line.transitions:
        return "ZPL"
    return ", ".join(
        f"#{transition.mode_index}:{transition.initial}->{transition.final}"
        for transition in line.transitions
    )


def _report_lines(result: LinesResult, output: Path, *, show: int = 0) -> None:
    diagnostics = result.diagnostics
    typer.echo(
        f"wrote {output} "
        f"({diagnostics.n_lines} lines, "
        f"captured={diagnostics.captured_weight:.6g}, "
        f"<E>={diagnostics.mean_energy:.6g} cm^-1, "
        f"lambda={result.system.reorganization_energy:.6g} cm^-1)"
    )
    if show > 0 and result.lines:
        typer.echo(f"  {'E / cm^-1':>12}  {'FC':>12}  {'weight':>12}  transition")
    for line in result.lines[: max(show, 0)]:
        typer.echo(
            f"  {line.energy:12.4g}  {line.fc_factor:12.6g}  "
            f"{line.weight:12.6g}  {_transition_label(line)}"
        )
    if show > 0 and diagnostics.n_lines > show:
        typer.echo(f"  ... {diagnostics.n_lines - show} more (see {output})")
    _echo_warnings(diagnostics.messages)


#: 報告関数に共通の署名。`--show` を使うのは線だけだが、表に載せるために揃えてある。
Reporter = Callable[..., None]

#: 結果の型 -> 報告。種類を足すときはここに 1 行足す（ADR-0049）。
#: 保存・読み込みの表は `io.RESULT_KINDS`、描画の表は `plotting.DRAWERS` にある。
REPORTERS: dict[type, Reporter] = {
    EnvelopeResult: _report_envelope,
    LinesResult: _report_lines,
}


def _report_any(result: Result, output: Path, *, show: int = 0) -> None:
    """結果の種類を見て報告する。"""
    REPORTERS[type(result)](result, output, show=show)


#: 重ね描きが取る組み合わせ。表には載せず専用の関数のままにする（ADR-0049）。
OVERLAY_TYPES = (EnvelopeResult, LinesResult)

_R = TypeVar("_R", bound=Result)


def _of_type(results: Sequence[Result], result_type: type[_R]) -> list[_R]:
    """与えられた結果のうち、その型のものだけを取り出す。"""
    return [item for item in results if isinstance(item, result_type)]


def _pair_for_overlay(
    results: list[Result], paths: list[Path]
) -> tuple[EnvelopeResult, LinesResult]:
    """重ね描き用に、エンベロープと線リストを 1 つずつ取り出す。与える順序は問わない。

    使用法エラーの種類名は `io` の表から引く。`kind` 文字列を直接書かない（ADR-0049）。
    """
    envelopes = _of_type(results, EnvelopeResult)
    line_lists = _of_type(results, LinesResult)

    if len(results) != 2 or len(envelopes) != 1 or len(line_lists) != 1:
        found = ", ".join(
            f"{path}: {kind_for(type(item))}" for path, item in zip(paths, results)
        )
        expected = " and one ".join(kind_for(t) for t in OVERLAY_TYPES)
        raise typer.BadParameter(
            f"overlaying takes exactly one {expected}, in either order (got {found})",
            param_hint="RESULT.json...",
        )
    return envelopes[0], line_lists[0]


def _write_figure(
    figure: "matplotlib.figure.Figure", output: Path, *, dpi: int
) -> None:
    """`Figure` を画像として書き出し、後始末まで済ませる。"""
    import matplotlib.pyplot as plt

    output.parent.mkdir(parents=True, exist_ok=True)
    with stage(logger, f"write {output}"):
        figure.savefig(output, dpi=dpi)
    plt.close(figure)
    typer.echo(f"wrote {output}")


def _save_figure(
    result: Result, output: Path, *, title: str | None, dpi: int
) -> None:
    from .plotting import plot_any

    _write_figure(plot_any(result, title=title), output, dpi=dpi)


def _save_overlay(
    envelope: EnvelopeResult,
    lines: LinesResult,
    output: Path,
    *,
    title: str | None,
    magnify: float,
    dpi: int,
) -> None:
    from .plotting import plot_overlay

    figure = plot_overlay(envelope, lines, magnify=magnify, title=title)
    _write_figure(figure, output, dpi=dpi)

    low = float(envelope.energy[0])
    high = float(envelope.energy[-1])
    dropped = sum(1 for line in lines.lines if not low <= line.energy <= high)
    if dropped:
        # 利用者への警告と、記録としてのログの両方に出す（ADR-0052）。
        message = (
            f"{dropped} of {len(lines.lines)} lines fall outside the "
            f"E window [{low:g}, {high:g}] cm^-1 and are not drawn"
        )
        typer.secho(f"warning: {message}", fg=typer.colors.YELLOW, err=True)
        logger.warning("%s", message)


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
