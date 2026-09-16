# インターフェイス仕様

変更が行われにくい部分のみを簡潔に記す。詳細は実際のコード（`src/fcenvelope/`）を本体とする。
語の定義は `CONTEXT.md`、量どうしの関係式は `docs/theory/`、判断の理由は `docs/adr/` にある。

スペクトルには 2 つの表現があり、それぞれに「計算・保存・読み込み・描画」の 4 関数を持つ。

| 表現 | 関数 | 結果クラス | 出力 `kind` |
|---|---|---|---|
| エンベロープ F(E) | `compute_envelope` 系 | `EnvelopeResult` | `fcenvelope.envelope` |
| 離散 FC 因子 | `compute_fc_lines` 系 | `LinesResult` | `fcenvelope.fc_lines` |

## 単位・規約

| 項目 | 値 |
|---|---|
| エネルギー | cm⁻¹（入力・内部・出力すべて） |
| τ | cm |
| 温度 | K |
| 振電相互作用の内部正準量 | S（Huang-Rhys 因子） |
| 密度 F(E) の単位 | 1/cm⁻¹（∫F dE = 1） |
| 重みの単位 | 無次元（全遷移にわたる総和 = 1） |
| 重ね描きでの棒の高さ | w·V(0; σ, γ)、単位は F(E) と同じ 1/cm⁻¹ |
| E 軸 | E = 0 が ZPL。k 量子生成のサイドバンドは E = −k·ε（負側） |

## 公開 API

`fcenvelope` トップレベルから公開する自由関数。

```python
# エンベロープ F(E)
compute_envelope(modes: Sequence[VibrationalMode], *, temperature: float,
                 broadening: Broadening, grid: EnergyGrid) -> EnvelopeResult
save_envelope(result: EnvelopeResult, path: str | Path) -> None
load_envelope(path: str | Path) -> EnvelopeResult
plot_envelope(result, *, ax=None, label=None, title=None) -> matplotlib.figure.Figure

# 離散 FC 因子
compute_fc_lines(modes, *, temperature: float,
                 selection: Selection = Selection()) -> LinesResult
save_lines(result: LinesResult, path: str | Path) -> None
load_lines(path: str | Path) -> LinesResult
plot_lines(result, *, ax=None, label=None, title=None) -> matplotlib.figure.Figure

# 理論式そのもの: FC_mn = |<m|U(sqrt(S))|n>|^2 を (m_max+1, n_max+1) で返す
fc_factor_matrix(huang_rhys: float, m_max: int, n_max: int = 0) -> np.ndarray

# 2 つの表現を 1 枚に重ねる
plot_overlay(envelope: EnvelopeResult, lines: LinesResult, *, ax=None,
             envelope_label="envelope", lines_label="FC lines",
             magnify=1.0, title=None) -> matplotlib.figure.Figure
```

結果クラスは純粋なデータ容器で、I/O と描画の責務を持たない。
`plot_*` は `Figure` を返すのみでファイル保存はしない。
両系統とも「共通の物理条件（`temperature`）＋自分に固有の数値条件（`grid` / `selection`）」
という同じ形をとる（ADR-0035）。

入力ファイルの読み込みは `FCEnvelopeInput` を経由する。

```python
FCEnvelopeInput.from_path(path)                   -> FCEnvelopeInput  # modes.path はファイル基準
FCEnvelopeInput.from_json(text, *, base_dir=None) -> FCEnvelopeInput
FCEnvelopeInput.from_obj(data, *, base_dir=None)  -> FCEnvelopeInput  # base_dir 省略時は cwd 基準
FCEnvelopeInput.to_modes()   -> list[VibrationalMode]  # 流儀を消費して正準化
FCEnvelopeInput.coupling_unit -> str | None            # 無次元の流儀では None
```

## データモデル

値型（frozen, pydantic）。検証の失敗は直接構築でも `from_obj` でも `InvalidInputError`。

