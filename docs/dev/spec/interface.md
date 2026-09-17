# インターフェイス仕様

変更が行われにくい部分のみを簡潔に記す。詳細は実際のコード（`src/fcenvelope/`）を本体とする。
語の定義は `CONTEXT.md`、設計の背景・判断理由は `docs/adr/` の各 ADR を参照。

スペクトルには 2 つの表現があり、それぞれに「計算・保存・読み込み・描画」の 4 関数を持つ。

| 表現 | 関数 | 結果クラス | 出力 `kind` |
|---|---|---|---|
| エンベロープ F(E) | `compute_envelope` 系 | `EnvelopeResult` | `fcenvelope.envelope` |
| 線 | `compute_fc_lines` 系 | `LinesResult` | `fcenvelope.fc_lines` |

## 単位・規約

| 項目 | 値 |
|---|---|
| エネルギー | cm⁻¹（入力・内部・出力すべて） |
| τ | cm |
| 温度 | K |
| 結合の内部正準量 | S（Huang-Rhys 因子） |
| 密度の単位 | 1/cm⁻¹（∫F dE = 1） |
| 重みの単位 | 無次元（全遷移にわたる総和 = 1） |
| 重ね描きでの棒の高さ | w·L(0)、ガウス型なら w/(σ√(2π))。単位は密度と同じ 1/cm⁻¹ |
| E 軸 | E = 0 が ZPL。k 量子生成のサイドバンドは E = −k·ε（負側） |

単位は結果クラスではなく `io`（ファイル形式）と `plotting`（軸ラベル）が持つ（ADR-0047）。

## 公開 API

`fcenvelope` トップレベルから公開する自由関数。

```python
# エンベロープ F(E)
compute_envelope(system: VibrationalSystem, *, temperature: float,
                 broadening: Broadening, grid: EnergyGrid) -> EnvelopeResult
save_envelope(result: EnvelopeResult, path: str | Path) -> None
load_envelope(path: str | Path) -> EnvelopeResult
plot_envelope(result, *, ax=None, label=None, title=None) -> matplotlib.figure.Figure

# 線
compute_fc_lines(system: VibrationalSystem, *, temperature: float,
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

両系統とも「共通の物理条件（`temperature`）＋自分に固有の数値条件（`grid` / `selection`）」
という同じ形をしている（ADR-0035）。結果クラスは純粋なデータ容器で、I/O と描画の責務を
持たない（ADR-0011）。描画関数は `Figure` を返すのみでファイル保存はしない。

入力ファイルの読み込みは `FCEnvelopeInput` を経由する。

```python
FCEnvelopeInput.from_path(path)                   -> FCEnvelopeInput   # modes.path はファイル基準
FCEnvelopeInput.from_json(text, *, base_dir=None) -> FCEnvelopeInput
FCEnvelopeInput.from_obj(data, *, base_dir=None)  -> FCEnvelopeInput   # base_dir 省略時は cwd 基準

FCEnvelopeInput.to_system()      -> VibrationalSystem   # 単位と流儀を消費して正準化
FCEnvelopeInput.to_temperature() -> float
FCEnvelopeInput.to_broadening()  -> Broadening
FCEnvelopeInput.to_grid()        -> EnergyGrid
FCEnvelopeInput.to_selection()   -> Selection
```

## データモデル

### 計算用の値（`models.py`、frozen dataclass、pydantic に依存しない）

- `VibrationalMode(frequency, huang_rhys)` — 正準形の振動モード
- `VibrationalSystem(modes)` — 系。`.frequencies` / `.huang_rhys` / `.reorganization_energy` /
  `.occupations(temperature)` を持つ（ADR-0044）
- `Broadening(sigma)` — 線形状。`.log_damping(tau)` / `.peak_height()` /
  `.truncation_indicator(tau_max)` / `MIN_TRUNCATION_INDICATOR` を持つ（ADR-0034）
- `EnergyGrid(e_min, e_max, de)` — エネルギーグリッド
- `Selection(min_weight=1e-4, max_lines=10000, max_quanta=None)` — 選択条件。**つまみの
  既定値はここにしかない**（ADR-0050）

どの型も `__post_init__` で自分の不変条件を検証し、違反は `InvalidInputError`（ADR-0051）。
`temperature` はどの型にも属さないので `models.validate_temperature` が唯一の置き場になる。

### 入力ファイルの型（`inputs.py`、pydantic）

- `FCEnvelopeInput` — 入力ファイル全体。構造・単位・流儀だけを検査する
- `ModeSpec(frequency, coupling)` / `BroadeningSpec` / `EnergyGridSpec` / `SelectionSpec`

範囲の検査は値の型に任せ、値の型が送出したエラーにフィールドの位置（`modes[1]`、`grid` など）
を添える（ADR-0045, 0051）。

### 単位と流儀（`units.py`）

- `CouplingConvention(name, energy_power, converter)` — 流儀。`.to_huang_rhys(coupling,
  frequency)` / `.is_dimensionless` / `.check_coupling_unit(unit)`（ADR-0033）
- `G` / `HUANG_RHYS` と `COUPLING_CONVENTIONS`（名前 → 流儀）
- `check_frequency_unit(unit)` / `CANONICAL_FREQUENCY_UNIT`

`energy_power` は coupling の次元をエネルギーのべきで表したもの。無次元の流儀は `None`。
V（1.5）と λ（1.0）は**まだ登録していない**が、型はこれらを表現できる。

### 結果（`result.py`、frozen dataclass）

- `Provenance(fcenvelope_version, created_at)` — 来歴（ADR-0046）
- `EnvelopeResult(system, temperature, broadening, grid, energy, density, diagnostics, provenance)`
- `LinesResult(system, temperature, selection, lines, diagnostics, provenance)`
- `FCLine(energy, fc_factor, weight, transitions)`
- `ModeTransition(mode_index, initial, final)` — 1 モードの n_α → m_α
- `Diagnostics` / `FCLineDiagnostics` — 数値品質の診断値

結果クラスが持つのは**計算で決まったものだけ**である（ADR-0047）。λ は
`system.reorganization_energy` から得る。`LinesResult` は `.energies` / `.fc_factors` /
`.weights` を ndarray として返す。

## ファイル形式

### 入力

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
  "broadening": { "sigma": 150.0 },
  "grid": { "e_min": -4000.0, "e_max": 1000.0, "de": 5.0 },
  "selection": { "min_weight": 0.0001, "max_lines": 10000, "max_quanta": null }
}
```

