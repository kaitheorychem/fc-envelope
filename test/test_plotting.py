"""描画 API（合意文書 §9）。"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pytest
from conftest import compute_quietly, lines_quietly

from fcenvelope import Conditions, VibrationalMode, plot_fc_lines, plot_result

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


# --- 離散 FC 因子の棒スペクトル ---


@pytest.fixture
def lines_result():
    return lines_quietly(MODES, temperature=300.0, min_intensity=1e-4)


def test_fc_lines_draws_one_stick_per_line(lines_result):
    figure = plot_fc_lines(lines_result)
    try:
        (collection,) = figure.axes[0].collections
        segments = collection.get_segments()
        assert len(segments) == lines_result.diagnostics.n_lines
        # エネルギーが縮退した線もまとめずに 1 本ずつ描く。
        drawn = sorted((segment[0][0], segment[1][1]) for segment in segments)
        expected = sorted(
            (line.energy, line.intensity) for line in lines_result.lines
        )
        np.testing.assert_allclose(drawn, expected)
        assert all(segment[0][1] == 0.0 for segment in segments)
    finally:
        plt.close(figure)


def test_fc_lines_accepts_an_existing_axes(lines_result):
    figure, ax = plt.subplots()
    try:
        assert plot_fc_lines(lines_result, ax=ax, label="300 K") is figure
        assert ax.get_legend() is not None
    finally:
        plt.close(figure)


def test_fc_lines_title_is_applied(lines_result):
    figure = plot_fc_lines(lines_result, title="sticks")
    try:
        assert figure.axes[0].get_title() == "sticks"
    finally:
        plt.close(figure)