- `VibrationalMode(frequency, huang_rhys)` — 正準表現の 1 モード
- `Broadening(sigma, gamma=0.0)` — 線形状。σ ≥ 0, γ ≥ 0 かつ少なくとも一方 > 0
- `EnergyGrid(e_min, e_max, de)` — 出力グリッド。`e_min` < `e_max`, `de` > 0
- `Selection(min_weight=1e-4, max_lines=10000, max_quanta=None)` — 線の選択条件
- `ModeSpec(frequency, coupling)` — 入力ファイル中の 1 モード（流儀依存）

結果クラス（frozen dataclass）。

- `EnvelopeResult` — `energy` / `density` / 入力エコー（`modes` / `temperature` / `broadening` / `grid`）/ `reorganization_energy` / `diagnostics` / 来歴
- `EnvelopeDiagnostics` — `n_fft` / `d_tau` / `tau_max` / `damping_at_tau_max` / `total_area` / `window_captured_fraction` / `edge_density_ratio` / `max_imaginary_ratio` / `messages`
- `LinesResult` — `lines` / 入力エコー（`modes` / `temperature` / `selection`）/ `reorganization_energy` / `diagnostics` / 来歴。`energies` / `fc_factors` / `weights` で ndarray としても取れる
- `LinesDiagnostics` — `n_lines` / `captured_weight` / `mean_energy` / `min_mode_completeness` / `max_initial_quanta` / `max_final_quanta` / `beam_truncated` / `recurrence_limited` / `messages`
- `FCLine(energy, fc_factor, weight, transitions)` — 離散遷移 1 本
- `ModeTransition(mode_index, initial, final)` — 1 モードの n_α → m_α

`fcenvelope_version` と `created_at` は計算時に確定し、結果クラスが保持する。
保存時に付与しないため、`load → save` の往復でファイルは変化しない。

## 流儀と単位

`CouplingConvention` は変換式・単位の有無・振動数への依存の仕方を自分で知っている
オブジェクト（ADR-0033）。レジストリは `COUPLING_CONVENTIONS`（キーは入力に書く名前）。

| `coupling_convention` | 記号 | S への変換 | `coupling_unit()` |
|---|---|---|---|
| `"g"` | g | S = g² | None（無次元） |
| `"delta"` | Δ | S = Δ²/2 | None |
| `"huang_rhys"` | S | 恒等 | None |
| `"vcc"` | V | S = V²/(2ω³) | `(cm^-1)^3/2` |
| `"lambda"` | λ | S = λ/ω | `cm^-1` |

```python
convention.to_huang_rhys(coupling, frequency) -> float
convention.coupling_unit(frequency_unit="cm^-1") -> str | None
convention.is_dimensionless -> bool
```

## ファイル形式

### 入力（`schema_version` = 2）

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

| フィールド | 型 | 制約 | 意味 |
|---|---|---|---|
| `schema_version` | int | `2` 固定 | 不一致は `SchemaVersionError`（v1 の互換層は置かない） |
| `frequency_unit` | str | `"cm^-1"` 固定 | 他は `UnsupportedUnitError` |
| `coupling_convention` | str | 上表の 5 つ | 既定 `"g"` |
| `modes[].frequency` | float | > 0 | ε_α [cm⁻¹] |
| `modes[].coupling` | float | ≥ 0 | convention に従う値 |
| `temperature` | float | ≥ 0 | T [K]。0 は許可（n_α = 0） |
| `broadening.sigma` | float | ≥ 0 | σ [cm⁻¹] |
| `broadening.gamma` | float | ≥ 0 | γ [cm⁻¹]。既定 0.0。σ と両方 0 は不可 |
| `grid.e_min` / `e_max` | float | `e_min` < `e_max` | 出力窓 [cm⁻¹] |
| `grid.de` | float | > 0 | 出力グリッド間隔 [cm⁻¹] |
| `selection.min_weight` | float | 0 < x ≤ 1 | 既定 1e-4 |
| `selection.max_lines` | int | ≥ 1 | 既定 10000 |
| `selection.max_quanta` | int \| null | ≥ 0 | 既定 null（自動） |

