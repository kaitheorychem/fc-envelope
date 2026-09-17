"""結果の種類による振り分けの表（ADR-0049）。

分岐は関心ごとの表に分かれているので、**すべての表が同じ種類を網羅していること**を
ここで確かめる。種類を足すときは各表に 1 行ずつ足す。
"""

from __future__ import annotations

import pytest
from conftest import compute_quietly, lines_quietly

from fcenvelope import Broadening, EnergyGrid, EnvelopeResult, LinesResult
from fcenvelope.cli import OVERLAY_TYPES, REPORTERS
from fcenvelope.errors import InvalidInputError
from fcenvelope.io import RESULT_KINDS, kind_for, kind_of, load_any, save_any
from fcenvelope.plotting import DRAWERS, plot_any

TABLES = {
    "io.RESULT_KINDS": lambda: {spec.result_type for spec in RESULT_KINDS.values()},
    "plotting.DRAWERS": lambda: set(DRAWERS),
    "cli.REPORTERS": lambda: set(REPORTERS),
}


def test_every_table_covers_the_same_result_types():
    covered = {name: types() for name, types in TABLES.items()}
    expected = {EnvelopeResult, LinesResult}
    for name, types in covered.items():
        assert types == expected, f"{name} covers {types}, expected {expected}"


def test_kinds_and_result_types_are_a_bijection():
    assert len({spec.kind for spec in RESULT_KINDS.values()}) == len(RESULT_KINDS)
    assert {kind_for(spec.result_type) for spec in RESULT_KINDS.values()} == set(
        RESULT_KINDS
    )


def test_an_unknown_result_type_is_reported_by_every_table():
    with pytest.raises(InvalidInputError):
        kind_for(str)
    with pytest.raises(InvalidInputError):
        plot_any("not a result")


def test_overlay_is_not_in_the_tables_but_names_its_kinds_from_them():
    """重ね描きは種類ごとの処理ではないので表に載せない（ADR-0049）。"""
    assert set(OVERLAY_TYPES) == {EnvelopeResult, LinesResult}
    assert [kind_for(t) for t in OVERLAY_TYPES] == [
        "fcenvelope.envelope",
        "fcenvelope.fc_lines",
    ]


@pytest.fixture
def results(multi_mode):
    envelope = compute_quietly(
        multi_mode,
        temperature=300.0,
        broadening=Broadening(sigma=150.0),
        grid=EnergyGrid(e_min=-6000.0, e_max=2000.0, de=5.0),
    )
    return [envelope, lines_quietly(multi_mode, temperature=300.0, min_weight=1e-3)]


def test_save_any_and_load_any_round_trip_every_kind(results, tmp_path):
    for index, result in enumerate(results):
        path = tmp_path / f"result{index}.json"
        save_any(result, path)
        restored = load_any(path)
        assert type(restored) is type(result)
        assert kind_of(restored) == kind_of(result)


def test_plot_any_draws_every_kind(results):
    import matplotlib.pyplot as plt

    for result in results:
        figure = plot_any(result, title="demo")
        try:
            assert figure.axes[0].get_title() == "demo"
        finally:
            plt.close(figure)


def test_report_any_handles_every_kind(results, tmp_path, capsys):
    from fcenvelope.cli import _report_any

    for result in results:
        _report_any(result, tmp_path / "out.json", show=2)
    assert capsys.readouterr().out.count("wrote") == len(results)


def test_load_any_rejects_an_unknown_kind(results, tmp_path):
    import json

    path = tmp_path / "result.json"
    save_any(results[0], path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["kind"] = "fcenvelope.something"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(InvalidInputError, match="known kinds"):
        load_any(path)
