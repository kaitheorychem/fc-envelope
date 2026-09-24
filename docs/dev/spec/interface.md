# インターフェイス仕様

変更が行われにくい部分のみを簡潔に記す。詳細は実際のコード（`src/fcenvelope/`）を本体とする。
語の定義は `CONTEXT.md`、設計の背景・判断理由は `docs/adr/` の各 ADR を参照。

スペクトルには 2 つの表現があり、それぞれに「計算・保存・読み込み・描画」の 4 関数を持つ。
図は CLI では描かない。計算に添えて**作図スクリプト**を生成し、それを走らせて作る
（ADR-0057, 0061）。

| 表現 | 関数 | 結果クラス | 出力 `kind` |
|---|---|---|---|
| エンベロープ F(E) | `compute_envelope` 系 | `EnvelopeResult` | `fcenvelope.envelope` |
| 線 | `compute_fc_lines` 系 | `LinesResult` | `fcenvelope.fc_lines` |

## 単位・規約

| 項目 | 値 |
|---|---|
| エネルギー | cm⁻¹（内部・出力）。入力は単位を書ける（下表）。読み込みの際に cm⁻¹ へ畳む |
| τ | cm |
| 温度 | K |
| 結合の内部正準量 | S（Huang-Rhys 因子） |
| 密度の単位 | 1/cm⁻¹（∫F dE = 1） |
| 重みの単位 | 無次元（全遷移にわたる総和 = 1） |
| 重ね描きでの棒の高さ | w·L(0)、ガウス型なら w/(σ√(2π))。単位は密度と同じ 1/cm⁻¹ |
| E 軸 | E = 0 が ZPL。k 量子生成のサイドバンドは E = −k·ε（負側） |

単位は結果クラスではなく `io`（ファイル形式）と `plotting`（軸ラベル）が持つ（ADR-0047）。

入力で受け付けるエネルギー単位は `cm^-1` / `eV` / `hartree` / `THz` / `kJ/mol` /
`kcal/mol`。波長（`nm`）は入れない（ADR-0054）。**単位の軸は項目ごとに独立**で、入力
ファイル全体で 1 つではない（ADR-0053）。既定の単位はそれを使うブロックが持ち、
トップレベルには置かない（ADR-0079）。

| 軸 | 何の単位か | 既定 |
|---|---|---|
| `modes.frequency_unit` | `modes.rows[].frequency`（CSV なら frequency の列） | `cm^-1` |
| `modes.coupling_unit` | `modes.rows[].coupling`。無次元の流儀では指定してはならない | 流儀による |
| `broadening.unit` | σ | `cm^-1` |
| `grid.unit` | `e_min` / `e_max` / `points.de` | `cm^-1` |

変換は入力ファイルの型（`inputs.py`）の中だけで起こる。`to_system()` / `to_broadening()`
/ `to_grid()` が単位と流儀を消費し、計算用の値の型には常に正準形が渡る（ADR-0054）。
描画の横軸はこの 4 つとは別の軸で、**作図スクリプトの `X_UNIT` / `X_SCALE` が持つ**
（ADR-0062）。`plotting.py` の軸ラベルは `cm^-1` 固定である。

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
という同じ形をしている（ADR-0035）。入力ファイルでも、固有のブロックはどちらも省略でき、
無いことを言うのはそれを読む `to_*` である（ADR-0075）。結果クラスは純粋なデータ容器で、I/O と描画の責務を
持たない（ADR-0011）。描画関数は `Figure` を返すのみでファイル保存はしない。

作図スクリプトの生成は `fcenvelope.emit`（トップレベルには出さない。種類で振り分ける
関数なので `io.save_any` / `plotting.plot_any` と同じ扱い）。

```python
emit.script_path_for(output: Path) -> Path      # result.json -> result_plot.py
emit.image_path_for(script: Path) -> Path       # result_plot.py -> fcenvelope-result.png
emit.write_script(result, data: Path, script: Path, *, force=False) -> bool
emit.write_overlay_script(envelope, envelope_path, lines, lines_path, script, *,
                          force=False) -> bool
```

戻り値は「書いたかどうか」で、生成先が既にあれば書かずに `False` を返す（ADR-0060）。

入力ファイルの読み込みは `FCEnvelopeInput` を経由する。

```python
FCEnvelopeInput.from_path(path)                   -> FCEnvelopeInput   # 書式は拡張子、modes.csv.path はファイル基準
FCEnvelopeInput.from_toml(text, *, base_dir=None) -> FCEnvelopeInput
FCEnvelopeInput.from_json(text, *, base_dir=None) -> FCEnvelopeInput
FCEnvelopeInput.from_obj(data, *, base_dir=None)  -> FCEnvelopeInput   # base_dir 省略時は cwd 基準

FCEnvelopeInput.to_system()      -> VibrationalSystem   # 単位と流儀を消費して正準化
FCEnvelopeInput.to_temperature() -> float
FCEnvelopeInput.to_broadening()  -> Broadening
FCEnvelopeInput.to_grid()        -> EnergyGrid
FCEnvelopeInput.to_selection()   -> Selection

FCEnvelopeInput.to_json()        -> str    # 実効設定。単位・流儀は入力ファイルのまま
FCEnvelopeInput.save(path)       -> None   # from_path で読み返せる形（ADR-0065）

INPUT_FORMATS: dict[str, Callable[[str], object]]   # 拡張子 -> テキストを辞書にする（ADR-0069）
```

