"""例外・警告クラス。

利用側が `except FCEnvelopeError` で一括捕捉できるよう、本パッケージが
意図的に送出する例外はすべて `FCEnvelopeError` の派生とする。
"""

from __future__ import annotations

__all__ = [
    "FCEnvelopeError",
    "InvalidInputError",
    "UnsupportedUnitError",
    "SchemaVersionError",
    "NumericalQualityWarning",
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