| フィールド | 型 | 制約 | 意味 |
|---|---|---|---|
| `schema_version` | int | `2` 固定 | 不一致は `SchemaVersionError`。1 の互換層は置かない（ADR-0040） |
| `frequency_unit` | str | `"cm^-1"` 固定 | 他は `UnsupportedUnitError` |
| `coupling_convention` | str | `"g"` \| `"huang_rhys"` | 既定 `"g"` |
| `modes[].frequency` | float | > 0 | ε_α [cm⁻¹] |
| `modes[].coupling` | float | 流儀による | 流儀に従った値 |
| `temperature` | float | ≥ 0 | T [K]。0 は許可（n_α = 0） |
| `broadening.sigma` | float | > 0 | σ [cm⁻¹] |
| `grid.e_min` / `e_max` | float | `e_min` < `e_max` | 出力窓 [cm⁻¹] |
| `grid.de` | float | > 0 | 出力グリッド間隔 [cm⁻¹] |
| `selection` | object | 省略可 | 省略時は `Selection` の既定値 |

`modes` は最低 1 要素。配列の代わりに `{"path": "<file>.csv"}` を置くと外部 CSV を参照する
（相対パスは入力 JSON のディレクトリ基準）。CSV は RFC 4180 準拠で、列は `frequency` /
`coupling` の 2 列のみ。ヘッダは省略可（省略時はこの順、ヘッダがあれば順序自由）。
コメント行・空行・補助列は受け付けない。CSV が報告するのは**構造の誤りだけ**で、行番号が
付くのもそこまでである。値の範囲は正準化のときに値の型が見るので、位置はモードの番号になる。

`run` は `temperature` / `broadening` / `grid` を、`lines` は `temperature` / `selection` を
読む。どちらの副命令も同じファイルを使える（ADR-0005）。

### 出力（エンベロープ）

```json
{
  "schema_version": 2,
  "kind": "fcenvelope.envelope",
  "fcenvelope_version": "0.1.0",
  "created_at": "2026-09-17T03:21:44Z",
  "energy_unit": "cm^-1",
  "density_unit": "1/cm^-1",
  "input": {
    "frequency_unit": "cm^-1",
    "coupling_convention": "huang_rhys",
    "modes": [{ "frequency": 1200.0, "coupling": 0.25 }],
    "temperature": 300.0,
    "broadening": { "sigma": 150.0 },
    "grid": { "e_min": -4000.0, "e_max": 1000.0, "de": 5.0 }
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
    "density": [1.2e-9, 1.4e-9, "..."]
  }
}
```

### 出力（線）

```json
{
  "schema_version": 2,
  "kind": "fcenvelope.fc_lines",
  "fcenvelope_version": "0.1.0",
  "created_at": "2026-09-17T01:23:45Z",
  "energy_unit": "cm^-1",
  "input": {
    "frequency_unit": "cm^-1",
    "coupling_convention": "huang_rhys",
    "modes": [{ "frequency": 1200.0, "coupling": 0.25 }],
    "temperature": 300.0,
    "selection": { "min_weight": 0.0001, "max_lines": 10000, "max_quanta": null }
  },
  "derived": { "reorganization_energy": 300.0 },
  "diagnostics": { "n_lines": 58, "captured_weight": 0.997, "...": "..." },
  "lines": [
    { "energy": 0.0, "fc_factor": 0.41, "weight": 0.36, "transitions": [] },
    { "energy": -450.0, "fc_factor": 0.26, "weight": 0.23,
      "transitions": [{ "mode": 1, "initial": 0, "final": 1 }] }
  ]
}
```