## データモデル

### 計算用の値（`models.py`、frozen dataclass、pydantic に依存しない）

- `VibrationalMode(frequency, huang_rhys)` — 正準形の振動モード
- `VibrationalSystem(modes)` — 系。`.frequencies` / `.huang_rhys` / `.reorganization_energy` /
  `.occupations(temperature)` を持つ（ADR-0044）
- `Broadening(sigma)` — 線形状。`.log_damping(tau)` / `.peak_height()` /
  `.truncation_indicator(tau_max)` / `MIN_TRUNCATION_INDICATOR` を持つ（ADR-0034）
- `EnergyGrid(e_min, e_max, de, n_fft)` — エネルギーグリッド。持つのは**解決済み**の
  全域グリッドで、`from_points(e_min, e_max, n)` / `from_spacing(e_min, e_max, de, shift=0)`
  のどちらかで作る（ADR-0070）。`e_half` / `full_span` を導出として持つ
- `Selection(min_weight=1e-4, max_lines=10000, max_quanta=None)` — 選択条件。**つまみの
  既定値はここにしかない**（ADR-0050）

どの型も `__post_init__` で自分の不変条件を検証し、違反は `InvalidInputError`（ADR-0051）。
`temperature` はどの型にも属さないので `models.validate_temperature` が唯一の置き場になる。

### 入力ファイルの型（`inputs.py`、pydantic）

- `FCEnvelopeInput` — 入力ファイル全体。構造・単位・流儀だけを検査する
- `ModeSpec(frequency, coupling)` / `BroadeningSpec` / `EnergyGridSpec` / `GridPointsSpec`
  / `SelectionSpec`。`EnergyGridSpec.points` が `GridPointsSpec`（`n` / `de` / `shift`）
- `BroadeningSpec` と `EnergyGridSpec` は `_EnergySpec` を継承し、自分の `unit`（ブロックの
  **既定**の単位）と `.to_canonical(quantity)`（そのブロックの値を cm⁻¹ の数にする）を持つ
- `Quantity(value, unit)` — 有次元の値。`150.0` / `[150.0]` / `[0.0186, "eV"]` /
  `[18.6, 0.001, "eV"]` の書き方がここへ畳まれる（ADR-0072, 0078）。`unit` は `UnitForm`
  で、`None` なら既定の単位で読む。
  `.unit_or(default)` / `.in_canonical(default)` を持つ

範囲の検査は値の型に任せ、値の型が送出したエラーにフィールドの位置（`modes.rows[1]`、`grid` など）
を添える（ADR-0045, 0051）。

### 単位と流儀（`units.py`）

- `CouplingConvention(name, unit_kind, converter)` — 流儀。`.to_huang_rhys(coupling,
  frequency)` / `.is_dimensionless` / `.check_coupling_unit(unit)` /
  `.coupling_to_canonical(unit)`（ADR-0033）
- `G` / `DELTA` / `HUANG_RHYS` / `LAMBDA` / `VCC` と `COUPLING_CONVENTIONS`（名前 → 流儀）
- `UnitKind(name, factors, aliases)` — 単位の種類（ADR-0076）。`.resolve(written)` が
  `ResolvedUnit(form, factor)`（正式形と、倍率込みの換算係数）を返す。未知の名前や書き方の
  誤りは `UnsupportedUnitError`
- `ENERGY_UNIT_KIND`（`ENERGY_UNITS` と別名 `ENERGY_UNIT_ALIASES`）/ `VCC_UNIT_KIND`
  （正式名 `VCC_UNIT` = `hartree/(bohr*sqrt(m_e))`、ADR-0077）
- `UnitForm = str | tuple[float, str]` — 単位の書き方。名前だけか `(倍率, 名前)` の組（ADR-0078）
- `split_unit(written)` — 倍率と名前の切り分け。単位の種類によらない書き方だけの検査
- `ENERGY_UNITS`（正式名 → cm⁻¹ への換算係数）/ `energy_conversion_factor(unit)`
  （`ENERGY_UNIT_KIND.resolve(unit).factor`）/ `CANONICAL_ENERGY_UNIT`

換算係数は `scipy.constants` から導出し、自前の数値定数表は持たない。単位の追加は表への
1 行で済む（ADR-0054）。

