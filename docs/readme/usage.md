# 使い方

無次元化 VCC（g_α）・振動数（ω_α）・温度（T）から Franck-Condon スペクトルを計算する。
出力には 2 つの表現がある。

- **エンベロープ F(E)**（`run`）— 時間相関関数のフーリエ変換による連続スペクトル。多数のモードを
  含めた全体像を精度よく得たいとき。
- **離散 FC 因子**（`lines`）— 個々の振動遷移の FC 因子と、その遷移エネルギーの一覧。
  どのモードが何量子ぶん効いているかを定性的に見たいとき。

両者は同じ物理量の別表現で、線を σ のガウシアンで畳んで足し上げるとエンベロープに一致する。

## エネルギーの向き

E = 0 が ZPL（zero-phonon line）で、E は ZPL からの符号付き変位 [cm⁻¹]。
振動量子を k 個生成するサイドバンドは **E = −k·ε_α**（負側）に立つ。
有限温度ではホットバンドにより正側にも重みが乗り、F(E) は左右非対称になる。

吸収／発光の区別は導入していない。F(E) はどちらでもない中立な量である。

## 入力ファイル

モードデータと計算条件を 1 ファイルに入れる。このファイル 1 つで計算が完全に再現できる。

```json
{
  "schema_version": 1,
  "frequency_unit": "cm^-1",
  "coupling_convention": "g",
  "modes": [
    { "frequency": 1200.0, "coupling": 0.5 },
    { "frequency":  450.0, "coupling": 0.8 }
  ],
  "conditions": {
    "temperature": 300.0,
    "sigma": 150.0,
    "e_min": -4000.0,
    "e_max": 1000.0,
    "de": 5.0
  }
}
```

| フィールド | 意味 | 制約 |
|---|---|---|
| `frequency_unit` | 振動数の単位 | `"cm^-1"` のみ |
| `coupling_convention` | `coupling` の流儀。`"g"` なら S = g²、`"huang_rhys"` なら S をそのまま | 既定は `"g"` |
| `modes[].frequency` | ε_α [cm⁻¹] | > 0 |
| `modes[].coupling` | 流儀に従った値（キー名は流儀によらず `coupling`） | ≥ 0 |
| `conditions.temperature` | T [K] | ≥ 0（0 は許可） |
| `conditions.sigma` | スペクトル幅 σ [cm⁻¹] | > 0 |
| `conditions.e_min` / `e_max` | 出力窓 [cm⁻¹] | `e_min` < `e_max` |
| `conditions.de` | 出力グリッド間隔 [cm⁻¹] | > 0 |

### モードを CSV で渡す

モード数が多い場合や外部プログラムの出力を使う場合は、`modes` に CSV への参照を書ける。

```json
{
  "schema_version": 1,
  "frequency_unit": "cm^-1",
  "coupling_convention": "g",
  "modes": { "path": "modes.csv" },
  "conditions": { "temperature": 300.0, "sigma": 150.0, "e_min": -4000.0, "e_max": 1000.0, "de": 5.0 }
}
```

```csv
frequency,coupling
1200.0,0.5
450.0,0.8
```

- 相対パスは**入力 JSON ファイルの場所**が基準。
- 書式は CSV の標準（RFC 4180）に従う。列は `frequency` と `coupling` の 2 列のみで、ほかの列があるとエラー。
- ヘッダ行は省略できる。省略時は `frequency,coupling` の順。ヘッダを書く場合は 1 行目に置き、列の順序は自由。
- RFC 4180 にはコメントの規定がないため、コメント行は書けない。空行もエラー（ファイル末尾の改行 1 つは可）。
- 行の順序は計算結果に影響しない。縮重モードは同じ値の行を複数書く。
- 単位と流儀は JSON 側の `frequency_unit` / `coupling_convention` に従う。
- 区切りはカンマのみ。エラーは `modes.csv:3: ...` のように行番号付きで報告される。
- 結果 JSON にはモードの値そのものが埋め込まれるので、CSV が後で変わっても結果ファイル単体で再現できる。

E 範囲の目安は `e_min ≲ −(λ + 5√Var)`、`e_max ≳ +5σ`。
ここで λ = Σ S_α ε_α、Var = Σ S_α ε_α²(2n_α+1) + σ²。

## CLI

```bash
# 計算して結果 JSON を書き出す（図も同時に出す場合は --plot）
uv run fcenvelope run input.json -o result.json --plot spectrum.png

# 条件だけ振る（modes は上書きできない）
uv run fcenvelope run input.json -o result_0K.json --temperature 0

# 離散 FC 因子の一覧を書き出す
uv run fcenvelope lines input.json -o lines.json --min-intensity 1e-5

# 計算をやり直さずに図だけ作り直す（エンベロープ・棒スペクトルのどちらでも）
uv run fcenvelope plot result.json -o spectrum.png --title "300 K" --dpi 300
uv run fcenvelope plot lines.json  -o sticks.png   --title "300 K"

# 2 つを 1 枚に重ねる（与える順序は問わない）
uv run fcenvelope plot result.json lines.json -o overlay.png --title "300 K"
```

