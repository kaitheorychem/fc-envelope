"""例外・警告クラス。

利用側が `except FCEnvelopeError` で一括捕捉できるよう、本パッケージが
意図的に送出する例外はすべて `FCEnvelopeError` の派生とする。
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence

__all__ = [
    "FCEnvelopeError",
    "InvalidInputError",
    "UnsupportedUnitError",
    "SchemaVersionError",
    "NumericalQualityWarning",
    "report_quality",
]


class FCEnvelopeError(Exception):
    """本パッケージが送出する例外の基底クラス。"""


class InvalidInputError(FCEnvelopeError):
    """値の範囲・整合性の違反。pydantic の ValidationError をラップする。"""


class UnsupportedUnitError(FCEnvelopeError):
    """cm^-1 以外の単位が指定された。"""


class SchemaVersionError(FCEnvelopeError):
    """入出力ファイルの schema_version が実装と一致しない。"""


class NumericalQualityWarning(UserWarning):
    """数値計算の品質が閾値を下回ったことを示す警告。

    計算自体は完走し、警告文言は `Diagnostics.messages` にも残る。
    """


def report_quality(messages: Sequence[str]) -> tuple[str, ...]:
    """品質の警告をまとめて発報し、結果に残す形で返す。

    計算は完走させ、品質は警告で知らせるという方針（ADR-0009）の実装はこの 1 箇所で
    済む。両系統で共通なのは発報と記録の手順だけで、**メッセージ本文は各系統が手書きで
    持つ**（ADR-0036）。本文には「どう直すか」というその項目にしかない知識があり、
    雛形に押し込めるとそれが失われる。
    """
    reported = tuple(messages)
    for message in reported:
        # 2 つ上が compute_* の呼び出し元になる（compute_* -> report_quality -> warn）。
        warnings.warn(message, NumericalQualityWarning, stacklevel=3)
    return reported