`unit_kind` は coupling の単位の種類。無次元の流儀は `None`、λ は `ENERGY_UNIT_KIND`、
V は `VCC_UNIT_KIND` である。V をエネルギーのべき指数で持たないのは、実在しない
`eV^{3/2}` を受け付け、質量を含む実在の単位を表せないからである（ADR-0077）。

単位は正式名・別名・倍率からなり、入力の検証を通った後は常に**正式形**である
（ADR-0076）。エネルギーの欄はフィールドの検証器が、coupling の欄は流儀が見える
`FCEnvelopeInput` のモデルの検証器が正式形へ置き換える。

coupling と frequency の単位が揃うことは前提にできないので、両者はそれぞれの単位から
別々に正準単位へ直してから変換式に入る。coupling には流儀の単位の種類で引いた換算係数が
掛かる（ADR-0053）。振動数は変換式の前に `validate_frequency` で検査する（λ と V の変換式は
振動数で割るため、ADR-0077）。

### 結果（`result.py`、frozen dataclass）

- `Provenance(fcenvelope_version, created_at)` — 来歴（ADR-0046）
- `EnvelopeResult(system, temperature, broadening, grid, energy, density, diagnostics, provenance)`
- `LinesResult(system, temperature, selection, lines, diagnostics, provenance)`
- `FCLine(energy, fc_factor, weight, transitions)`
- `ModeTransition(mode_index, initial, final)` — 1 モードの n_α → m_α。`mode_index` は
  `system.modes` の位置（0 始まり）で、`.mode_number` が人に見せる番号（1 始まり）。結果
  ファイルと端末の表示は番号を使う
- `Diagnostics` / `FCLineDiagnostics` — 数値品質の診断値
- `Result = EnvelopeResult | LinesResult` / `AnyDiagnostics = Diagnostics | FCLineDiagnostics`
  — 種類によらず扱う関数が使う別名

結果クラスが持つのは**計算で決まったものだけ**である（ADR-0047）。λ は
`system.reorganization_energy` から得る。`LinesResult` は `.energies` / `.fc_factors` /
`.weights` を ndarray として返す。

## ファイル形式

### 入力

書式は TOML（`.toml`）と JSON（`.json`）の 2 つで、**拡張子だけ**で振り分ける
（`inputs.INPUT_FORMATS`、ADR-0069）。読んだ後は同じ辞書になるので、構造・単位・流儀の
扱いは以下どちらの書式でも同じである。利用者が書くのは TOML、実効設定の読み返しが JSON。雛形は
`src/fcenvelope/templates/input.toml` に実物の TOML ファイルとして置き、
`inputs.template_text()` が読むだけである（ADR-0074）。

```toml
schema_version = 4
temperature = 300.0

[modes]
frequency_unit = "cm^-1"
coupling_convention = "g"

[[modes.rows]]
frequency = 1200.0
coupling = 0.5

[[modes.rows]]
frequency = 450.0
coupling = 0.8

[broadening]
sigma = 150.0
unit = "cm^-1"

[grid]
e_min = -4500.0
e_max = 1000.0
unit = "cm^-1"

[grid.points]
de = 4.0

[selection]
min_weight = 0.0001
max_lines = 10000
# max_quanta は省略（TOML に null はない）
```

同じものを JSON で書くとこうなる。実効設定（`*_config.json`）もこの形である。

```json
{
  "schema_version": 4,
  "modes": {
    "coupling_convention": "g",
    "frequency_unit": "cm^-1",
    "coupling_unit": null,
    "rows": [
      { "frequency": 1200.0, "coupling": 0.5 },
      { "frequency":  450.0, "coupling": 0.8 }
    ]
  },
  "temperature": 300.0,
  "broadening": { "sigma": 150.0, "unit": "cm^-1" },
  "grid": {
    "e_min": -4500.0, "e_max": 1000.0, "unit": "cm^-1",
    "points": { "de": 4.0 }
  },
  "selection": { "min_weight": 0.0001, "max_lines": 10000, "max_quanta": null }
}
```

