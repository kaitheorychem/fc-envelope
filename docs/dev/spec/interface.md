# インターフェイス仕様

変更が行われにくい部分のみを簡潔に記す。詳細は実際のコード（`src/fcenvelope/`）を本体とする。
設計の背景・判断理由は `docs/dev/agreement/io-and-class-design-20260725.md` と
`docs/dev/agreement/modes-csv-20260915.md` を参照。

## 単位・規約

| 項目 | 値 |
|---|---|
| エネルギー | cm⁻¹（入力・内部・出力すべて） |
| τ | cm |
| 温度 | K |
| 振電相互作用の内部正準量 | S（Huang-Rhys 因子） |
| F(E) の単位 | 1/cm⁻¹（∫F dE = 1） |
| E 軸 | E = 0 が ZPL。k 量子生成のサイドバンドは E = −k·ε（負側） |

## 公開 API

`fcenvelope` トップレベルから公開する自由関数 4 つ。

```python
compute_envelope(modes: Sequence[VibrationalMode], conditions: Conditions) -> FCEnvelopeResult
save_result(result: FCEnvelopeResult, path: str | Path) -> None
load_result(path: str | Path) -> FCEnvelopeResult
plot_result(result, *, ax=None, label=None, title=None) -> matplotlib.figure.Figure
```

結果クラスは純粋なデータ容器で、I/O と描画の責務を持たない。
`plot_result` は `Figure` を返すのみでファイル保存はしない。

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
- `Diagnostics` — 数値品質の診断値（frozen dataclass）

`fcenvelope_version` と `created_at` は計算時に確定し、結果クラスが保持する。
保存時に付与しないため、`load → save` の往復でファイルは変化しない。

## ファイル形式

- 入力: `schema_version` = 1、`frequency_unit` = `"cm^-1"`、`coupling_convention` ∈ {`"g"`, `"huang_rhys"`}、`modes`（1 件以上）、`conditions`
- `modes` は配列か `{"path": "<file>.csv"}`。CSV は RFC 4180 準拠で、列は `frequency` / `coupling` の 2 列のみ。ヘッダは省略可（省略時はこの順、ヘッダがあれば順序自由）。コメント行・空行なし
- 出力: `kind` = `"fcenvelope.result"` の単一 JSON。入力エコーは常に正準形（`coupling_convention` = `"huang_rhys"`）
- 両者の詳細スキーマは合意文書 §4.2 / §8.2

## CLI

```
fcenvelope run INPUT.json -o RESULT.json [--plot FIG.png] [--dpi INT]
                          [--temperature FLOAT] [--sigma FLOAT]
                          [--e-min FLOAT] [--e-max FLOAT] [--de FLOAT]

fcenvelope plot RESULT.json -o FIG.png [--title TEXT] [--dpi INT]
```

上書きできるのは `conditions` の 5 フィールドのみ。`modes` は上書きしない。
終了コード: `0` 正常 / `1` `FCEnvelopeError` / `2` 使用法エラー。

## 例外・警告

```
FCEnvelopeError
├── InvalidInputError
├── UnsupportedUnitError
└── SchemaVersionError

NumericalQualityWarning(UserWarning)
```

計算は常に完走し、品質は `Diagnostics` に記録される。閾値を超えた項目は
`NumericalQualityWarning` として発報され、同じ文言が `Diagnostics.messages` に残る。

## E グリッドの構成

`e_min` / `e_max` / `de` は明示指定（省略値・自動推定なし）。内部では 0 対称な
全域グリッド上で FFT し、最後に窓へ切り出す。

1. `E_h = max(|e_min|, |e_max|)`
2. `N = next_pow2(ceil(2 E_h / de))`
3. `Δτ = 2π / (N de)`、`τ_max = π / de`
4. 計算後に `e_min ≤ E ≤ e_max` を切り出し

出力の ΔE は指定した `de` ちょうどで、E = 0 は必ずグリッド点に乗る。
一方、出力の端点は `de` の整数倍にスナップされる。

## モジュール依存

`errors → models → result → core → {io, plotting} → cli` の一方通行。
matplotlib は `plotting.py`、typer は `cli.py` に閉じ込める。
