# 計算は常に完走させ、品質は診断値と警告で伝える

- 日付: 2026-07-25
- 状態: 受理

数値品質の問題で計算を中断しない。品質は診断値として結果クラスに記録し、閾値を超えたものは `NumericalQualityWarning`（`UserWarning` 派生）で発報するとともに、同じ文言を `messages` に残す。**出力ファイルだけを後から見て信頼可否を判定できる**ことを重視する。

## 帰結

各診断値は互いに異なる失敗モードを検出するよう選ぶ。エンベロープでは `sigma_tau_max`（打ち切りリンギング）、`edge_intensity_ratio`（エイリアシング）、`total_area`（実装の誤り）、`window_captured_fraction`（切り出し窓が狭い）、`max_imaginary_ratio`（ρ の対称性の破れ）。

`total_area` について注意が要る。エイリアシングでは重みが畳み込まれて戻るため面積は 1 のまま変化せず、この指標では検出できない。だから `edge_intensity_ratio` が別に必要になる。
