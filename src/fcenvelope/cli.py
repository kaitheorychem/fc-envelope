"""typer による CLI。

終了コード: 0 正常 / 1 `FCEnvelopeError` / 2 typer の使用法エラー。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from .core import compute_envelope
from .errors import FCEnvelopeError
from .fcfactor import compute_fc_lines
from .io import load_any, save_fc_lines, save_result
from .models import Conditions, FCEnvelopeInput
from .result import FCEnvelopeResult, FCLine, FCLinesResult
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


def _report(result: FCEnvelopeResult, output: Path) -> None:
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
        save_result(result, output)
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
    min_intensity: Annotated[
        float,
        typer.Option("--min-intensity", help="Keep every line at or above this intensity."),
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
        int, typer.Option("--show", help="Print this many of the strongest lines (0 disables).")
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
            min_intensity=min_intensity,
            max_lines=max_lines,
            max_quanta=max_quanta,
        )
        save_fc_lines(result, output)
    except FCEnvelopeError as exc:
        raise _fail(exc) from exc

    _report_lines(result, output, show=show)

    if plot is not None:
        _save_figure(result, plot, title=None, dpi=dpi)


@app.command()
def plot(
    result_path: Annotated[
        Path,
        typer.Argument(
            metavar="RESULT.json",
            help="Result JSON written by `fcenvelope run` or `fcenvelope lines`.",
        ),
    ],
    output: Annotated[
        Path,
        typer.Option("-o", "--output", help="Destination image file."),
    ],
    title: Annotated[
        Optional[str], typer.Option("--title", help="Title drawn above the axes.")
    ] = None,
    dpi: Annotated[int, typer.Option("--dpi", help="Resolution of the output image.")] = 150,
) -> None:
    """Render a stored result without recomputing it.

    Accepts either an envelope result or an FC line list; the `kind` field decides.
    """
    try:
        result = load_any(result_path)
    except FCEnvelopeError as exc:
        raise _fail(exc) from exc

    _save_figure(result, output, title=title, dpi=dpi)


def _transition_label(line: FCLine) -> str:
    """`#0:0->1, #2:1->0` の形。すべて 0 なら ZPL。"""
    if not line.transitions:
        return "ZPL"
    return ", ".join(
        f"#{transition.mode_index}:{transition.initial}->{transition.final}"
        for transition in line.transitions
    )


def _report_lines(result: FCLinesResult, output: Path, *, show: int) -> None:
    diagnostics = result.diagnostics
    typer.echo(
        f"wrote {output} "
        f"({diagnostics.n_lines} lines, "
        f"captured={diagnostics.captured_intensity:.6g}, "
        f"<E>={diagnostics.mean_energy:.6g} cm^-1, "
        f"lambda={result.reorganization_energy:.6g} cm^-1)"
    )
    if show > 0 and result.lines:
        typer.echo(f"  {'E / cm^-1':>12}  {'FC':>12}  {'intensity':>12}  transition")
    for line in result.lines[: max(show, 0)]:
        typer.echo(
            f"  {line.energy:12.4g}  {line.fc_factor:12.6g}  "
            f"{line.intensity:12.6g}  {_transition_label(line)}"
        )
    if show > 0 and diagnostics.n_lines > show:
        typer.echo(f"  ... {diagnostics.n_lines - show} more (see {output})")
    for message in diagnostics.messages:
        typer.secho(f"warning: {message}", fg=typer.colors.YELLOW, err=True)


def _save_figure(
    result: FCEnvelopeResult | FCLinesResult, output: Path, *, title: str | None, dpi: int
) -> None:
    import matplotlib.pyplot as plt

    from .plotting import plot_fc_lines, plot_result

    if isinstance(result, FCLinesResult):
        figure = plot_fc_lines(result, title=title)
    else:
        figure = plot_result(result, title=title)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=dpi)
    plt.close(figure)
    typer.echo(f"wrote {output}")


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