終了コードは 正常 `0` / 入力・計算エラー `1` / 使用法エラー `2`。

## 離散 FC 因子

`docs/theory/fc-factor.md` の漸化式で FC 因子 |⟨m|U(g)|n⟩|² を求め、対応する遷移エネルギーと
一緒に並べる。エネルギーは E 軸の規約どおり **E = −Σ_α (m_α − n_α)·ε_α**。

入力ファイルは `run` と同じものをそのまま使う。`conditions` のうち読むのは `temperature` だけで、
`sigma` と E グリッドは使わない。

```bash
# FC 因子と遷移エネルギーを書き出し、強度上位 10 本を表示する
uv run fcenvelope lines input.json -o lines.json

# T = 0 で、より細かい閾値まで拾う。棒スペクトルも出す
uv run fcenvelope lines input.json -o lines_0K.json --temperature 0 \
    --min-intensity 1e-6 --plot sticks.png

# 表示だけ増やす（--show 0 で表を出さない）
uv run fcenvelope lines input.json -o lines.json --show 30
```

```
wrote lines.json (58 lines, captured=0.997261, <E>=-583.531 cm^-1, lambda=588 cm^-1)
     E / cm^-1            FC     intensity  transition
             0      0.410656       0.36206  ZPL
          -450       0.26282      0.231718  #1:0->1
         -1200      0.102664     0.0905149  #0:0->1
          -900     0.0841023     0.0741498  #1:0->2
         -1650     0.0657049     0.0579296  #0:0->1, #1:0->1
           450       0.26282      0.026772  #1:1->0
          -450      0.243056     0.0247588  #1:1->2
         -2100     0.0210256     0.0185375  #0:0->1, #1:0->2
          -900      0.156139      0.015905  #1:1->3
         -1350     0.0179418     0.0158186  #1:0->3
  ... 48 more (see lines.json)
```

`#1:0->1` は「1 番目のモード（`modes` の並び順、0 始まり）が n = 0 から m = 1 へ」の意味。
量子数がすべて 0 の線は `ZPL`。線は**強度の降順**に並ぶので、主要なものから順に読めばよい。

### 2 つの強度

| 値 | 意味 |
|---|---|
| `fc_factor` | FC 因子そのもの Π_α FC_{m_α n_α}（無次元） |
| `intensity` | 始状態の熱占有を掛けた線強度 Π_α P(n_α)·FC_{m_α n_α}。全遷移にわたる総和は 1 |

T = 0 では始状態が振動基底状態だけなので両者は一致する。有限温度ではホットバンド
（n_α > m_α）が正側に立ち、その `intensity` は始状態の占有ぶんだけ小さくなる。

### どこまで返すか

`--min-intensity`（既定 1e-4）以上の線を**すべて**返す。全遷移は無限個あるので閾値が要る。

- どれだけ拾えたかは `captured_intensity`（拾った線の強度の総和）で分かる。1 に近いほど
  スペクトルの全体を見ていることになる。
- 閾値が高すぎて 1 本も残らない場合は、最強の線の強度を警告に載せるので、そこまで下げればよい。
- 熱的に活性なモードが多い系では強度が膨大な数の線に分散し、離散線での記述自体が意味を失う。
  その場合は `run`（エンベロープ）を使う。

## ライブラリとして使う

```python
from fcenvelope import (
    Conditions, FCEnvelopeInput, VibrationalMode,
    compute_envelope, load_result, plot_result, save_result,
)

# 引数から直接
modes = [VibrationalMode(frequency=1200.0, huang_rhys=0.25)]
conditions = Conditions(
    temperature=300.0, sigma=150.0, e_min=-4000.0, e_max=1000.0, de=5.0
)
result = compute_envelope(modes, conditions)

# 入力ファイルから（流儀と単位はここで消費される。modes の CSV 参照もここで解決）
parsed = FCEnvelopeInput.from_path("input.json")
result = compute_envelope(parsed.to_modes(), parsed.conditions)

save_result(result, "result.json")
result = load_result("result.json")

fig = plot_result(result, label="300 K")   # 保存は呼び出し側の責務
fig.savefig("spectrum.png", dpi=300)
```

離散 FC 因子も同じ 4 関数の形をしている。

```python
from fcenvelope import compute_fc_lines, load_fc_lines, plot_fc_lines, save_fc_lines

lines = compute_fc_lines(modes, temperature=300.0, min_intensity=1e-5)
for line in lines.lines[:5]:
    labels = [f"#{t.mode_index}: {t.initial}->{t.final}" for t in line.transitions]
    print(f"{line.energy:9.1f} cm^-1  FC={line.fc_factor:.5f}  I={line.intensity:.5f}  {labels}")

save_fc_lines(lines, "lines.json")
lines = load_fc_lines("lines.json")
plot_fc_lines(lines).savefig("sticks.png", dpi=300)
```

`lines.energies` / `lines.fc_factors` / `lines.intensities` で ndarray としても取れる。
理論文書の行列そのものが要る場合は `fc_factor_matrix(S, m_max, n_max)` を使う。