| フィールド | 型 | 制約 | 意味 |
|---|---|---|---|
| `schema_version` | int | `4` 固定 | 不一致は `SchemaVersionError`。古い版の互換層は置かない（ADR-0040, 0070, 0079） |
| `modes` | object | `rows` と `csv` のどちらか一方 | モード表（ADR-0079）。版 3 までの配列は拒否する |
| `modes.coupling_convention` | str | `"g"` \| `"delta"` \| `"huang_rhys"` \| `"lambda"` \| `"vcc"` | coupling の列の流儀。既定 `"g"` |
| `modes.frequency_unit` | str \| [倍率, str] | エネルギーの単位の正式名か別名。倍率は `[0.001, "eV"]` の組で書く | frequency の列の既定の単位。既定 `"cm^-1"` |
| `modes.coupling_unit` | str \| [倍率, str] \| null | 流儀の単位の種類の正式名か別名。倍率は組で書く | coupling の列の既定の単位。無次元の流儀では書いてはならず、有次元の流儀では要る。TOML では `null` を書けないので省略する |
| `modes.rows[].frequency` | 有次元 | > 0（正準化後） | ε_α。既定の単位は `modes.frequency_unit` |
| `modes.rows[].coupling` | 有次元 | 流儀による | 流儀に従った値。既定の単位は `modes.coupling_unit` |
| `modes.csv` | object | キーは `path` と `columns` | 行を CSV から読む。パース時に `rows` へ差し替わる |
| `modes.csv.path` | str | 空でない | CSV のパス。相対パスは入力ファイルのディレクトリ基準 |
| `modes.csv.columns` | list | 各列ちょうど 1 回。要素は `"列名"` / `["列名", "単位"]` / `["列名", 倍率, "単位"]` | 列の並びと列の単位。既定 `["frequency", "coupling"]` |
| `temperature` | float | ≥ 0 | T [K]。0 は許可（n_α = 0）。単位の軸を持たない |
| `broadening.sigma` | 有次元 | > 0 | σ。既定の単位は `broadening.unit` |
| `broadening.unit` | str \| [倍率, str] | エネルギーの単位の正式名か別名。倍率は `[0.001, "eV"]` の組で書く | ブロックの既定。既定 `"cm^-1"` |
| `grid.e_min` / `e_max` | 有次元 | `e_min` < `e_max` | 出力窓。既定の単位は `grid.unit` |
| `grid.unit` | str \| [倍率, str] | エネルギーの単位の正式名か別名。倍率は `[0.001, "eV"]` の組で書く | ブロックの既定。既定 `"cm^-1"` |
| `grid.points` | object | `n` と `de` のどちらか一方だけ | 全域グリッドの取り方（ADR-0070） |
| `grid.points.n` | int \| null | 2 の冪、≥ 2 | 全域グリッドの点数。ΔE = 2·e_half / n |
| `grid.points.de` | 有次元 \| null | > 0 | 出力グリッド間隔。既定の単位は `grid.unit` |
| `grid.points.shift` | int | ≥ 0、既定 0 | `de` のときだけ書ける。全域幅を保ったまま点数を 2^shift 倍 |
| `selection` | object | 省略可 | 省略時は `Selection` の既定値 |

単位フィールドは 4 つとも省略でき、省略時はすべて `cm^-1` である（coupling の単位は
流儀による）。単位の実例は `docs/readme/examples/` にある（ADR-0056）。

**有次元**の欄は、素の数値のほかに `[値, "単位"]` の組でも書ける（ADR-0072）。
`sigma = 0.0186` / `sigma = [0.0186]` / `sigma = [0.0186, "eV"]` と、倍率つきの
`sigma = [18.6, 0.001, "eV"]`（ADR-0078）が受け付けるすべてで、単位を添えなければ上の 4 つの単位フィールド（ブロックの既定）で読む。添えた単位はその値にだけ効き、既定より優先される。無次元の値
（`grid.points.n` / `shift` / `selection` の各つまみ / `temperature`）には書けない。

実効設定（`*_config.json`）は書いたままの姿で書き出す。素の数値で書けば素の数値、組で
書けば組で、単位フィールドは省略しても既定値で埋まって必ず書かれる（ADR-0065, 0072）。

`modes.rows` は最低 1 要素（TOML では `[[modes.rows]]` の並び）。代わりに
`modes.csv = {"path": "<file>.csv", "columns": [...]}` を置くと外部 CSV から行を読む
（ADR-0019, 0079）。CSV は RFC 4180 準拠で、列は `frequency` / `coupling` の 2 列のみ。
列に添えた単位は、その列のすべての値に `[値, "単位"]` と添えたものとして読むので、読んだ
後は行を直接書いた場合と区別がない。ヘッダは省略可で、ヘッダがあり `columns` が無ければ
ヘッダの並び、両方あれば並びが一致しなければ誤り。コメント行・空行・補助列は受け付けない。
CSV が報告するのは**構造の誤りだけ**で、行番号が付くのもそこまでである。値の範囲は正準化の
ときに値の型が見るので、位置はモードの番号（`modes.rows[i]`）になる。

CSV の読み込みは表一般の `inputs.read_csv_table(path, columns, build, *, explicit)` と、
それをモード表に使う `inputs.read_mode_specs_csv(path, columns=None)` に分かれる。列は
`inputs.CsvColumn(name, unit)` で表す。

`run` は `temperature` / `broadening` / `grid` を、`lines` は `temperature` / `selection` を
読む。どちらの副命令も同じファイルを使える（ADR-0005）。

実効設定の書き出し（`*_config.json`）は**常に JSON** である。省略した項目が既定値で埋まり、
`modes.csv` が `modes.rows` に展開されているだけで、入力ファイルとして読み返せる（ADR-0065）。TOML には
`null` がなく、「無し」で埋まった `coupling_unit` / `selection.max_quanta` を書けないため、
入力が TOML でも書き出しは JSON になる（ADR-0069）。