`run` は `temperature` / `broadening` / `grid` を、`lines` は `temperature` / `selection` を
読み、互いに相手の節を無視する。`selection` の節は省略でき、その場合 `Selection()` の
既定値になる。`modes` は最低 1 要素で、配列の代わりに `{"path": "<file>.csv"}` を置くと
外部 CSV を参照する（相対パスは入力 JSON のディレクトリ基準）。CSV は RFC 4180 準拠で、
列は `frequency` / `coupling` の 2 列のみ。ヘッダは省略可（省略時はこの順、ヘッダが
あれば順序自由）。コメント行・空行・補助列は受け付けない。

### 出力

2 系統は同じ骨格を持ち、違うのは末尾のペイロードだけである。

```
schema_version / kind / fcenvelope_version / created_at / 単位
input { frequency_unit, coupling_convention, modes, temperature, ... }
derived { reorganization_energy }
diagnostics { ..., messages }
＋ ペイロード
```

エンベロープは単位に `density_unit` を加え、`input` に `broadening` と `grid` を持ち、
ペイロードは `spectrum`（`energy` / `density`）。

```json
{
  "schema_version": 2,
  "kind": "fcenvelope.envelope",
  "fcenvelope_version": "0.1.0",
  "created_at": "2026-09-16T03:21:44Z",
  "energy_unit": "cm^-1",
  "density_unit": "1/cm^-1",
  "input": {
    "frequency_unit": "cm^-1",
    "coupling_convention": "huang_rhys",
    "modes": [{ "frequency": 1200.0, "coupling": 0.25 }],
    "temperature": 300.0,
    "broadening": { "sigma": 150.0, "gamma": 0.0 },
    "grid": { "e_min": -4000.0, "e_max": 1000.0, "de": 5.0 }
  },
  "derived": { "reorganization_energy": 300.0 },
  "diagnostics": {
    "n_fft": 2048, "d_tau": 6.13e-4, "tau_max": 0.628,
    "damping_at_tau_max": 0.0, "total_area": 1.0,
    "window_captured_fraction": 0.9993,
    "edge_density_ratio": 1.7e-5,
    "max_imaginary_ratio": 1.1e-16,
    "messages": []
  },
  "spectrum": {
    "energy": [-4000.0, -3995.0, "..."],
    "density": [1.2e-9, 1.4e-9, "..."]
  }
}
```

離散 FC 因子はペイロードが `selection` と `lines`。

```json
{
  "schema_version": 2,
  "kind": "fcenvelope.fc_lines",
  "fcenvelope_version": "0.1.0",
  "created_at": "2026-09-16T01:23:45Z",
  "energy_unit": "cm^-1",
  "input": {
    "frequency_unit": "cm^-1",
    "coupling_convention": "huang_rhys",
    "modes": [{ "frequency": 1200.0, "coupling": 0.25 }],
    "temperature": 300.0
  },
  "derived": { "reorganization_energy": 300.0 },
  "diagnostics": { "n_lines": 58, "captured_weight": 0.997, "...": "..." },
  "selection": { "min_weight": 0.0001, "max_lines": 10000, "max_quanta": null },
  "lines": [
    { "energy": 0.0, "fc_factor": 0.41, "weight": 0.36, "transitions": [] },
    { "energy": -450.0, "fc_factor": 0.26, "weight": 0.23,
      "transitions": [{ "mode": 1, "initial": 0, "final": 1 }] }
  ]
}
```

どちらの出力も入力エコーは常に正準形（`coupling_convention` = `"huang_rhys"`）で、
それ以外は読み込み時に reject する。`selection` は丸ごとエコーされるため、
`max_quanta` を含めて結果ファイルだけから計算を再現できる（ADR-0035）。

## CLI

```
fcenvelope run INPUT.json -o RESULT.json [--plot FIG.png] [--dpi INT]
                          [--temperature FLOAT] [--sigma FLOAT] [--gamma FLOAT]
                          [--e-min FLOAT] [--e-max FLOAT] [--de FLOAT]

fcenvelope lines INPUT.json -o LINES.json [--plot FIG.png] [--dpi INT]
                          [--temperature FLOAT] [--min-weight FLOAT]
                          [--max-lines INT] [--max-quanta INT] [--show INT]

fcenvelope plot RESULT.json [LINES.json] -o FIG.png [--title TEXT] [--dpi INT]
                          [--magnify FLOAT]
```

