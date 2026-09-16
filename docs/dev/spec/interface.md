# インターフェイス仕様

変更が行われにくい部分のみを簡潔に記す。詳細は実際のコード（`src/fcenvelope/`）を本体とする。
設計の背景・判断理由は `docs/dev/agreement/io-and-class-design-20260725.md`、
`docs/dev/agreement/modes-csv-20260915.md`、`docs/dev/agreement/fc-factor-20260916.md`、
`docs/dev/agreement/overlay-plot-20260916.md` を参照。

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

- 入力: `schema_version` = 1、`frequency_unit` = `"cm^-1"`、`coupling_convention` ∈ {`"g"`, `"huang_rhys"`}、`modes`（1 件以上）、`conditions`
- `modes` は配列か `{"path": "<file>.csv"}`。CSV は RFC 4180 準拠で、列は `frequency` / `coupling` の 2 列のみ。ヘッダは省略可（省略時はこの順、ヘッダがあれば順序自由）。コメント行・空行なし
- 出力（エンベロープ）: `kind` = `"fcenvelope.result"` の単一 JSON
- 出力（離散 FC 因子）: `kind` = `"fcenvelope.fc_lines"` の単一 JSON。`conditions` ではなく `temperature` のみをエコーする
- どちらの出力も入力エコーは常に正準形（`coupling_convention` = `"huang_rhys"`）
- 詳細スキーマは `io-and-class-design-20260725.md` §4.2 / §8.2 と `fc-factor-20260916.md` §5.3

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