`--override` の値は入力ファイルの書式によらず JSON として読む（ADR-0064）。TOML 入力から
「無し」を渡せるのはこの口だけである。

### 出力（エンベロープ）

```json
{
  "schema_version": 4,
  "kind": "fcenvelope.envelope",
  "fcenvelope_version": "0.1.0",
  "created_at": "2026-09-17T03:21:44Z",
  "conditions": {
    "modes": {
      "frequency_unit": "cm^-1",
      "rows": [{ "frequency": 1200.0, "huang_rhys": 0.25 }]
    },
    "temperature": 300.0,
    "broadening": { "sigma": [150.0, "cm^-1"] },
    "grid": {
      "e_min": [-4500.0, "cm^-1"], "e_max": [1000.0, "cm^-1"],
      "de": [4.0, "cm^-1"], "n_fft": 4096
    }
  },
  "derived": { "reorganization_energy": [300.0, "cm^-1"] },
  "diagnostics": {
    "d_tau": [3.83e-4, "cm"], "tau_max": [0.785, "cm"],
    "sigma_tau_max": 117.8, "total_area": 0.9999999998,
    "window_captured_fraction": 0.9993,
    "edge_intensity_ratio": 4.9e-9,
    "max_imaginary_ratio": 8.4e-17,
    "messages": []
  },
  "spectrum": {
    "energy_unit": "cm^-1",
    "density_unit": "1/cm^-1",
    "energy": [-4500.0, -4496.0, "..."],
    "density": [4.6e-8, 4.4e-8, "..."]
  }
}
```

### 出力（線）

```json
{
  "schema_version": 4,
  "kind": "fcenvelope.fc_lines",
  "fcenvelope_version": "0.1.0",
  "created_at": "2026-09-17T01:23:45Z",
  "conditions": {
    "modes": {
      "frequency_unit": "cm^-1",
      "rows": [{ "frequency": 1200.0, "huang_rhys": 0.25 }]
    },
    "temperature": 300.0,
    "selection": { "min_weight": 0.0001, "max_lines": 10000, "max_quanta": null }
  },
  "derived": { "reorganization_energy": [300.0, "cm^-1"] },
  "diagnostics": {
    "n_lines": 58, "captured_weight": 0.997, "mean_energy": [-583.5, "cm^-1"], "...": "..."
  },
  "lines": {
    "energy_unit": "cm^-1",
    "rows": [
      { "energy": 0.0, "fc_factor": 0.41, "weight": 0.36, "transitions": [] },
      { "energy": -1200.0, "fc_factor": 0.19, "weight": 0.17,
        "transitions": [{ "mode": 1, "initial": 0, "final": 1 }] }
    ]
  }
}
```

どちらの出力も計算条件（`conditions`）は結果ファイル側の固定の形で、入力ファイルの形は
写さない（ADR-0080）。モードは振動数と Huang-Rhys 因子 S（`huang_rhys`）で書き、流儀の欄は
持たない。`grid` は解決済みの全域グリッドである。

単位は入力ファイルと同じ書き方で書く（ADR-0081）。有次元の値 1 つは `[値, "単位"]` の組、
表（`conditions.modes` / `spectrum` / `lines`）は表のブロックに `<列名>_unit` を書く。無次元の
値と温度（K）は素の数である。書き出す単位は常に正準単位（`cm^-1`、密度 `1/cm^-1`、τ `cm`）で、
読み込みはそれ以外の単位を `UnsupportedUnitError` で止める。

グリッドの点数は `conditions.grid.n_fft` だけに書き、診断値には重ねない。`lines` の
`transitions[].mode` はモード表の行の番号で、1 から数える。線のエネルギーは ZPL からの
符号付き変位で、振動量子を生成するサイドバンドが負側に立つ（上の「単位・規約」の E 軸）。`derived` は系から一意に決まる控えなので、書き出しはするが読み込み
時は読み飛ばす（ADR-0047）。`load → save` でファイルは変化しない（ADR-0008）。

結果ファイルの `schema_version` は 4 で、入力ファイルの版とは別に数える。入力の書き方が
変わっても上げない（ADR-0080）。`io` は `inputs` に依存しないため（ADR-0041）定数は別に持つ。

## CLI

```
fcenvelope run INPUT.json [-o RESULT.json] [--override KEY=VALUE]...
                          [--script FILE | --no-script] [--force-script]
                          [--config FILE | --no-config] [--log FILE]

fcenvelope lines INPUT.json [-o LINES.json] [--override KEY=VALUE]... [--top INT]
                          [--script FILE | --no-script] [--force-script]
                          [--config FILE | --no-config] [--log FILE]

fcenvelope script RESULT.json [LINES.json] -o PLOT.py [--force] [--log FILE]

fcenvelope template [-o INPUT.toml] [--force]

fcenvelope --version
```

