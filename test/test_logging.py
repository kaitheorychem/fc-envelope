"""節目のログ（ADR-0052）。

ログは痕跡を残すためだけのものなので、確かめるのは 2 点である。**どこまで進んだかが
読めること**と、**それ以上は出さないこと**——とりわけ、記録の数が系の大きさや線の本数で
増えないこと（ループの内側で記録を取っていないこと）である。
"""

from __future__ import annotations

import json
import logging
import warnings

import pytest
from conftest import compute_quietly, lines_quietly
from typer.testing import CliRunner

from fcenvelope import Broadening, EnergyGrid, plot_overlay, save_envelope
from fcenvelope.cli import app
from fcenvelope.logs import LOGGER_NAME, Trace, stage

runner = CliRunner()


@pytest.fixture
def stages(caplog):
    """`fcenvelope` の INFO 記録（= 節目）だけを順に取り出す。"""
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    def collected() -> list[str]:
        return [
            record.getMessage()
            for record in caplog.records
            if record.name.startswith(LOGGER_NAME) and record.levelno == logging.INFO
        ]

    return collected


@pytest.fixture
def alerts(caplog):
    """`fcenvelope` の WARNING 記録だけを取り出す。"""
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    def collected() -> list[str]:
        return [
            record.getMessage()
            for record in caplog.records
            if record.name.startswith(LOGGER_NAME) and record.levelno == logging.WARNING
        ]

    return collected


@pytest.fixture
def input_file(tmp_path, input_payload):
    path = tmp_path / "input.json"
    path.write_text(json.dumps(input_payload), encoding="utf-8")
    return path


# --- 何が残るか ---


def test_each_stage_leaves_a_begin_and_an_end(stages, single_mode, tmp_path):
    compute_quietly(
        single_mode,
        temperature=300.0,
        broadening=Broadening(sigma=150.0),
        grid=EnergyGrid(e_min=-4000.0, e_max=1000.0, de=5.0),
    )
    result_path = tmp_path / "result.json"
    save_envelope(
        compute_quietly(
            single_mode,
            temperature=0.0,
            broadening=Broadening(sigma=150.0),
            grid=EnergyGrid(e_min=-4000.0, e_max=1000.0, de=5.0),
        ),
        result_path,
    )

    recorded = stages()
    assert sum(message.startswith("begin envelope") for message in recorded) == 2
    assert sum(message.startswith("end envelope") for message in recorded) == 2
    assert f"begin write {result_path}" in recorded
    assert any(message.startswith(f"end write {result_path}") for message in recorded)


def test_the_end_line_carries_the_elapsed_time(stages, single_mode):
    compute_quietly(
        single_mode,
        temperature=300.0,
        broadening=Broadening(sigma=150.0),
        grid=EnergyGrid(e_min=-4000.0, e_max=1000.0, de=5.0),
    )
    ends = [message for message in stages() if message.startswith("end ")]
    assert ends and all(message.endswith(" s)") for message in ends)


def test_a_stage_that_raises_leaves_no_end_line(stages):
    """開始行だけがあって完了行がない、という形が「ここで止まった」を意味する。"""
    logger = logging.getLogger(f"{LOGGER_NAME}.test")
    with pytest.raises(ZeroDivisionError):
        with stage(logger, "heavy thing"):
            1 / 0

    assert stages() == ["begin heavy thing"]


# --- 警告は利用者への発報とログの両方に出る ---


def test_quality_warnings_are_recorded(alerts, single_mode):
    """`warnings` を潰していても痕跡は残る。宛先が違うだけで同じ出来事である。"""
    result = compute_quietly(
        single_mode,
        temperature=300.0,
        broadening=Broadening(sigma=150.0),
        grid=EnergyGrid(e_min=-500.0, e_max=500.0, de=5.0),
    )
    assert result.diagnostics.messages  # 閾値に引っかかる条件を選んでいる
    assert alerts() == list(result.diagnostics.messages)


