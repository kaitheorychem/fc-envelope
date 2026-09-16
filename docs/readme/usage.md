# 使い方

振電相互作用・振動数（ω_α）・温度（T）から Franck-Condon スペクトルを計算する。
出力には 2 つの表現がある。

- **エンベロープ F(E)**（`run`）— 時間相関関数のフーリエ変換による連続スペクトル。多数のモードを
  含めた全体像を精度よく得たいとき。
- **離散 FC 因子**（`lines`）— 個々の振動遷移の FC 因子と、その遷移エネルギーの一覧。
  どのモードが何量子ぶん効いているかを定性的に見たいとき。

両者は同じ物理量の別表現で、線を線形状で畳んで足し上げるとエンベロープに一致する。
語の定義は `CONTEXT.md` にまとめてある。とくに **密度**（エンベロープの縦軸、1/cm⁻¹）と
**重み**（線の縦軸、無次元）は次元の違う別の量なので、どちらも「強度」とは呼ばない。

## エネルギーの向き

E = 0 が ZPL（zero-phonon line）で、E は ZPL からの符号付き変位 [cm⁻¹]。
振動量子を k 個生成するサイドバンドは **E = −k·ε_α**（負側）に立つ。
有限温度ではホットバンドにより正側にも重みが乗り、F(E) は左右非対称になる。

吸収／発光の区別は導入していない。F(E) はどちらでもない中立な量である。

## 入力ファイル

モードデータと計算条件を 1 ファイルに入れる。このファイル 1 つで計算が完全に再現できる。

```json
{
  "schema_version": 2,
  "frequency_unit": "cm^-1",
  "coupling_convention": "g",
  "modes": [
    { "frequency": 1200.0, "coupling": 0.5 },
    { "frequency":  450.0, "coupling": 0.8 }
  ],
  "temperature": 300.0,
  "broadening": { "sigma": 150.0, "gamma": 0.0 },
  "grid": { "e_min": -4000.0, "e_max": 1000.0, "de": 5.0 },
  "selection": { "min_weight": 0.0001, "max_lines": 10000, "max_quanta": null }
}
```

条件は性質ごとに 4 つに分かれている。`temperature` は物理（答えが変わる）、`broadening`
は線の形を決める現象論的なパラメータ、`grid` と `selection` は数値（どこを標本するか・
どれを保持するか）である。`run` は `temperature` / `broadening` / `grid` を、`lines` は
`temperature` / `selection` を読み、互いに相手の節を無視する。

| フィールド | 意味 | 制約 |
|---|---|---|
| `schema_version` | 入力形式の版 | `2` のみ（v1 は明示的に拒否する） |
| `frequency_unit` | 振動数の単位 | `"cm^-1"` のみ |
| `coupling_convention` | `coupling` の流儀（下表） | 既定は `"g"` |
| `modes[].frequency` | ε_α [cm⁻¹] | > 0 |
| `modes[].coupling` | 流儀に従った値（キー名は流儀によらず `coupling`） | ≥ 0 |
| `temperature` | T [K] | ≥ 0（0 は許可） |
| `broadening.sigma` | ガウス幅 σ [cm⁻¹] | ≥ 0 |
| `broadening.gamma` | ローレンツ幅 γ [cm⁻¹] | ≥ 0、既定 0.0。σ と両方 0 は不可 |
| `grid.e_min` / `e_max` | 出力窓 [cm⁻¹] | `e_min` < `e_max` |
| `grid.de` | 出力グリッド間隔 [cm⁻¹] | > 0 |
| `selection.min_weight` | 保持する重みの下限 | 0 < x ≤ 1、既定 1e-4 |
| `selection.max_lines` | 保持・列挙する線数の上限 | ≥ 1、既定 10000 |
| `selection.max_quanta` | 1 モードあたりの量子数の上限 | ≥ 0 または `null`（自動）|

`selection` の節は省略できる（既定値が使われる）。`broadening` と `grid` は `run` に必須。

### 振電相互作用の流儀