エンベロープと離散線を 1 枚に重ねるには `plot_overlay` を使う。

```python
from fcenvelope import plot_overlay

plot_overlay(result, lines, title="300 K").savefig("overlay.png", dpi=300)
```

複数条件を 1 枚に重ねる場合は `ax` を渡す。

```python
import matplotlib.pyplot as plt

fig, ax = plt.subplots()
for temperature in (0.0, 77.0, 300.0):
    result = compute_envelope(
        modes, conditions.model_copy(update={"temperature": temperature})
    )
    plot_result(result, ax=ax, label=f"{temperature:g} K")
```

## エンベロープと離散線を重ねる

`run` の曲線と `lines` の棒は同じ物理量の別表現で、E 軸の規約も共通しているので 1 枚に重ねられる。

```bash
uv run fcenvelope run   input.json -o result.json
uv run fcenvelope lines input.json -o lines.json
uv run fcenvelope plot  result.json lines.json -o overlay.png --title "300 K"
```

**縦軸は 1 本しかない。** 線強度 I は無次元だが、幅 σ の規格化ガウシアンの頂点
G_σ(0) = 1/(σ√(2π)) を掛けて F(E) と同じ 1/cm⁻¹ に直してから描く。この高さは
「その線が F(E) に立てる山の高さそのもの」なので、棒と曲線の高さをそのまま比べてよい。

- 孤立した線では棒の先端が曲線の山にぴたりと一致する。
- σ の中に線が何本も密集するところでは曲線が棒より高くなる。これは縮尺の都合ではなく、
  その山が 1 本の遷移では説明できないことを意味する。

σ は `result` 側の条件から取る（`lines` は σ を持たない）。

線が密集して棒が潰れる場合は `--magnify` で棒だけを拡大できる。倍率は凡例に `(×N)` と
出るので、拡大したことが図から失われない。

```bash
uv run fcenvelope plot result.json lines.json -o overlay.png --magnify 5
```

注意点が 2 つある。

- 横軸は `result` の E 窓に合わせるので、窓の外に立つ線は描かれない。落ちた本数は
  警告に出る。すべて見たいなら `run` の `--e-min` / `--e-max` を広げる。
- 2 つの結果のモードか温度が食い違っていると警告が出る。棒と曲線の対応が
  成り立つのは同じ系・同じ温度で計算した場合だけなので、図には出すが鵜呑みにしない。

## 結果の中身

`FCEnvelopeResult` は配列（`energy` / `intensity`）に加えて、入力エコー・
再配列エネルギー λ・診断値・来歴（`fcenvelope_version` / `created_at`）を持つ。
`save_result` はこれらをすべて 1 つの JSON に書くため、そのファイルだけから
`load_result` で完全に復元でき、後から信頼可否も判定できる。

`FCLinesResult` も同じ作りで、`lines`（各線のエネルギー・FC 因子・強度・量子数）に加えて
入力エコー・温度・選択条件・λ・診断値・来歴を持つ。出力 JSON は
`kind` が `"fcenvelope.fc_lines"` になる点だけが異なり、`load_fc_lines` で完全に復元できる。

## 数値品質の見方

計算は常に完走し、品質は `result.diagnostics` に記録される。閾値を超えた項目は
`NumericalQualityWarning` として警告され、同じ文言が `diagnostics.messages` に残る。

| 診断値 | 意味するもの | 対処 |
|---|---|---|
| `sigma_tau_max` | 小さい（< 6）と τ 窓の打ち切りによるリンギング | `de` を σ/2 より小さく |
| `edge_intensity_ratio` | 大きい（> 1e-4）とエイリアシング | `e_min` / `e_max` を広く |
| `window_captured_fraction` | 小さい（< 0.99）と窓がエンベロープを取りこぼしている | `e_min` / `e_max` を広く |
| `total_area` | 1 から外れるのは実装の誤り | — |
| `max_imaginary_ratio` | 大きいのは ρ の対称性の破れ（実装の誤り） | — |

`edge_intensity_ratio` は `total_area` では検出できない失敗（重みが折り返して
戻るため面積は 1 のまま）を捉える。両方を見ること。

離散 FC 因子（`compute_fc_lines`）の診断値は別の項目を持つ。

| 診断値 | 意味するもの | 対処 |
|---|---|---|
| `captured_intensity` | 小さい（< 0.9）と閾値が粗く、スペクトルの大半を取りこぼしている | `--min-intensity` を下げる |
| `beam_truncated` | True なら `max_lines` で列挙を打ち切っており、閾値以上の線が欠けている | `--max-lines` を上げるか閾値を粗くする |
| `min_mode_completeness` | 1 から外れると振動梯子の打ち切り | `--max-quanta` を上げる |
| `recurrence_limited` | True なら漸化式の桁落ちを避けて始状態を打ち切っている | 閾値を粗くするか温度を下げる |
| `mean_energy` | ⟨E⟩。収束していれば −λ に一致する（記録のみ） | — |
