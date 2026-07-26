"""描画 API（合意文書 §9）。"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pytest
from conftest import compute_quietly

from fcenvelope import Conditions, VibrationalMode, plot_result

MODES = [VibrationalMode(frequency=1200.0, huang_rhys=0.5)]


@pytest.fixture
def result():
    conditions = Conditions(
        temperature=300.0, sigma=150.0, e_min=-8000.0, e_max=4000.0, de=5.0
    )
    return compute_quietly(MODES, conditions)


def test_returns_a_figure_and_draws_the_spectrum(result):
    figure = plot_result(result)
    try:
        (line,) = figure.axes[0].lines[:1]
        np.testing.assert_array_equal(line.get_xdata(), result.energy)
        np.testing.assert_array_equal(line.get_ydata(), result.intensity)
    finally:
        plt.close(figure)


def test_accepts_an_existing_axes_for_overlays(result):
    figure, ax = plt.subplots()
    try:
        first = plot_result(result, ax=ax, label="300 K")
        second = plot_result(result, ax=ax, label="0 K")
        assert first is figure and second is figure
        assert len([line for line in ax.lines if line.get_label() in {"300 K", "0 K"}]) == 2
        assert ax.get_legend() is not None
    finally:
        plt.close(figure)


def test_title_is_applied(result):
    figure = plot_result(result, title="demo")
    try:
        assert figure.axes[0].get_title() == "demo"
    finally:
        plt.close(figure)


def test_saving_is_left_to_the_caller(result, tmp_path):
    figure = plot_result(result)
    try:
        assert not list(tmp_path.iterdir())
        target = tmp_path / "figure.png"
        figure.savefig(target)
        assert target.is_file()
    finally:
        plt.close(figure)
