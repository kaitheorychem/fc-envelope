# 共有物理層を挟み、2 つの系統を対等な兄弟にする

- 日付: 2026-09-16
- 状態: 受理（ADR-0014 を差し替える）

現行の依存は `errors → models → result → core → fcfactor → {io, plotting} → cli`。ここに
2 つの歪みがある。**`core.py` が「共有物理」と「エンベロープ固有の FFT」を同居させて
いる**こと（`K_B_CM`・`occupation_numbers`・`reorganization_energy` は両系統が使う）。その
結果 **`fcfactor` が `core` を import している**——離散線の計算がエンベロープのモジュールに
依存するという、物理的に理由のない向きである。

離散線は「エンベロープの一部」ではなく対等な別表現（ADR-0021）なのに、依存図はそう読め
ない。共有物理層を挟んで兄弟にする。

```
errors → units → models → physics → result → { envelope, lines } → { io, plotting } → cli
                              normalmodes ↗
```

| モジュール | 責務 | 変更 |
|---|---|---|
| `units.py` | 流儀オブジェクト（ADR-0033）、単位の検証と変換 | 新規 |
| `models.py` | `VibrationalMode` / `Broadening` / `EnergyGrid` / `Selection`、入力ファイル | 縮小 |
| `physics.py` | `K_B_CM`、占有数 n_α、梯子 P(n)、λ | `core.py` から分離 |
| `envelope.py` | グリッド構成・FFT | `core.py` の残り |
| `lines.py` | 漸化式・線の列挙 | `fcfactor.py` を改名 |
| `normalmodes.py` | 対角化（ADR-0037） | 新規 |

`boltzmann_populations` を `physics.py` へ移すのは、`occupation_numbers`（ボーズ分布の
平均 n_α）と `boltzmann_populations`（同じ分布の確率質量 P(n)）が **n_α = Σ_n n·P(n)** と
いう関係にある同一物理の 2 つの顔だからである。別モジュールに置く理由がない。

## 検討した選択肢

理論プリミティブ（`displacement_matrix` / `fc_factor_matrix`）を `lines.py` から分離する
案は採らない。これらは公開はしているが（理論式そのものを直接触れるようにするため）、
内部の利用者は `lines.py` の 1 つだけである。分離しても継ぎ目が増えるだけになる。