上書きできるのは `temperature` / `broadening` / `grid` / `selection` のフィールドのみで、
`modes` は上書きしない（ADR-0012 / ADR-0035）。指定しなかったつまみは入力ファイルの値の
ままになる。`lines` は同じ入力 JSON を使い、`broadening` と `grid` は読まない。
`plot` は `kind` を見てエンベロープと棒スペクトルのどちらかを描く。ファイルを 2 つ
（エンベロープ 1 つと線リスト 1 つ、順序は任意）渡すと重ね描きになり、`--magnify` が
効く。種類の組み合わせが違えば使用法エラー。
終了コード: `0` 正常 / `1` `FCEnvelopeError` / `2` 使用法エラー。

## 例外・警告

```
FCEnvelopeError
├── InvalidInputError
├── UnsupportedUnitError
└── SchemaVersionError

NumericalQualityWarning(UserWarning)
```

計算は常に完走し、品質は `EnvelopeDiagnostics` / `LinesDiagnostics` に記録される。閾値を
超えた項目は `NumericalQualityWarning` として発報され、同じ文言が `messages` に残る。

## 線形状

線形状は時間領域では ρ(τ) に掛かる実数の減衰因子にすぎず、(σ, γ) の 2 パラメータを持つ
1 つの族である（ADR-0034）。型階層は作らない。

    D(τ) = exp(−σ²τ²/2 − γ|τ|)

σ だけならガウス、γ だけならローレンツ、両方あれば Voigt。頂点値は
`fcenvelope.physics.lineshape_peak(sigma, gamma)` が与える。

    V(0; σ, γ) = Re[w(i·a)] / (σ√(2π)),   a = γ / (σ√2)

σ → 0 では 1/(πγ)、γ → 0 では 1/(σ√(2π)) に帰着する。

τ 窓の打ち切りは減衰因子そのもので診断する（ADR-0038）。健全な計算では
`damping_at_tau_max` はアンダーフローして 0.0 になる。閾値 e⁻¹⁸ ≈ 1.523e-8 を
超えると警告が出る。

## E グリッドの構成

`e_min` / `e_max` / `de` は明示指定（省略値・自動推定なし）。内部では 0 対称な
全域グリッド上で FFT し、最後に窓へ切り出す。

1. `E_h = max(|e_min|, |e_max|)`
2. `N = next_pow2(ceil(2 E_h / de))`
3. `Δτ = 2π / (N de)`、`τ_max = π / de`
4. 計算後に `e_min ≤ E ≤ e_max` を切り出し

出力の ΔE は指定した `de` ちょうどで、E = 0 は必ずグリッド点に乗る。
一方、出力の端点は `de` の整数倍にスナップされる。

## 離散 FC 因子の打ち切り

`min_weight` 以上の線をすべて返す。1 モードあたりの寄与 P(n)·FC_mn は 1 以下で、
完成した線の重みは途中経過の積を超えないため、モードを 1 つずつ合成しながら
閾値で枝刈りしても取りこぼさない。`max_lines` を超えた場合のみ重みの上位を残して
打ち切り、`beam_truncated` を立てる。

振動梯子の長さは打ち切り残差が `min_weight` を下回るまで自動で伸ばす
（`max_quanta` で上限指定可）。g と n がともに大きい領域では漸化式が桁落ちで
破綻するため、列和 Σ_m FC_mn が 1 を上回った時点で n を打ち切り、
`recurrence_limited` を立てる（梯子の打ち切りは列和が 1 を下回るので区別できる）。

## モジュール依存

```
errors → units → models → physics → result → { envelope, lines } → { io, plotting } → cli
```

一方通行。`envelope` と `lines` は互いを見ない対等な兄弟であり、共有する物理は
`physics` にある（ADR-0041）。matplotlib は `plotting.py`、typer は `cli.py` に
閉じ込める。
