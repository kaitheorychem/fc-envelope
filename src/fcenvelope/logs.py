"""ログの出力先。節目の記録をどこへ書くかだけを決める（ADR-0052）。

記録の仕組みは標準ライブラリの `logging` そのもので、このモジュールが足すのは
2 つだけである。

* `stage` — 節目の開始と完了を 1 行ずつ残す文脈マネージャ。**ループの内側では
  使わない**。節目はファイルの読み書き・重い数値計算・図の書き出しのような、
  1 回の実行に数回しか現れない区切りだけを指す。
* `Trace` — CLI が 1 回の実行につき 1 つ持つ出力先。既定ではメモリに溜めるだけで、
  異常終了したときにだけファイルへ書き出す。正常に終わった実行はログのための
  ファイル IO を 1 回も行わない。

ライブラリとして使う場合、このモジュールを呼ぶ必要はない。`logging` の作法どおり
`fcenvelope` ロガー（`LOGGER_NAME`）にハンドラを付ければ節目が流れてくる。付けなければ
下の `NullHandler` が受けるので何も出ない。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from logging.handlers import MemoryHandler
from pathlib import Path

from .errors import InvalidInputError

__all__ = ["LOGGER_NAME", "Trace", "stage"]

#: 本パッケージの節目を集めるロガー。各モジュールはこの下に `__name__` で枝を持つ。
LOGGER_NAME = "fcenvelope"

#: ログ 1 行の書式。時刻が要るのは「どこまで進んで止まったか」を読むためである。
FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

#: 溜めておく行数の上限。節目しか記録しないので実際には届かない。
CAPACITY = 1000

#: ライブラリとしての既定。ハンドラが 1 つもないと `logging` が最後の手段として
#: stderr へ出すので、それを抑えるために付ける（`logging` 公式の作法）。
logging.getLogger(LOGGER_NAME).addHandler(logging.NullHandler())


@contextmanager
def stage(logger: logging.Logger, label: str) -> Iterator[None]:
    """節目の開始と完了を記録する。

    完了行には経過時間を添える。途中で例外が出た場合は完了行を**書かない**。
    開始行だけがあって完了行がない、という形がそのまま「ここで止まった」を意味する
    ことがこの記録の目的だからである。

    ループの内側では使わない（ADR-0052）。
    """
    logger.info("begin %s", label)
    started = time.perf_counter()
    yield
    logger.info("end %s (%.3f s)", label, time.perf_counter() - started)


def _file_handler(path: Path) -> logging.FileHandler:
    """書き出し先のファイルハンドラ。親ディレクトリは作る。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, mode="w", encoding="utf-8")
    except OSError as exc:
        raise InvalidInputError(f"cannot write log file {path}: {exc}") from exc
    handler.setFormatter(logging.Formatter(FORMAT))
    return handler


class Trace:
    """1 回の実行の節目の記録。

    `path` を与えるとその場でファイルを開き、以降の節目を直に書く。与えない場合は
    メモリに溜めるだけで、`dump` を呼んだときにだけファイルに触れる。CLI は
    `--log` が指定されたときだけ `path` を与え、そうでなければ異常終了したときに
    `dump` する（ADR-0052）。
    """

    def __init__(self, path: Path | None = None, *, level: int = logging.INFO) -> None:
        self._logger = logging.getLogger(LOGGER_NAME)
        self._previous_level = self._logger.level
        self._buffer: MemoryHandler | None
        self._handler: logging.Handler
        if path is None:
            # flushLevel は使わない。書き出す時機を決めるのは `dump` の呼び出し側で
            # あって、記録の重大度ではない。
            self._buffer = MemoryHandler(CAPACITY, flushLevel=logging.CRITICAL + 1)
            self._handler = self._buffer
        else:
            self._buffer = None
            self._handler = _file_handler(path)
        self._logger.addHandler(self._handler)
        self._logger.setLevel(level)

    def dump(self, path: Path) -> Path | None:
        """溜めた記録を書き出し、その場所を返す。

        既にファイルへ書いている場合（`--log` 指定時）と、書き出せなかった場合は
        `None` を返す。痕跡を残せないこと自体は、元のエラーを押しのけて報告する
        ほどのことではない。
        """
        if self._buffer is None:
            return None
        try:
            target = _file_handler(path)
        except InvalidInputError:
            return None
        self._buffer.setTarget(target)
        try:
            self._buffer.flush()
        finally:
            self._buffer.setTarget(None)
            target.close()
        return path

    def close(self) -> None:
        """ハンドラを外し、ロガーの水準を元に戻す。"""
        self._logger.removeHandler(self._handler)
        self._handler.close()
        self._logger.setLevel(self._previous_level)