def test_an_overlay_mismatch_is_recorded(alerts, single_mode):
    import matplotlib.pyplot as plt

    envelope = compute_quietly(
        single_mode,
        temperature=300.0,
        broadening=Broadening(sigma=150.0),
        grid=EnergyGrid(e_min=-4000.0, e_max=1000.0, de=5.0),
    )
    lines = lines_quietly(single_mode, temperature=0.0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        plt.close(plot_overlay(envelope, lines))

    assert any("temperature mismatch" in message for message in alerts())


def test_lines_dropped_from_an_overlay_are_recorded(tmp_path, input_file):
    """CLI だけが出す警告も、利用者への 1 行とログの 1 行の両方になる。"""
    result_json = tmp_path / "result.json"
    lines_json = tmp_path / "lines.json"
    log = tmp_path / "overlay.log"
    narrow = ["--e-min", "-600", "--e-max", "300"]
    assert runner.invoke(
        app, ["run", str(input_file), "-o", str(result_json), *narrow]
    ).exit_code == 0
    assert runner.invoke(
        app, ["lines", str(input_file), "-o", str(lines_json), "--show", "0"]
    ).exit_code == 0

    invocation = runner.invoke(
        app,
        ["plot", str(result_json), str(lines_json), "-o", str(tmp_path / "overlay.png"),
         "--log", str(log)],
    )

    assert invocation.exit_code == 0, invocation.output
    assert "fall outside" in invocation.output
    assert "fall outside" in log.read_text(encoding="utf-8")


# --- どれだけ出さないか ---


def test_the_number_of_stages_does_not_grow_with_the_system(stages, caplog, multi_mode, single_mode):
    """モードの数で記録が増えないこと。増えるならループの内側で記録している。"""
    conditions = {
        "temperature": 300.0,
        "broadening": Broadening(sigma=150.0),
        "grid": EnergyGrid(e_min=-6000.0, e_max=2000.0, de=5.0),
    }
    compute_quietly(single_mode, **conditions)
    one_mode = len(stages())
    caplog.clear()
    compute_quietly(multi_mode, **conditions)

    assert len(stages()) == one_mode


def test_the_number_of_stages_does_not_grow_with_the_lines(stages, caplog, multi_mode):
    """線の本数で記録が増えないこと。列挙のループも記録を取らない。"""
    coarse = lines_quietly(multi_mode, temperature=300.0, min_weight=1e-2)
    few = len(stages())
    caplog.clear()
    fine = lines_quietly(multi_mode, temperature=300.0, min_weight=1e-6)

    assert fine.diagnostics.n_lines > 10 * coarse.diagnostics.n_lines
    assert len(stages()) == few


def test_the_library_is_silent_until_a_handler_is_attached(capsys, single_mode):
    """ハンドラを付けていない利用者には何も出さない（`NullHandler` の役目）。"""
    compute_quietly(
        single_mode,
        temperature=300.0,
        broadening=Broadening(sigma=150.0),
        grid=EnergyGrid(e_min=-4000.0, e_max=1000.0, de=5.0),
    )
    assert capsys.readouterr() == ("", "")


def test_a_trace_leaves_the_logger_as_it_found_it(tmp_path):
    logger = logging.getLogger(LOGGER_NAME)
    before = (list(logger.handlers), logger.level)

    trace = Trace(tmp_path / "run.log")
    try:
        assert len(logger.handlers) == len(before[0]) + 1
    finally:
        trace.close()

    assert (logger.handlers, logger.level) == before


# --- CLI ---


def test_log_option_writes_the_stages(tmp_path, input_file):
    log = tmp_path / "run.log"
    invocation = runner.invoke(
        app,
        [
            "run", str(input_file), "-o", str(tmp_path / "result.json"),
            "--plot", str(tmp_path / "spectrum.png"), "--log", str(log),
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    written = log.read_text(encoding="utf-8")
    # 読み込み・計算・保存・作図が、この順に始まって終わっている。
    assert written.count("begin ") == written.count("end ") == 5
    for label in ("read", "envelope:", "write", "plot envelope"):
        assert f"begin {label}" in written


def test_a_successful_run_writes_no_log_file(tmp_path, input_file):
    """ログを頼まれていない正常終了は、ログのためのファイル IO を 1 回も行わない。"""
    output = tmp_path / "result.json"
    invocation = runner.invoke(app, ["run", str(input_file), "-o", str(output)])

    assert invocation.exit_code == 0, invocation.output
    assert list(tmp_path.glob("*.log")) == []


def test_a_failing_run_leaves_the_trace_next_to_the_output(tmp_path, input_file):
    output = tmp_path / "result.json"
    invocation = runner.invoke(
        app, ["run", str(input_file), "-o", str(output), "--e-min", "5000"]
    )

    assert invocation.exit_code == 1
    trace = output.with_suffix(".log")
    assert str(trace) in invocation.output
    written = trace.read_text(encoding="utf-8")
    assert "ERROR" in written
    assert "e_min must be smaller than e_max" in written
    # 読み込みまでは終わっていた、というところまで読める。
    assert f"end read {input_file}" in written


def test_an_explicit_log_file_is_not_duplicated_on_failure(tmp_path, input_file):
    output = tmp_path / "result.json"
    log = tmp_path / "run.log"
    invocation = runner.invoke(
        app,
        ["run", str(input_file), "-o", str(output), "--e-min", "5000", "--log", str(log)],
    )

    assert invocation.exit_code == 1
    assert not output.with_suffix(".log").exists()
    assert "ERROR" in log.read_text(encoding="utf-8")


def test_an_unwritable_trace_does_not_hide_the_error(tmp_path, input_file):
    """痕跡を残せないこと自体は、元のエラーを押しのけて報告するほどのことではない。"""
    output = tmp_path / "absent" / "result.json"
    (tmp_path / "absent").write_text("not a directory", encoding="utf-8")

    invocation = runner.invoke(
        app, ["run", str(input_file), "-o", str(output), "--e-min", "5000"]
    )

    assert invocation.exit_code == 1
    assert "e_min must be smaller than e_max" in invocation.output
    assert "wrote the log" not in invocation.output


def test_an_unexpected_failure_leaves_the_trace_too(tmp_path, input_file, monkeypatch):
    """バグや Ctrl-C で落ちたときこそ、どの節目で止まったかが残っていてほしい。"""
    def explode(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("fcenvelope.cli.compute_envelope", explode)
    output = tmp_path / "result.json"

    invocation = runner.invoke(app, ["run", str(input_file), "-o", str(output)])

    assert invocation.exit_code != 0
    written = output.with_suffix(".log").read_text(encoding="utf-8")
    assert f"end read {input_file}" in written
    assert "KeyboardInterrupt" in written


def test_a_usage_error_leaves_no_trace(tmp_path, input_file):
    """使用法の誤りは「どこまで進んだか」の話ではないので痕跡を残さない。"""
    result_json = tmp_path / "result.json"
    assert runner.invoke(app, ["run", str(input_file), "-o", str(result_json)]).exit_code == 0

    output = tmp_path / "figure.png"
    invocation = runner.invoke(
        app, ["plot", str(result_json), "-o", str(output), "--magnify", "5"]
    )

    assert invocation.exit_code == 2
    assert not output.with_suffix(".log").exists()


def test_lines_and_plot_take_the_log_option_too(tmp_path, input_file):
    lines_json = tmp_path / "lines.json"
    lines_log = tmp_path / "lines.log"
    plot_log = tmp_path / "plot.log"

    assert runner.invoke(
        app,
        ["lines", str(input_file), "-o", str(lines_json), "--show", "0",
         "--log", str(lines_log)],
    ).exit_code == 0
    assert runner.invoke(
        app,
        ["plot", str(lines_json), "-o", str(tmp_path / "sticks.png"),
         "--log", str(plot_log)],
    ).exit_code == 0

    assert "begin fc lines:" in lines_log.read_text(encoding="utf-8")
    assert "begin plot lines" in plot_log.read_text(encoding="utf-8")