`template` は入力ファイルの雛形を書き出す（ADR-0074）。`-o` がなければ標準出力へ、
あれば既存のファイルを残して（`--force` で上書き）そこへ書く。`.toml` 以外の拡張子は
使用法エラーである。計算も追跡すべき節目もないので `--log` は取らない。

**図のつまみは CLI にない**（ADR-0057）。調整は生成された作図スクリプトを直して行う。

### 出力の名前

`-o` は省略でき、省略時の出力は**入力ファイルの拡張子を除いた部分**に種類の接尾辞を
付けた名前で、**入力ファイルの隣**に置く（ADR-0063）。接尾辞があるので既定の出力名が
入力ファイルと一致することはなく、`run` と `lines` の出力も衝突しない。

| 呼び出し | 結果 | 実効設定 | 作図スクリプト |
|---|---|---|---|
| `fcenvelope run input.json` | `input_envelope.json` | `input_envelope_config.json` | `input_envelope_plot.py` |
| `fcenvelope lines input.json` | `input_lines.json` | `input_lines_config.json` | `input_lines_plot.py` |

結果と実効設定は既にあっても黙って上書きする。作図スクリプトだけが残る（ADR-0060）。
名前を変えながら掃引する実行では `-o` を書く。

### 上書き

入力ファイルの項目を差し替えるつまみは `--override KEY=VALUE` 1 つで、繰り返し指定できる
（ADR-0064）。

| 決め | 内容 |
|---|---|
| キー | 入力ファイル中の項目の位置。入れ子はドットで繋ぐ（`grid.points.de`、`broadening.sigma`） |
| 値 | JSON として読み、読めなければ文字列（`null` / `2.5` / `eV`） |
| 単位・流儀 | 入力ファイルのもの。`broadening.sigma` はファイルの `broadening.unit` で読む |
| 拒否する位置 | `modes` 以下（ADR-0012, 0035）と `schema_version` |
| 誤字 | 入力ファイルの型が `extra="forbid"` なので未知のフィールドとして弾かれる |

上書きの値は入力ファイルの型に適用してから正準化する（ADR-0050）。つまみの既定値は
`Selection` の 1 箇所にしかなく、CLI 側に項目の写しを持たない。使用法エラー（終了コード 2）に
なるのは**書式そのものの誤り**——`=` がない、キーが空、`modes` を指す、ブロックでない位置に
潜ろうとする——だけで、キーの存在と値の妥当性は入力の検証（終了コード 1）が見る。

### 実効設定

`run` と `lines` は、入力を読んで上書きを当てた直後、**計算を始める前**に、その実行で実際に
使われる設定を JSON で書き出す（ADR-0065）。書き出すのは正準化前の姿、すなわち**入力
ファイルと同じ単位・流儀**の値で、省略した項目は既定値で埋まり、`{"path": ...}` で渡した
モードは行に展開される。これを入力として与えれば同じ計算が再現できる。

結果ファイルの計算条件が常に正準形なのとは狙いが違う（ADR-0080）。計算条件は結果を読む側が
流儀と単位を気にせずに済むためのもの、実効設定は手元の入力ファイルと突き合わせ、再実行する
ためのものである。`--config FILE` で場所を変え、`--no-config` で書かせない。

`run` と `lines` は結果 JSON に添えて作図スクリプトを**既定で**書き出す（ADR-0060）。
生成先は `-o` の名前から作り（`result.json` → `result_plot.py`）、既にあれば書かずに
残して `kept ...` と知らせる。`--force-script` で上書き、`--no-script` で生成しない。
名前を変えながら掃引する実行では `--no-script` を使う。

`script` は保存済みの結果から作図スクリプトを書き出す。`kind` を見てエンベロープと棒
スペクトルのどちらかの雛形を選び、ファイルを 2 つ（エンベロープ 1 つと線リスト 1 つ、
順序は任意）渡すと重ね描きの雛形になる（ADR-0030 の規則をそのまま引き継ぐ）。種類の
組み合わせが違えば使用法エラー。壊したスクリプトを作り直す口でもある。

`--top N` は図ではなく結果の報告で、強い線を N 本まで端末に表として出す（旧 `--show`）。
入力ファイルに書けないものはフラグのまま残る——`--top` / `--log` / `--script` /
`--no-script` / `--force-script` / `--config` / `--no-config` がそれで、入力ファイルに
書けるものは `--override` を通る（ADR-0064）。
`--version` は副命令を取らず、パッケージ版だけを出して終了する。
終了コード: `0` 正常 / `1` `FCEnvelopeError` / `2` 使用法エラー。
品質の警告は結果の `Diagnostics.messages` から `warning: ...` として 1 度だけ出す。
`warnings` の表示はアプリケーションの入口で降ろしてある（ADR-0068）。

## 作図スクリプト

生成物は `json` と `matplotlib` だけで動き、`fcenvelope` を import しない（ADR-0058）。
雛形は `src/fcenvelope/templates/{envelope,lines,overlay}.py` にそのまま走る Python
ファイルとして置いてあり、生成が差し替えるのは生成ヘッダの区画だけである（ADR-0059）。

