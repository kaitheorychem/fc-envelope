# インターフェイス仕様

変更が行われにくい部分のみを簡潔に記す。詳細は実際のコード（`src/fcenvelope/`）を本体とする。
設計の背景・判断理由は `docs/adr/` の各 ADR を参照。

スペクトルには 2 つの表現があり、それぞれに「計算・保存・読み込み・描画」の 4 関数を持つ。

| 表現 | 関数 | 結果クラス | 出力 `kind` |
|---|---|---|---|
| エンベロープ F(E) | `compute_envelope` 系 | `FCEnvelopeResult` | `fcenvelope.result` |
| 離散 FC 因子 | `compute_fc_lines` 系 | `FCLinesResult` | `fcenvelope.fc_lines` |

## 単位・規約

| 項目 | 値 |
|---|---|
| エネルギー | cm⁻¹（入力・内部・出力すべて） |
| τ | cm |
| 温度 | K |
| 振電相互作用の内部正準量 | S（Huang-Rhys 因子） |
| F(E) の単位 | 1/cm⁻¹（∫F dE = 1） |
| 線強度の単位 | 無次元（全遷移にわたる総和 = 1） |
| 重ね描きでの棒の高さ | I·G_σ(0) = I/(σ√(2π))、単位は F(E) と同じ 1/cm⁻¹ |
| E 軸 | E = 0 が ZPL。k 量子生成のサイドバンドは E = −k·ε（負側） |

## 公開 API

`fcenvelope` トップレベルから公開する自由関数。

```python
# エンベロープ F(E)
compute_envelope(modes: Sequence[VibrationalMode], conditions: Conditions) -> FCEnvelopeResult
save_result(result: FCEnvelopeResult, path: str | Path) -> None
load_result(path: str | Path) -> FCEnvelopeResult
plot_result(result, *, ax=None, label=None, title=None) -> matplotlib.figure.Figure

# 離散 FC 因子
compute_fc_lines(modes, *, temperature, min_intensity=1e-4,
                 max_lines=10000, max_quanta=None) -> FCLinesResult
save_fc_lines(result: FCLinesResult, path: str | Path) -> None
load_fc_lines(path: str | Path) -> FCLinesResult
plot_fc_lines(result, *, ax=None, label=None, title=None) -> matplotlib.figure.Figure

# 理論式そのもの: FC_mn = |<m|U(sqrt(S))|n>|^2 を (m_max+1, n_max+1) で返す
fc_factor_matrix(huang_rhys: float, m_max: int, n_max: int = 0) -> np.ndarray

# 2 つの表現を 1 枚に重ねる
plot_overlay(envelope: FCEnvelopeResult, lines: FCLinesResult, *, ax=None,
             envelope_label="envelope", lines_label="FC lines",
             magnify=1.0, title=None) -> matplotlib.figure.Figure
```

結果クラスは純粋なデータ容器で、I/O と描画の責務を持たない。
`plot_result` / `plot_fc_lines` / `plot_overlay` は `Figure` を返すのみでファイル保存はしない。
`compute_fc_lines` は `Conditions` を取らない（離散線に必要なのは温度だけ）。

入力ファイルの読み込みは `FCEnvelopeInput` を経由する。

```python
FCEnvelopeInput.from_path(path)                  -> FCEnvelopeInput   # modes.path はファイル基準
FCEnvelopeInput.from_json(text, *, base_dir=None) -> FCEnvelopeInput
FCEnvelopeInput.from_obj(data, *, base_dir=None)  -> FCEnvelopeInput   # base_dir 省略時は cwd 基準
FCEnvelopeInput.to_modes()      -> list[VibrationalMode]   # 流儀を消費して正準化
```

## データモデル

- `VibrationalMode(frequency, huang_rhys)` — 正準表現（frozen, pydantic）
- `Conditions(temperature, sigma, e_min, e_max, de)` — 計算条件（frozen, pydantic）
- `ModeSpec(frequency, coupling)` — 入力ファイル中の 1 モード（流儀依存）
- `FCEnvelopeResult` — `energy` / `intensity` / 入力エコー / `reorganization_energy` / `diagnostics` / 来歴（frozen dataclass）
- `Diagnostics` — エンベロープの数値品質の診断値（frozen dataclass）
- `ModeTransition(mode_index, initial, final)` — 1 モードの n_α → m_α（frozen dataclass）
- `FCLine(energy, fc_factor, intensity, transitions)` — 離散遷移 1 本（frozen dataclass）
- `FCLinesResult` — `lines` / 入力エコー / `temperature` / 選択条件 / `reorganization_energy` / `diagnostics` / 来歴（frozen dataclass）
- `FCLineDiagnostics` — 離散 FC 因子の数値品質の診断値（frozen dataclass）

`fcenvelope_version` と `created_at` は計算時に確定し、結果クラスが保持する。
保存時に付与しないため、`load → save` の往復でファイルは変化しない。

## ファイル形式

### 入力

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

