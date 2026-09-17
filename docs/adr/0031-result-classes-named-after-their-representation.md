# 結果クラスを表現ごとの名前にし、`result` の専有をやめる

- 日付: 2026-09-16
- 状態: 受理（ADR-0011 の命名を改める）

`result.py` / `RESULT_KIND = "fcenvelope.result"` / `save_result` / `load_result` /
`plot_result` はいずれもエンベロープ専用だったが、`FCLinesResult` も同じく result であり、
総称語が片方の系統を専有していた。共通の抽象を作るうえで必ず衝突するので、改名する。

| 旧 | 新 |
|---|---|
| `FCEnvelopeResult` | `EnvelopeResult` |
| `FCLinesResult` | `LinesResult` |
| `save_result` / `load_result` / `plot_result` | `save_envelope` / `load_envelope` / `plot_envelope` |
| `save_fc_lines` / `load_fc_lines` / `plot_fc_lines` | `save_lines` / `load_lines` / `plot_lines` |
| `kind = "fcenvelope.result"` | `kind = "fcenvelope.envelope"` |

## 検討した選択肢

`Envelope` / `LineSpectrum` のように `Result` を落として物理的な対象名にすることも検討したが
採らない。これらのクラスは `diagnostics` と `created_at` と `fcenvelope_version` を抱えて
おり、**エンベロープそのものではなく「エンベロープを計算した結果」**である。`Result` を
接尾辞として両系統に等しく配ることで、この語が片方を専有している状態が解消する。