```python
# --- generated header (fcenvelope) ---------------------------------------
DATA = Path(__file__).parent / 'result.json'
OUTPUT = Path(__file__).parent / 'fcenvelope-result.png'
KIND = 'fcenvelope.envelope'
SCHEMA_VERSION = 2
# --- end generated header ------------------------------------------------
```

| 名前 | 何を決めるか |
|---|---|
| `SAVE` / `SHOW` | 出力先。`SHOW` が `None` なら端末のときだけ出す |
| `SHOW_WIDTH` / `SHOW_DPI` | 端末に出す図の大きさ。ファイルの `DPI` とは別（ADR-0061） |
| `IMAGE_PREFIX` | 引数でほかの結果を指したときの画像名の頭（ADR-0067） |
| `FIGSIZE` / `DPI` / `TITLE` / `XLIM` / `YLIM` / 色 | 図の体裁 |
| `X_UNIT` / `X_SCALE` | 横軸の単位（ADR-0062） |
| `MAGNIFY` | 重ね描きの棒の倍率（ADR-0028。凡例に出る） |

構造は 3 つの雛形で共通である。

| 関数 | 役目 |
|---|---|
| `beside(path)` | スクリプトの中に書いた相対パスを、スクリプトの隣として読む（ADR-0067） |
| `load(path, kind)` | 結果 JSON を読む。`kind` と `schema_version` が合わなければ止まる |
| `image_for(source)` | 図の書き出し先。既定のデータなら `OUTPUT`、引数でほかの結果を指したならその隣（ADR-0067） |
| `draw(ax, data)` | 図の中身。notebook から import して使える |
| `show(fig)` | kitty graphics protocol で端末に出す |
| `main()` | 読む → 描く → 画像と端末へ出す |

`beside` / `load` / `terminal_pixel_width` / `show` は 3 つの雛形で同一で、食い違わない
ことを `test/test_emit.py` が確かめる。`image_for` は雛形ごとに違う（単独の図はデータ 1 つ、
重ね描きはエンベロープを見る）ので共有部分には入らない。

パスの基準は 2 つあり、どちらも 1 つの規則で言える（ADR-0067）。スクリプトの中に書いた
名前はスクリプトの隣、コマンドラインの引数はカレントディレクトリである。`main` が引数を
`Path(...).absolute()` で先に絶対パスへ直すので、以降は生成ヘッダの位置と同じに扱える。

画像には見た目に出ない覚え書き（`Software` / `Source` / `Description`）が入る。`Source`
には生成時のデータ名ではなく、**実際に読んだデータ**の名前が入る。

`--log FILE` は節目のログの書き出し先（下の「ログ」を参照）。省略時は書き出さない。

## 型注釈の方針

`Any` は「構造が分からないことが分かっている」位置にだけ置き、それ以外は具体的な型を書く。
分からなさには 2 種類あるので、置き場も 2 つに分ける。

| 位置 | 書き方 | 理由 |
|---|---|---|
| 検証前の JSON の値で、そのまま先へ渡すもの | `io.JsonValue`（= `Any`） | `json.loads` の戻りそのもの。ファイルの中身は外部のもので狭められない |
| 検証前の値を、その場で調べて返すだけのもの | `object` | 何も仮定しないことを型で言える。pydantic の `mode="before"` 検証器がこれ |
| 種類によらず結果を扱うもの | `Result` | 種類が 2 つであることを型から消さない |
| 種類ごとに要素の型が違う表 | `_ResultKind[_R]` を `dict[str, _ResultKind[Any]]` に | 行の組み立ては型で検査され、`Any` は入れ物にだけ残る |

**計算の途中の測定値は `dict[str, Any]` に入れない。** 診断値クラスをそのまま組み立て、
判定で決まる `messages` だけを `dataclasses.replace` で後から入れる。測定値用の入れ物を
別に作るとフィールド名を 2 箇所に書くことになり、ADR-0036 が消したはずの重複が戻る。

JSON は型を保証しないので、読み込み側は数のつもりの位置に文字列・真偽値・辞書が来ることを
前提にする。どの位置に何が入っていても、送出するのは `FCEnvelopeError` の派生だけである
（ADR-0013）。真偽値は Python では `int` なので、数を期待する位置では明示的に弾く。

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

## ログ

節目（ファイルの読み書き・重い数値計算・図の書き出し）だけを標準ライブラリの `logging` で
記録する（ADR-0052）。ロガーは `fcenvelope` で、各モジュールはその下に `__name__` で枝を
持つ。パッケージ側は `NullHandler` だけを付けるので、ハンドラを足さない限り何も出ない。

```python
logs.stage(logger, label)   # 節目の開始と完了を 1 行ずつ。ループの内側では使わない
logs.Trace(path=None)       # CLI の出力先。None ならメモリに溜め、dump(path) で書き出す
```