`coupling` の値をどの量で書くかを `coupling_convention` で選ぶ。内部では常に
Huang-Rhys 因子 S へ正準化される。関係式は `docs/theory/vcc.md` にある。

| 値 | 量 | S への変換 | `coupling` の単位 |
|---|---|---|---|
| `"g"` | 無次元化振電相互作用定数 g | S = g² | 無次元 |
| `"delta"` | 無次元化変位 Δ | S = Δ²/2 | 無次元 |
| `"huang_rhys"` | Huang-Rhys 因子 S | そのまま | 無次元 |
| `"vcc"` | 振電相互作用定数 V | S = V²/(2ω³) | (cm⁻¹)^(3/2) |
| `"lambda"` | 再配列エネルギー λ | S = λ/ω | cm⁻¹ |

V と λ は単位を持つため、同じモードの `frequency` と組で解釈される。単位系は
`frequency_unit` が決めるので、`coupling` だけ別の単位で書くことはできない。

### モードを CSV で渡す

モード数が多い場合や外部プログラムの出力を使う場合は、`modes` に CSV への参照を書ける。

```json
{
  "schema_version": 2,
  "frequency_unit": "cm^-1",
  "coupling_convention": "g",
  "modes": { "path": "modes.csv" },
  "temperature": 300.0,
  "broadening": { "sigma": 150.0 },
  "grid": { "e_min": -4000.0, "e_max": 1000.0, "de": 5.0 }
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
γ > 0 のときは裾が 1/E² でしか落ちないので、この目安よりかなり広く取らないと
`window_captured_fraction` が上がらない。

## CLI

```bash
# 計算して結果 JSON を書き出す（図も同時に出す場合は --plot）
uv run fcenvelope run input.json -o result.json --plot spectrum.png

# 条件だけ振る（modes は上書きできない）
uv run fcenvelope run input.json -o result_0K.json --temperature 0

# 線形状にローレンツ幅を混ぜる（σ だけならガウス、γ だけならローレンツ、両方で Voigt）
uv run fcenvelope run input.json -o result_voigt.json --gamma 40

# 離散 FC 因子の一覧を書き出す
uv run fcenvelope lines input.json -o lines.json --min-weight 1e-5

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

入力ファイルは `run` と同じものをそのまま使う。読むのは `temperature` と `selection` だけで、
`broadening` と `grid` は使わない。

```bash
# FC 因子と遷移エネルギーを書き出し、重みの上位 10 本を表示する
uv run fcenvelope lines input.json -o lines.json

# T = 0 で、より細かい閾値まで拾う。棒スペクトルも出す
uv run fcenvelope lines input.json -o lines_0K.json --temperature 0 \
    --min-weight 1e-6 --plot sticks.png

# 表示だけ増やす（--show 0 で表を出さない）
uv run fcenvelope lines input.json -o lines.json --show 30
```

```
wrote lines.json (58 lines, captured=0.997261, <E>=-583.531 cm^-1, lambda=588 cm^-1)
     E / cm^-1            FC        weight  transition
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
量子数がすべて 0 の線は `ZPL`。線は**重みの降順**に並ぶので、主要なものから順に読めばよい。

### FC 因子と重み

| 値 | 意味 |
|---|---|
| `fc_factor` | FC 因子そのもの Π_α FC_{m_α n_α}（無次元） |
| `weight` | 始状態の熱占有を掛けた重み Π_α P(n_α)·FC_{m_α n_α}。全遷移にわたる総和は 1 |

T = 0 では始状態が振動基底状態だけなので両者は一致する。有限温度ではホットバンド
（n_α > m_α）が正側に立ち、その `weight` は始状態の占有ぶんだけ小さくなる。

重み {w_ℓ} は遷移の上の離散確率分布で、エンベロープの密度 F(E) はそれを線形状で
平滑化したものにあたる（F(E) = Σ_ℓ w_ℓ·L(E − E_ℓ)、∫F dE = Σ_ℓ w_ℓ = 1）。
両者を同じ「強度」という語で呼ばないのはこのためである。

### どこまで返すか

`--min-weight`（既定 1e-4）以上の線を**すべて**返す。全遷移は無限個あるので閾値が要る。

- どれだけ拾えたかは `captured_weight`（拾った線の重みの総和）で分かる。1 に近いほど
  スペクトルの全体を見ていることになる。
- 閾値が高すぎて 1 本も残らない場合は、最強の線の重みを警告に載せるので、そこまで下げればよい。
- 熱的に活性なモードが多い系では重みが膨大な数の線に分散し、離散線での記述自体が意味を失う。
  その場合は `run`（エンベロープ）を使う。

つまみは入力ファイルの `selection` にも書ける。CLI で指定したものだけが上書きされ、
実際に使われた値は結果ファイルに丸ごと記録されるので、結果だけから計算を再現できる。

## ライブラリとして使う

```python
from fcenvelope import (
    Broadening, EnergyGrid, FCEnvelopeInput, VibrationalMode,
    compute_envelope, load_envelope, plot_envelope, save_envelope,
)

