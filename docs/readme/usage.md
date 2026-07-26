# 使い方

VCC（g_α）・振動数（ω_α）・温度（T）から Franck-Condon エンベロープ F(E) を計算する。

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

E 範囲の目安は `e_min ≲ −(λ + 5√Var)`、`e_max ≳ +5σ`。
ここで λ = Σ S_α ε_α、Var = Σ S_α ε_α²(2n_α+1) + σ²。

## CLI

```bash
# 計算して結果 JSON を書き出す（図も同時に出す場合は --plot）
uv run fcenvelope run input.json -o result.json --plot spectrum.png

# 条件だけ振る（modes は上書きできない）
uv run fcenvelope run input.json -o result_0K.json --temperature 0

# 計算をやり直さずに図だけ作り直す
uv run fcenvelope plot result.json -o spectrum.png --title "300 K" --dpi 300
```

終了コードは 正常 `0` / 入力・計算エラー `1` / 使用法エラー `2`。

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

# 入力ファイルから（流儀と単位はここで消費される）
parsed = FCEnvelopeInput.from_path("input.json")
result = compute_envelope(parsed.to_modes(), parsed.conditions)

save_result(result, "result.json")
result = load_result("result.json")

fig = plot_result(result, label="300 K")   # 保存は呼び出し側の責務
fig.savefig("spectrum.png", dpi=300)
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

## 結果の中身

`FCEnvelopeResult` は配列（`energy` / `intensity`）に加えて、入力エコー・
再編成エネルギー λ・診断値・来歴（`fcenvelope_version` / `created_at`）を持つ。
`save_result` はこれらをすべて 1 つの JSON に書くため、そのファイルだけから
`load_result` で完全に復元でき、後から信頼可否も判定できる。

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
