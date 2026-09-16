# 依存を 5 つに絞り、extras による分割をしない

- 日付: 2026-07-25
- 状態: 受理

必須依存は numpy（配列・FFT）、scipy（`scipy.constants` の k_B、将来の単位変換の受け皿）、pydantic v2（入力の検証）、typer（CLI）、matplotlib（描画）。dev 依存は pytest。Python 3.11 以上。

matplotlib と typer を optional extras に分けることは検討したが採らない。README の `uv sync` → `uv run fcenvelope` が素の同期だけで動くことを優先する。
