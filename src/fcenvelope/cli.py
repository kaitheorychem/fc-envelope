"""typer による CLI。

終了コード: 0 正常 / 1 `FCEnvelopeError` / 2 typer の使用法エラー。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Optional

import typer

if TYPE_CHECKING:  # pragma: no cover - 型注釈のためだけの import
    import matplotlib.figure

from .envelope import compute_envelope
from .errors import FCEnvelopeError
from .io import ENVELOPE_KIND, LINES_KIND, load_any, save_envelope, save_lines
from .lines import compute_fc_lines
from .models import Conditions, FCEnvelopeInput
from .result import EnvelopeResult, FCLine, LinesResult
from .version import __version__

__all__ = ["app"]

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Franck-Condon envelope F(E) from vibronic couplings, frequencies and temperature.",
)


def _fail(exc: FCEnvelopeError) -> typer.Exit:
    typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
    return typer.Exit(1)


def _override_conditions(
    conditions: Conditions,
    *,
    temperature: float | None,
    sigma: float | None,
    e_min: float | None,
    e_max: float | None,
    de: float | None,
) -> Conditions:
    """CLI オプションで指定されたフィールドのみ差し替えて再検証する。"""
    overrides = {
        "temperature": temperature,
        "sigma": sigma,
        "e_min": e_min,
        "e_max": e_max,
        "de": de,
    }
    merged = conditions.model_dump()
    merged.update({key: value for key, value in overrides.items() if value is not None})
    return Conditions.from_obj(merged)


def _report(result: EnvelopeResult, output: Path) -> None:
    diagnostics = result.diagnostics
    typer.echo(
        f"wrote {output} "
        f"({result.energy.size} points, N={diagnostics.n_fft}, "
        f"area={diagnostics.total_area:.9g}, "
        f"captured={diagnostics.window_captured_fraction:.6g})"
    )
    for message in diagnostics.messages:
        typer.secho(f"warning: {message}", fg=typer.colors.YELLOW, err=True)


@app.command()
def run(
    input_path: Annotated[
        Path,
        typer.Argument(metavar="INPUT.json", help="Input JSON with modes (inline or a CSV reference) and conditions."),
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
        typer.Option("--temperature", help="Override conditions.temperature [K]."),
    ] = None,
    sigma: Annotated[
        Optional[float],
        typer.Option("--sigma", help="Override conditions.sigma [cm^-1]."),
    ] = None,
    e_min: Annotated[
        Optional[float],
        typer.Option("--e-min", help="Override conditions.e_min [cm^-1]."),
    ] = None,
    e_max: Annotated[
        Optional[float],
        typer.Option("--e-max", help="Override conditions.e_max [cm^-1]."),
    ] = None,
    de: Annotated[
        Optional[float],
        typer.Option("--de", help="Override conditions.de [cm^-1]."),
    ] = None,
    dpi: Annotated[int, typer.Option("--dpi", help="Resolution of --plot.")] = 150,
) -> None:
    """Compute the Franck-Condon envelope and write it to a result JSON."""
    try:
        parsed = FCEnvelopeInput.from_path(input_path)
        conditions = _override_conditions(
            parsed.conditions,
            temperature=temperature,
            sigma=sigma,
            e_min=e_min,
            e_max=e_max,
            de=de,
        )
        result = compute_envelope(parsed.to_modes(), conditions)
        save_envelope(result, output)
    except FCEnvelopeError as exc:
        raise _fail(exc) from exc

    _report(result, output)

    if plot is not None:
        _save_figure(result, plot, title=None, dpi=dpi)


@app.command()
def lines(
    input_path: Annotated[
        Path,
        typer.Argument(
            metavar="INPUT.json",
            help="Input JSON with modes (inline or a CSV reference) and conditions.",
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
        typer.Option("--temperature", help="Override conditions.temperature [K]."),
    ] = None,
    min_weight: Annotated[
        float,
        typer.Option("--min-weight", help="Keep every line at or above this weight."),
    ] = 1e-4,
    max_lines: Annotated[
        int, typer.Option("--max-lines", help="Upper bound on the number of lines kept.")
    ] = 10000,
    max_quanta: Annotated[
        Optional[int],
        typer.Option(
            "--max-quanta", help="Cap on vibrational quanta per mode (default: automatic)."
        ),
    ] = None,
    show: Annotated[
        int, typer.Option("--show", help="Print this many of the heaviest lines (0 disables).")
    ] = 10,
    dpi: Annotated[int, typer.Option("--dpi", help="Resolution of --plot.")] = 150,
) -> None:
    """List the discrete Franck-Condon factors with their transition energies."""
    try:
        parsed = FCEnvelopeInput.from_path(input_path)
        result = compute_fc_lines(
            parsed.to_modes(),
            temperature=(
                parsed.conditions.temperature if temperature is None else temperature
            ),
            min_weight=min_weight,
            max_lines=max_lines,
            max_quanta=max_quanta,
        )
        save_lines(result, output)
    except FCEnvelopeError as exc:
        raise _fail(exc) from exc

    _report_lines(result, output, show=show)

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
) -> None:
    """Render stored results without recomputing them.

    One file draws either an envelope or a stick spectrum; the `kind` field decides.
    Two files -- one envelope result and one FC line list, in either order -- are
    drawn on one axes, with the lines scaled into the unit of F(E).
    """
    try:
        results = [load_any(result_path) for result_path in result_paths]
    except FCEnvelopeError as exc:
        raise _fail(exc) from exc

    if len(results) == 1:
        if magnify != 1.0:
            raise typer.BadParameter(
                "--magnify only applies when overlaying two results",
                param_hint="--magnify",
            )
        _save_figure(results[0], output, title=title, dpi=dpi)
        return

    envelope, line_list = _pair_for_overlay(results, result_paths)
    try:
        _save_overlay(envelope, line_list, output, title=title, magnify=magnify, dpi=dpi)
    except FCEnvelopeError as exc:
        raise _fail(exc) from exc


def _transition_label(line: FCLine) -> str:
    """`#0:0->1, #2:1->0` の形。すべて 0 なら ZPL。"""
    if not line.transitions:
        return "ZPL"
    return ", ".join(
        f"#{transition.mode_index}:{transition.initial}->{transition.final}"
        for transition in line.transitions
    )


def _report_lines(result: LinesResult, output: Path, *, show: int) -> None:
    diagnostics = result.diagnostics
    typer.echo(
        f"wrote {output} "
        f"({diagnostics.n_lines} lines, "
        f"captured={diagnostics.captured_weight:.6g}, "
        f"<E>={diagnostics.mean_energy:.6g} cm^-1, "
        f"lambda={result.reorganization_energy:.6g} cm^-1)"
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
    for message in diagnostics.messages:
        typer.secho(f"warning: {message}", fg=typer.colors.YELLOW, err=True)


def _pair_for_overlay(
    results: list[EnvelopeResult | LinesResult], paths: list[Path]
) -> tuple[EnvelopeResult, LinesResult]:
    """重ね描き用に、エンベロープと線リストを 1 つずつ取り出す。与える順序は問わない。"""
    envelopes = [item for item in results if isinstance(item, EnvelopeResult)]
    line_lists = [item for item in results if isinstance(item, LinesResult)]
    if len(results) > 2 or len(envelopes) != 1 or len(line_lists) != 1:
        found = ", ".join(
            f"{path}: {LINES_KIND if isinstance(item, LinesResult) else ENVELOPE_KIND}"
            for path, item in zip(paths, results)
        )
        raise typer.BadParameter(
            f"overlaying takes exactly one {ENVELOPE_KIND} and one {LINES_KIND}, "
            f"in either order (got {found})",
            param_hint="RESULT.json...",
        )
    return envelopes[0], line_lists[0]


def _write_figure(
    figure: "matplotlib.figure.Figure", output: Path, *, dpi: int
) -> None:
    """`Figure` を画像として書き出し、後始末まで済ませる。"""
    import matplotlib.pyplot as plt

    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=dpi)
    plt.close(figure)
    typer.echo(f"wrote {output}")


def _save_figure(
    result: EnvelopeResult | LinesResult, output: Path, *, title: str | None, dpi: int
) -> None:
    from .plotting import plot_envelope, plot_lines

    if isinstance(result, LinesResult):
        figure = plot_lines(result, title=title)
    else:
        figure = plot_envelope(result, title=title)
    _write_figure(figure, output, dpi=dpi)


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
        typer.secho(
            f"warning: {dropped} of {len(lines.lines)} lines fall outside the "
            f"E window [{low:g}, {high:g}] cm^-1 and are not drawn",
            fg=typer.colors.YELLOW,
            err=True,
        )


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