# 引数から直接
modes = [VibrationalMode(frequency=1200.0, huang_rhys=0.25)]
result = compute_envelope(
    modes,
    temperature=300.0,
    broadening=Broadening(sigma=150.0),                    # gamma は既定 0.0
    grid=EnergyGrid(e_min=-4000.0, e_max=1000.0, de=5.0),
)

# 入力ファイルから（流儀と単位はここで消費される。modes の CSV 参照もここで解決）
parsed = FCEnvelopeInput.from_path("input.json")
result = compute_envelope(
    parsed.to_modes(),
    temperature=parsed.temperature,
    broadening=parsed.broadening,
    grid=parsed.grid,
)

save_envelope(result, "result.json")
result = load_envelope("result.json")

fig = plot_envelope(result, label="300 K")   # 保存は呼び出し側の責務
fig.savefig("spectrum.png", dpi=300)
```

離散 FC 因子も同じ 4 関数の形をしている。どちらの系統も「共通の物理条件
（`temperature`）＋自分に固有の数値条件（`grid` / `selection`）」という同じ形をとる。

```python
from fcenvelope import Selection, compute_fc_lines, load_lines, plot_lines, save_lines

lines = compute_fc_lines(modes, temperature=300.0, selection=Selection(min_weight=1e-5))
for line in lines.lines[:5]:
    labels = [f"#{t.mode_index}: {t.initial}->{t.final}" for t in line.transitions]
    print(f"{line.energy:9.1f} cm^-1  FC={line.fc_factor:.5f}  w={line.weight:.5f}  {labels}")

save_lines(lines, "lines.json")
lines = load_lines("lines.json")
plot_lines(lines).savefig("sticks.png", dpi=300)
```

`lines.energies` / `lines.fc_factors` / `lines.weights` で ndarray としても取れる。
理論文書の行列そのものが要る場合は `fc_factor_matrix(S, m_max, n_max)` を使う。

エンベロープと離散線を 1 枚に重ねるには `plot_overlay` を使う。

```python
from fcenvelope import plot_overlay

plot_overlay(result, lines, title="300 K").savefig("overlay.png", dpi=300)
```

複数条件を 1 枚に重ねる場合は `ax` を渡す。

```python
import matplotlib.pyplot as plt

broadening = Broadening(sigma=150.0)
grid = EnergyGrid(e_min=-4000.0, e_max=1000.0, de=5.0)

fig, ax = plt.subplots()
for temperature in (0.0, 77.0, 300.0):
    result = compute_envelope(
        modes, temperature=temperature, broadening=broadening, grid=grid
    )
    plot_envelope(result, ax=ax, label=f"{temperature:g} K")
