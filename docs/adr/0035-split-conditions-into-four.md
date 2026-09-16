# `Conditions` を廃し、温度・線形状・グリッド・選択条件に分ける

- 日付: 2026-09-16
- 状態: 受理（ADR-0005 / ADR-0012 / ADR-0021 の該当部分を改める）

`Conditions(temperature, sigma, e_min, e_max, de)` は性質の違う 3 種を束ねていた。温度は
**物理**（答えが変わる）、σ・γ は**現象論的なモデルパラメータ**、E グリッドは**数値**
（どこを標本するかだけ）である。`compute_fc_lines` が `Conditions` を取らないのは必要な
ものが最初の 1 つだけだからで（ADR-0021）、分割線はすでに実装側から示唆されていた。

```python
compute_envelope(modes, *, temperature, broadening: Broadening, grid: EnergyGrid) -> EnvelopeResult
compute_fc_lines(modes, *, temperature, selection: Selection)                     -> LinesResult

Broadening(sigma, gamma)                       # ADR-0034
EnergyGrid(e_min, e_max, de)
Selection(min_weight, max_lines, max_quanta)
```

決め手は**構造が対称になること**である。両系統とも「共通の物理条件（temperature）＋
自分に固有の数値条件（envelope は grid、lines は selection）」という同じ形になり、
ADR-0021 が言葉で説明していた非対称が構造から消える。

## 帰結

- `Selection` が 1 つのオブジェクトとして丸ごとエコーされるため、**`max_quanta` が結果に
  記録されていなかった穴が自動的に閉じる**。「つまみを足したがエコーを足し忘れる」という
  バグのクラス自体が消える。
- 入力 JSON も平らにする: `{"modes":…, "temperature":…, "broadening":{…}, "grid":{…},
  "selection":{…}}`。`run` と `lines` が完全に同じファイルを使える性質（ADR-0005）は保つ。
- ADR-0012 の「CLI が上書きできるのは `conditions` の 5 フィールドのみ」は「temperature /
  broadening / grid / selection を上書きでき、modes は上書きしない」と読み替える。
