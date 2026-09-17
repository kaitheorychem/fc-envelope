# 共有物理層を挟み、2 つの系統を対等な兄弟にする

- 日付: 2026-09-16
- 状態: 受理（ADR-0014 を差し替える。ADR-0044〜0051 を反映済み）

現行の依存は `errors → models → result → core → fcfactor → {io, plotting} → cli`。ここに
2 つの歪みがある。**`core.py` が「共有物理」と「エンベロープ固有の FFT」を同居させて
いる**こと（`K_B_CM`・`occupation_numbers`・`reorganization_energy` は両系統が使う）。その
結果 **`fcfactor` が `core` を import している**——離散線の計算がエンベロープのモジュールに
依存するという、物理的に理由のない向きである。

離散線は「エンベロープの一部」ではなく対等な別表現（ADR-0021）なのに、依存図はそう読め
ない。共有物理層を挟んで兄弟にする。

| モジュール | 責務 | 依存先 | 変更 |
|---|---|---|---|
| `errors.py` | 例外・警告 | — | そのまま |
| `physics.py` | `K_B_CM`、占有数 n_α、梯子 P(n)。配列と数値だけを扱い、モデルの型を知らない | errors | `core.py` から分離 |
| `models.py` | 計算用の値の型 `VibrationalMode` / `VibrationalSystem` / `Broadening` / `EnergyGrid` / `Selection`（ADR-0044, 0045） | errors, physics | 入力ファイルの部分を切り出して縮小 |
| `units.py` | 流儀オブジェクト（ADR-0033）、単位の検証と変換 | errors | 新規 |
| `inputs.py` | 入力ファイルの型（pydantic）と正準化（ADR-0045） | errors, units, models | `models.py` から分離 |
| `result.py` | 結果クラス、`Provenance`（ADR-0046） | models | 構造を変更 |
| `envelope.py` | グリッド構成・FFT | physics, models, result | `core.py` の残り |
| `lines.py` | 漸化式・線の列挙 | physics, models, result | `fcfactor.py` を改名 |
| `io.py` | 保存・読み込み、`kind` の表（ADR-0049） | models, result | 表で振り分け |
| `plotting.py` | 描画、結果の型の表（ADR-0049） | models, result | 表で振り分け |
| `cli.py` | typer アプリ | 上記すべて | 上書きは入力ファイル側（ADR-0050） |

`envelope.py` と `lines.py` は互いに依存しない。`io.py` は `inputs.py` に依存しない（結果
ファイルの入力エコーは正準形なので、値の型を直接作る）。

`boltzmann_populations` を `physics.py` へ移すのは、`occupation_numbers`（ボーズ分布の
平均 n_α）と `boltzmann_populations`（同じ分布の確率質量 P(n)）が **n_α = Σ_n n·P(n)** と
いう関係にある同一物理の 2 つの顔だからである。別モジュールに置く理由がない。

対角化（ADR-0037、提案）を実装するときは `normalmodes.py` として `inputs` の横に置く想定だが、
このリファクタリングでは作らない。

## 検討した選択肢

理論プリミティブ（`displacement_matrix` / `fc_factor_matrix`）を `lines.py` から分離する
案は採らない。これらは公開はしているが（理論式そのものを直接触れるようにするため）、
内部の利用者は `lines.py` の 1 つだけである。分離しても継ぎ目が増えるだけになる。