```

## エンベロープと離散線を重ねる

`run` の曲線と `lines` の棒は同じ物理量の別表現で、E 軸の規約も共通しているので 1 枚に重ねられる。

```bash
uv run fcenvelope run   input.json -o result.json
uv run fcenvelope lines input.json -o lines.json
uv run fcenvelope plot  result.json lines.json -o overlay.png --title "300 K"
```

**縦軸は 1 本しかない。** 重み w は無次元だが、線形状の頂点 V(0; σ, γ) を掛けて
F(E) と同じ 1/cm⁻¹ に直してから描く。この高さは「その線が F(E) に立てる山の高さ
そのもの」なので、棒と曲線の高さをそのまま比べてよい。頂点は γ = 0 なら
1/(σ√(2π))、σ = 0 なら 1/(πγ)、その間では規格化 Voigt 関数の頂点になる。

- 孤立した線では棒の先端が曲線の山にぴたりと一致する。
- 線形状の幅の中に線が何本も密集するところでは曲線が棒より高くなる。これは縮尺の
  都合ではなく、その山が 1 本の遷移では説明できないことを意味する。
- γ > 0 では裾が 1/E² でしか落ちないので、「孤立している」と言える条件が
  ガウスのときより厳しくなる。弱い線の棒は隣の線の裾に埋もれる。

線形状は `result` 側の条件から取る（`lines` は線形状を持たない）。

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

`EnvelopeResult` は配列（`energy` / `density`）に加えて、入力エコー（`modes` /
`temperature` / `broadening` / `grid`）・再配列エネルギー λ・診断値・来歴
（`fcenvelope_version` / `created_at`）を持つ。`save_envelope` はこれらをすべて
1 つの JSON に書くため、そのファイルだけから `load_envelope` で完全に復元でき、
後から信頼可否も判定できる。

`LinesResult` も同じ作りで、`lines`（各線のエネルギー・FC 因子・重み・量子数）に加えて
入力エコー（`modes` / `temperature` / `selection`）・λ・診断値・来歴を持つ。選択条件は
`Selection` オブジェクトごとエコーされるので、`max_quanta` まで含めて計算を再現できる。
出力 JSON は `kind` が `"fcenvelope.fc_lines"` になる点だけが異なり、`load_lines` で
完全に復元できる。

## 数値品質の見方

計算は常に完走し、品質は `result.diagnostics` に記録される。閾値を超えた項目は
`NumericalQualityWarning` として警告され、同じ文言が `diagnostics.messages` に残る。

| 診断値 | 意味するもの | 対処 |
|---|---|---|
| `damping_at_tau_max` | 大きい（> 1.5e-8）と τ 窓の打ち切りによるリンギング | `de` を小さく（γ = 0 なら σ/2 より小さければ足りる） |
| `edge_density_ratio` | 大きい（> 1e-4）とエイリアシング | `e_min` / `e_max` を広く |
| `window_captured_fraction` | 小さい（< 0.99）と窓がエンベロープを取りこぼしている | `e_min` / `e_max` を広く |
| `total_area` | 1 から外れるのは実装の誤り | — |
| `max_imaginary_ratio` | 大きいのは ρ の対称性の破れ（実装の誤り） | — |

`damping_at_tau_max` は τ 窓が閉じる時点で線形状の減衰がどこまで進んだかを表す。
σ と γ のどちらが効いているかを問わない 1 つの数なので、純ローレンツ型でも誤警報に
ならない。健全な計算ではアンダーフローして 0.0 になる。

`edge_density_ratio` は `total_area` では検出できない失敗（重みが折り返して
戻るため面積は 1 のまま）を捉える。両方を見ること。γ > 0 では裾が重いぶんこの値も
`window_captured_fraction` も悪くなりやすい。

離散 FC 因子（`compute_fc_lines`）の診断値は別の項目を持つ。

| 診断値 | 意味するもの | 対処 |
|---|---|---|
| `captured_weight` | 小さい（< 0.9）と閾値が粗く、スペクトルの大半を取りこぼしている | `--min-weight` を下げる |
| `beam_truncated` | True なら `max_lines` で列挙を打ち切っており、閾値以上の線が欠けている | `--max-lines` を上げるか閾値を粗くする |
| `min_mode_completeness` | 1 から外れると振動梯子の打ち切り | `--max-quanta` を上げる |
| `recurrence_limited` | True なら漸化式の桁落ちを避けて始状態を打ち切っている | 閾値を粗くするか温度を下げる |
| `mean_energy` | ⟨E⟩。収束していれば −λ に一致する（記録のみ） | — |
