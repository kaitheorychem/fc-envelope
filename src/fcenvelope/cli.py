"""typer による CLI。

終了コード: 0 正常 / 1 `FCEnvelopeError` / 2 typer の使用法エラー。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from .core import compute_envelope
from .errors import FCEnvelopeError
from .io import load_result, save_result
from .models import Conditions, FCEnvelopeInput
from .result import FCEnvelopeResult
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
def plot(
    result_path: Annotated[
        Path,
        typer.Argument(metavar="RESULT.json", help="Result JSON written by `fcenvelope run`."),
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
    """Render a stored result without recomputing it."""
    try:
        result = load_result(result_path)
    except FCEnvelopeError as exc:
        raise _fail(exc) from exc

    _save_figure(result, output, title=title, dpi=dpi)


def _save_figure(result: FCEnvelopeResult, output: Path, *, title: str | None, dpi: int) -> None:
    import matplotlib.pyplot as plt

    from .plotting import plot_result

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
