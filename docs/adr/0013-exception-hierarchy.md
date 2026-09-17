# 例外を FCEnvelopeError の階層にまとめ、pydantic の例外を境界でラップする

- 日付: 2026-07-25
- 状態: 受理

本パッケージが意図的に送出する例外はすべて `FCEnvelopeError` の派生とし、利用側が `except FCEnvelopeError` で一括捕捉できるようにする。派生は `InvalidInputError`（値の範囲・整合性の違反）、`UnsupportedUnitError`、`SchemaVersionError`。

pydantic の `ValidationError` は I/O 境界で `InvalidInputError` にラップして送出する。CLI はそれを捕捉して短いメッセージと終了コードを返し、トレースバックを出さない。