どちらの出力も入力エコーは常に正準形（`coupling_convention` = `"huang_rhys"`）で、それ以外は
読み込み時に reject する。`derived` は系から一意に決まる控えなので、書き出しはするが読み込み
時は読み飛ばす（ADR-0047）。`load → save` でファイルは変化しない（ADR-0008）。

入力ファイルと結果ファイルは同じ `schema_version` を共有するが、`io` は `inputs` に依存しない
ため（ADR-0041）定数は別に持ち、一致はテストで確かめる。

## CLI

```
fcenvelope run INPUT.json -o RESULT.json [--plot FIG.png] [--dpi INT]
                          [--temperature FLOAT] [--sigma FLOAT]
                          [--e-min FLOAT] [--e-max FLOAT] [--de FLOAT]

fcenvelope lines INPUT.json -o LINES.json [--plot FIG.png] [--dpi INT]
                          [--temperature FLOAT] [--min-weight FLOAT]
                          [--max-lines INT] [--max-quanta INT] [--show INT]

fcenvelope plot RESULT.json [LINES.json] -o FIG.png [--title TEXT] [--dpi INT]
                          [--magnify FLOAT]
```

上書きできるのは `temperature` / `broadening` / `grid` / `selection` で、`modes` は上書き
しない（ADR-0012, 0035）。上書きの値は**入力ファイルと同じ単位・流儀で読み**、入力ファイルの
型に適用してから正準化する（ADR-0050）。上書き系オプションの既定値はすべて「上書きしない」
という意味の `None` で、つまみの既定値は `Selection` の 1 箇所にしかない。

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
発報と記録の手順は `errors.report_quality` にまとめ、**メッセージ本文は各系統が手書きで
持つ**（ADR-0036, 0048）。

## E グリッドの構成

`e_min` / `e_max` / `de` は明示指定（省略値・自動推定なし）。内部では 0 対称な
全域グリッド上で FFT し、最後に窓へ切り出す。

1. `E_h = max(|e_min|, |e_max|)`
2. `N = next_pow2(ceil(2 E_h / de))`
3. `Δτ = 2π / (N de)`、`τ_max = π / de`
4. 計算後に `e_min ≤ E ≤ e_max` を切り出し

出力の ΔE は指定した `de` ちょうどで、E = 0 は必ずグリッド点に乗る。
一方、出力の端点は `de` の整数倍にスナップされる。

## 線の打ち切り

`min_weight` 以上の線をすべて返す。1 モードあたりの寄与 P(n)·FC_mn は 1 以下で、
完成した線の重みは途中経過の積を超えないため、モードを 1 つずつ合成しながら
閾値で枝刈りしても取りこぼさない。`max_lines` を超えた場合のみ重みの上位を残して
打ち切り、`beam_truncated` を立てる。

振動梯子の長さは打ち切り残差が `min_weight` を下回るまで自動で伸ばす
（`max_quanta` で上限指定可）。g と n がともに大きい領域では漸化式が桁落ちで
破綻するため、列和 Σ_m FC_mn が 1 を上回った時点で n を打ち切り、
`recurrence_limited` を立てる（梯子の打ち切りは列和が 1 を下回るので区別できる）。

## モジュール依存

| モジュール | 責務 | 依存先 |
|---|---|---|
| `errors.py` | 例外・警告、`report_quality` | — |
| `physics.py` | `K_B_CM`、占有数 n_α、梯子 P(n)。配列と数値だけを扱う | — |
| `models.py` | 計算用の値の型 | errors, physics |
| `units.py` | 流儀オブジェクト、単位の検証と変換 | errors |
| `inputs.py` | 入力ファイルの型（pydantic）と正準化 | errors, units, models |
| `result.py` | 結果クラス、`Provenance` | models |
| `envelope.py` | グリッド構成・FFT | errors, models, result |
| `lines.py` | 漸化式・線の列挙 | errors, models, physics, result |
| `io.py` | 保存・読み込み、`kind` の表 | errors, models, result |
| `plotting.py` | 描画、結果の型の表 | errors, result |
| `cli.py` | typer アプリ | 上記すべて |

`envelope.py` と `lines.py` は互いに依存しない。`io.py` は `inputs.py` に依存しない
（ADR-0041）。matplotlib は `plotting.py`、typer は `cli.py`、pydantic は `inputs.py` に
閉じ込める。

種類による振り分けは関心ごとの表に置く（ADR-0049）。

| モジュール | 表 |
|---|---|
| `io.py` | `RESULT_KINDS`: `kind` → 保存・読み込み・単位 |
| `plotting.py` | `DRAWERS`: 結果の型 → 描画 |
| `cli.py` | `REPORTERS`: 結果の型 → 報告 |

重ね描きは表に載せず専用の関数のままにする。すべての表が同じ種類を網羅していることは
`test/test_dispatch.py` で確かめる。