| フィールド | 型 | 制約 | 意味 |
|---|---|---|---|
| `schema_version` | int | `1` 固定 | 不一致は `SchemaVersionError` |
| `frequency_unit` | str | `"cm^-1"` 固定 | 他は `UnsupportedUnitError` |
| `coupling_convention` | str | `"g"` \| `"huang_rhys"` | 既定 `"g"` |
| `modes[].frequency` | float | > 0 | ε_α [cm⁻¹] |
| `modes[].coupling` | float | ≥ 0 | convention に従う値 |
| `conditions.temperature` | float | ≥ 0 | T [K]。0 は許可（n_α = 0） |
| `conditions.sigma` | float | > 0 | σ [cm⁻¹] |
| `conditions.e_min` | float | < `e_max` | 出力窓の下端 [cm⁻¹] |
| `conditions.e_max` | float | > `e_min` | 出力窓の上端 [cm⁻¹] |
| `conditions.de` | float | > 0 | 出力グリッド間隔 [cm⁻¹] |

`modes` は最低 1 要素。配列の代わりに `{"path": "<file>.csv"}` を置くと外部 CSV を参照する
（相対パスは入力 JSON のディレクトリ基準）。CSV は RFC 4180 準拠で、列は `frequency` /
`coupling` の 2 列のみ。ヘッダは省略可（省略時はこの順、ヘッダがあれば順序自由）。
コメント行・空行・補助列は受け付けない。

### 出力（エンベロープ）

```json
{
  "schema_version": 1,
  "kind": "fcenvelope.result",
  "fcenvelope_version": "0.1.0",
  "created_at": "2026-07-25T03:21:44Z",
  "energy_unit": "cm^-1",
  "intensity_unit": "1/cm^-1",
  "input": {
    "frequency_unit": "cm^-1",
    "coupling_convention": "huang_rhys",
    "modes": [{ "frequency": 1200.0, "coupling": 0.25 }],
    "conditions": {
      "temperature": 300.0, "sigma": 150.0,
      "e_min": -4000.0, "e_max": 1000.0, "de": 5.0
    }
  },
  "derived": { "reorganization_energy": 300.0 },
  "diagnostics": {
    "n_fft": 2048, "d_tau": 6.13e-4, "tau_max": 0.628,
    "sigma_tau_max": 94.2, "total_area": 0.9999999998,
    "window_captured_fraction": 0.9993,
    "edge_intensity_ratio": 3.1e-12,
    "max_imaginary_ratio": 8.4e-17,
    "messages": []
  },
  "spectrum": {
    "energy": [-4000.0, -3995.0, "..."],
    "intensity": [1.2e-9, 1.4e-9, "..."]
  }
}
```

### 出力（離散 FC 因子）

```json
{
  "schema_version": 1,
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
  "selection": { "min_intensity": 0.0001, "max_lines": 10000 },
  "derived": { "reorganization_energy": 300.0 },
  "diagnostics": { "n_lines": 58, "captured_intensity": 0.997, "...": "..." },
  "lines": [
    { "energy": 0.0, "fc_factor": 0.41, "intensity": 0.36, "transitions": [] },
    { "energy": -450.0, "fc_factor": 0.26, "intensity": 0.23,
      "transitions": [{ "mode": 1, "initial": 0, "final": 1 }] }
  ]
}
```

`conditions` ではなく `temperature` だけをエコーする。どちらの出力も入力エコーは常に
正準形（`coupling_convention` = `"huang_rhys"`）で、それ以外は読み込み時に reject する。

## CLI

```
fcenvelope run INPUT.json -o RESULT.json [--plot FIG.png] [--dpi INT]
                          [--temperature FLOAT] [--sigma FLOAT]
                          [--e-min FLOAT] [--e-max FLOAT] [--de FLOAT]

fcenvelope lines INPUT.json -o LINES.json [--plot FIG.png] [--dpi INT]
                          [--temperature FLOAT] [--min-intensity FLOAT]
                          [--max-lines INT] [--max-quanta INT] [--show INT]

fcenvelope plot RESULT.json [LINES.json] -o FIG.png [--title TEXT] [--dpi INT]
                          [--magnify FLOAT]
```

`run` が上書きできるのは `conditions` の 5 フィールドのみ。`modes` は上書きしない。
`lines` は同じ入力 JSON を使い、`conditions` のうち `temperature` だけを読む。
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

計算は常に完走し、品質は `Diagnostics` / `FCLineDiagnostics` に記録される。閾値を
超えた項目は `NumericalQualityWarning` として発報され、同じ文言が `messages` に残る。

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

`min_intensity` 以上の線をすべて返す。1 モードあたりの寄与 P(n)·FC_mn は 1 以下で、
完成した線の強度は途中経過の積を超えないため、モードを 1 つずつ合成しながら
閾値で枝刈りしても取りこぼさない。`max_lines` を超えた場合のみ強度上位を残して
打ち切り、`beam_truncated` を立てる。

振動梯子の長さは打ち切り残差が `min_intensity` を下回るまで自動で伸ばす
（`max_quanta` で上限指定可）。g と n がともに大きい領域では漸化式が桁落ちで
破綻するため、列和 Σ_m FC_mn が 1 を上回った時点で n を打ち切り、
`recurrence_limited` を立てる（梯子の打ち切りは列和が 1 を下回るので区別できる）。

## モジュール依存

`errors → models → result → core → fcfactor → {io, plotting} → cli` の一方通行。
matplotlib は `plotting.py`、typer は `cli.py` に閉じ込める。