| 水準 | 何が出るか |
|---|---|
| INFO | 節目の `begin <label>` / `end <label> (N.NNN s)`、および読み込み・計算の要約 1 行 |
| WARNING | 利用者に出している警告（品質・重ね描きの食い違い・窓から外れた線）と同じ文言 |
| ERROR | CLI が異常終了するときの 1 行 |

標準出力は**利用者への直接のメッセージ**、ログは**何が起きたかの記録**である。宛先が違うので
警告とエラーは両方に出る。結果の要約（`wrote ...`・線の表）は前者だけ、節目は後者だけに出す。
警告の文言は発報側が 1 箇所で持ち、発報と記録に同じものを渡す。ログのために新しい警告は
作らない（ADR-0052）。

例外で節目を抜けた場合は `end` 行を書かない。開始行だけが残るという形が「そこで止まった」
を意味する。**記録の数は入力の規模に依存しない**。モード数や線の本数で行数が増えないことは
`test/test_logging.py` で確かめる。

CLI は `--log FILE` が指定されたときだけ最初からファイルへ書く。指定がなければ記録はメモリに
溜まるだけで、異常終了したときにだけ `-o` の拡張子を `.log` に替えた場所へ書き出す。異常終了は
`FCEnvelopeError`・想定外の例外・Ctrl-C の 3 つで、使用法エラーは含まない（どこまで進んだかの
話ではないため）。正常に終わった実行はログのためのファイル IO を 1 回も行わない。

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
| `logs.py` | 節目のログの出力先（ADR-0052） | errors |
| `models.py` | 計算用の値の型 | errors, physics |
| `units.py` | 流儀オブジェクト、エネルギー単位の換算表 | errors |
| `inputs.py` | 入力ファイルの型（pydantic）と正準化、実効設定の書き出し、入力の雛形 | errors, logs, units, models |
| `result.py` | 結果クラス、`Provenance` | models |
| `envelope.py` | グリッド構成・FFT | errors, logs, models, result |
| `lines.py` | 漸化式・線の列挙 | errors, logs, models, physics, result |
| `io.py` | 保存・読み込み、`kind` の表 | errors, logs, models, result |
| `plotting.py` | 描画、結果の型の表 | errors, logs, result |
| `emit.py` | 作図スクリプトの生成、雛形の表。**描かない**（matplotlib に依存しない） | errors, io, logs, result |
| `cli.py` | typer アプリ | 上記すべて |

`envelope.py` と `lines.py` は互いに依存しない。`io.py` は `inputs.py` に依存しない
（ADR-0041）。matplotlib は `plotting.py` と雛形、typer は `cli.py`、pydantic は
`inputs.py` に閉じ込める。`emit.py` が `io.py` に依存するのは、生成ヘッダに書く `kind` と
`schema_version` がファイル形式の知識だからである（ADR-0049 により直書きしない）。

種類による振り分けは関心ごとの表に置く（ADR-0049）。

| モジュール | 表 |
|---|---|
| `io.py` | `RESULT_KINDS`: `kind` → 保存・読み込み・単位 |
| `plotting.py` | `DRAWERS`: 結果の型 → 描画 |
| `emit.py` | `TEMPLATES`: 結果の型 → 雛形の名前 |
| `cli.py` | `REPORTERS`: 結果の型 → 報告 |

重ね描きは表に載せず専用の関数のままにする。すべての表が同じ種類を網羅していることは
`test/test_dispatch.py` で確かめる。

## 将来の拡張のための足場

物理モデルは変位型調和振動子に固定されており（ADR-0017）、振動数変化も Duschinsky 回転も
将来にわたり対象外である。そのうえで、以下の拡張は**構造としては入る場所が決まっている**。
いずれも機能そのものは未実装で、足場だけがある。

| 将来の機能 | 入る場所 | 参照 |
|---|---|---|
| ローレンツ型・Voigt 型の線形状 | `Broadening`。線形状の知識はここに閉じており、`envelope.py` と `plotting.py` は種類を知らない | ADR-0034、提案 ADR-0038 / 0039 |
| matplotlib 以外のツール向けの雛形 | `emit.py` の `TEMPLATES` と生成先の拡張子。多くのツールは JSON を読めないので、列指向のデータ書き出しを決めるところから始まる（ADR-0010 を開き直す） | ADR-0058 |
| 入力フォーマットの見直し | `inputs.py`。入力ファイルの型と計算用の値の型が分かれており、計算側に触れずに変えられる | ADR-0045 |
| 非対角な基底からの入力（対角化） | 別命令 `fcenvelope diagonalize` として足し、出力のモード CSV を `modes.csv` で読む。正準化の行き先は `VibrationalSystem` 1 つ | 提案 ADR-0037、ADR-0044 |
| 結果の種類の追加 | 関心ごとの表（`RESULT_KINDS` / `DRAWERS` / `REPORTERS`）に行を足す | ADR-0049 |

「提案」の ADR は、その機能を実装するときに確定する。
