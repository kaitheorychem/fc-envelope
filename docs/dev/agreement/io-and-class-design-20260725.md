# 入出力・クラス設計の合意

- 日付: 2026-07-25
- 種別: **イミュータブル**（原則更新せず、変更時は新文書を追加）
- 位置づけ: `README.md` と `docs/theory/time-ft.md` に記された構想を、実装可能な粒度の入出力仕様・クラス設計へ落とし込んだもの。v1 実装の出発点となる決定事項を記録する。

> [!IMPORTANT]
> **この文書は仕様書ではない。**
> ここに書かれているのは「ある時点で交わした検討・合意」であり、現在のシステム仕様を反映するものではない。
> 実装が進めば現実のコードとは食い違っていく前提で読むこと。

---

## 1. スコープ

v1 で実装するのは **Franck-Condon エンベロープ F(E) の計算・永続化・可視化のみ**。

計算対象は `docs/theory/time-ft.md` の式そのもの：

$$
F(E)=\frac{1}{2\pi} \int d\tau\, \rho(\tau)\, e^{iE\tau -\frac12\sigma^2 \tau^2}
$$

$$
\rho(\tau)=\prod_\alpha \exp\left(-S_\alpha(2n_\alpha+1)+S_\alpha(n_\alpha+1)e^{i\varepsilon_\alpha\tau} + S_\alpha n_\alpha e^{-i\varepsilon_\alpha\tau}\right)
$$

$$
n_\alpha=\frac{1}{e^{\varepsilon_\alpha/k_BT}-1}
$$

### 1.1 吸収・発光スペクトルを含めない判断

検討の結果、**v1 では吸収／発光の区別を導入しない**。

理由と背景：

- FC エンベロープ自体は吸収でも発光でもない中立な量であり、`spectrum_type` のようなフラグは F(E) の計算には不要。
- 吸収・発光へ進む際に追加で必要になるのは薄い層のみ（E ↔ ℏω_photon の写像と E_00、振動数プレファクタ ℏω / (ℏω)³、屈折率因子、遷移双極子モーメントによる絶対強度規格化）。したがって将来 `fcenvelope.spectra` のようなラッパー層として後付けできる。
- ただし**薄くない差分が一つある**：厳密には吸収は始状態＝基底状態、発光は始状態＝励起状態であり、それぞれの状態の ω_α・n_α を使う。両者を同一のモードセットで済ませるのは鏡像（mirror-image）近似である。この近似を破って2状態分の振動数を扱うには ρ(τ) の構造自体に手が入るため、v1 のスコープ外とする。

## 2. 単位系と正準量

| 項目 | 決定 |
|---|---|
| エネルギーの正準単位 | **cm⁻¹**。入力・内部・出力のすべてで cm⁻¹ 固定 |
| τ（E の共役変数） | cm（εα·τ が無次元になる） |
| 温度 | K |
| 振電相互作用の正準量 | **S_α（Huang-Rhys 因子）**。理論文書の g とは S = g² の関係 |
| 強度 F(E) の単位 | 1/cm⁻¹（∫F dE = 1 が成り立つ密度） |

### 2.1 単位変換の扱い

v1 では cm⁻¹ 以外を受け付けない。ただし将来の拡張に備え、**単位を保持・検証する場所だけ確保する**：

- 入力 JSON は `frequency_unit` フィールドを持つ。`"cm^-1"` 以外なら `UnsupportedUnitError` で即座に reject する。
- 出力 JSON は `energy_unit` / `intensity_unit` を持つ。
- 数値は素の `float` / `ndarray` として保持し、単位ライブラリ（pint 等）は導入しない。将来変換を入れる場合は、この「検証点」を「変換点」に差し替えるだけで済む形にする。
- 変換ロジックを自前で実装することはしない。必要になった時点で変換ライブラリに委譲する。

### 2.2 g の流儀

`ρ(τ)` の中で g は常に g² の形でしか現れず、g の符号は物理的に無意味である。したがって内部正準量は S とし、√ の往復を発生させない。副次的に、再編成エネルギー λ = Σ_α S_α ℏω_α が自然に得られる。

v1 で受け付ける入力の流儀は **2 種のみ**：

| `coupling_convention` | 変換式 |
|---|---|
| `"g"` | S = g² |
| `"huang_rhys"` | S = S（恒等） |

変換は Enum + 変換関数のレジストリとして実装し、流儀の追加が 1 エントリで済む形にする。無次元変位 Δ（S = Δ²/2）や再編成エネルギー λ_α（S = λ_α/ℏω_α）は、必要になった時点でレジストリに追加する。

## 3. E 軸の符号規約

**理論文書の式をそのまま実装する。** 符号の反転は行わない。

- E = 0 が ZPL（zero-phonon line）。E は ZPL からの符号付きエネルギー変位。
- 振動量子を k 個生成するサイドバンドは **E = −k·ε_α**（負側）に立つ。
- 有限温度では (n+1) 項と n 項が非対称なため、**F(E) 自体が左右非対称**である。この向きは吸収/発光の区別とは無関係に F(E) が持つ固有の性質であり、規約として固定する。
- 向きの反転が必要になった場合は、将来のラッパー層（§1.1）の責務とする。
- v1 では E_00 オフセットを持たない。E 軸は常に ZPL 相対。

検算用：T=0・単一モードで展開すると

$$
F(E)=e^{-S}\sum_{k=0}^{\infty}\frac{S^k}{k!}\,\mathcal{N}(E;\,-k\varepsilon,\,\sigma)
$$

（𝒩 は中心 −kε・標準偏差 σ の正規分布密度）

## 4. 入力仕様

### 4.1 方針

- **1 ファイルに全部**。モードデータ（分子固有）と計算条件（T, σ, E グリッド）を同じ JSON に入れ、その 1 ファイルで計算が完全に再現できるようにする。
- 条件を振りたい場合は **CLI オプションで上書き**する（§9.1）。
- `frequency_unit` / `coupling_convention` は**トップレベル**に置き、**パース時に消費されて消える**。パース後の内部表現は常に (frequency [cm⁻¹], huang_rhys) に正準化されており、それ以降のコードは流儀も単位も知らない。
- `modes` は**行指向**（1 モード = 1 オブジェクト）。長さ不一致というバグのクラスが原理的に生じず、将来 `label` / `symmetry` 等をモード単位で追加しやすい。
- モード側のキー名は convention によらず常に `coupling` で固定。

### 4.2 スキーマ

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

`modes` は最低 1 要素。

### 4.3 E グリッドの取り決め

`e_min` / `e_max` / `de` を明示指定する。省略値も自動推定も設けない（条件を振ったときにグリッドが黙って変わるのを避けるため）。

FFT の都合上、内部では 0 対称なグリッドで計算してから切り出す：

1. `E_h = max(|e_min|, |e_max|)`
2. `N = next_pow2(ceil(2 * E_h / de))`（N は 2 のべき、偶数）
3. `Δτ = 2π / (N * de)`
4. 全域グリッド `E_j = j * de`, `j = -N/2 .. N/2-1`
5. 計算後に `e_min <= E_j <= e_max` を満たす範囲へスライス

この取り方により、**出力の ΔE は指定した `de` ちょうど**になり、**E = 0（ZPL）が必ずグリッド点上に乗る**。一方で出力の端点は `de` の整数倍にスナップされる（`e_min` / `e_max` ちょうどとは限らない）。

推奨レンジの目安（強制はしない）：`e_min ≲ -(λ + 5√Var)`、`e_max ≳ +5σ`。ここで λ・Var は §11 の定義による。

## 5. 数値アルゴリズム

### 5.1 手法

**FFT（`numpy.fft`）**。ユーザは E グリッドのみを指定し、τ グリッドは §4.3 の手順で内部導出する。

### 5.2 離散化

`M(τ) = ρ(τ) · exp(-σ²τ²/2)` として、

$$
F(E_j) \approx \frac{\Delta\tau}{2\pi}\sum_k M(\tau_k)\,e^{iE_j\tau_k}
= \frac{1}{\Delta E}\,\mathrm{ifft}(M)_j
$$

τ グリッドと E グリッドをともに FFT 標準順序（`0, 1, …, N/2-1, -N/2, …, -1`）で持てば、余分な位相因子なしに上式がそのまま成立する。表示用に単調増加へ並べ替えるのは最後の `fftshift` のみ。

この形から、離散和についても

$$
\sum_j F(E_j)\,\Delta E = M(\tau=0) = 1
$$

が**厳密に**成り立つ。これを実装検証の軸に使う（§7）。

### 5.3 実装上の措置

- **占有数**：`n_α = 1 / expm1(ε_α / (k_B T))` で計算する。`expm1` により ε/kT が大きい領域でのオーバーフローが `inf` → `n = 0` と正しく畳まれる。`T = 0` は分岐して `n_α = 0` を直接与える。
- **k_B**：`scipy.constants` から cm⁻¹/K 単位の値を導出する（`k / (h * c * 100)`）。定数値を自前でハードコードしない。
- **メモリ**：`ln ρ` を長さ N の complex128 配列に持ち、**モードについてループで加算**する。全モード × 全 τ の外積を作らない（N = 2¹⁷・200 モードで数百 MB になるため）。
- **実数化**：`ρ(-τ) = ρ(τ)*` より F(E) は数学的に実数。実装は `.real` を取り、`max|Im| / max|Re|` を診断値として記録する（§7）。

## 6. データモデル

### 6.1 基盤の使い分け

- **境界（入力 JSON のパース・検証）＝ pydantic v2**。フィールドパス付きのエラーメッセージが自動生成され、typer とも相性が良い。
- **結果クラス（ndarray を抱える）＝ frozen dataclass**。pydantic の `arbitrary_types_allowed` の濁りと、大配列の検証コストを避ける。

### 6.2 クラス一覧

`models.py`（pydantic v2, すべて `BaseModel`）

```python
class VibrationalMode(BaseModel):      # 正準表現
    frequency: float                   # > 0, cm^-1
    huang_rhys: float                  # >= 0

class Conditions(BaseModel):           # 正準かつファイル表現（変換不要のため共用）
    temperature: float                 # >= 0, K
    sigma: float                       # > 0, cm^-1
    e_min: float
    e_max: float                       # e_min < e_max
    de: float                          # > 0

class ModeSpec(BaseModel):             # 入力ファイル中の1モード（流儀依存）
    frequency: float
    coupling: float

class FCEnvelopeInput(BaseModel):      # 入力ファイル全体
    schema_version: Literal[1] = 1
    frequency_unit: Literal["cm^-1"] = "cm^-1"
    coupling_convention: CouplingConvention = CouplingConvention.G
    modes: list[ModeSpec]              # min_length=1
    conditions: Conditions

    def to_modes(self) -> list[VibrationalMode]: ...   # 流儀を消費して正準化
```

`result.py`（frozen dataclass）

```python
@dataclass(frozen=True, slots=True)
class Diagnostics:
    n_fft: int                          # N
    d_tau: float                        # Δτ [cm]
    tau_max: float                      # π / de [cm]
    sigma_tau_max: float                # σ · τ_max（打ち切り指標）
    total_area: float                   # Σ F·de（全域）。厳密に 1 のはず
    window_captured_fraction: float     # 切り出し窓内に残った面積の割合
    edge_intensity_ratio: float         # 全域グリッド端の強度 / ピーク強度
    max_imaginary_ratio: float          # max|Im F| / max|Re F|
    messages: tuple[str, ...]           # 発報した警告の文言

@dataclass(frozen=True, slots=True)
class FCEnvelopeResult:
    energy: np.ndarray                  # (M,) float64, cm^-1, 単調増加
    intensity: np.ndarray               # (M,) float64, 1/cm^-1
    modes: tuple[VibrationalMode, ...]  # 入力エコー（正準形）
    conditions: Conditions              # 入力エコー
    reorganization_energy: float        # λ = Σ S_α ε_α [cm^-1]
    diagnostics: Diagnostics
    fcenvelope_version: str             # 計算時のパッケージ版
    created_at: datetime                # 計算時刻（UTC）
    energy_unit: str = "cm^-1"
    intensity_unit: str = "1/cm^-1"
```

`fcenvelope_version` / `created_at` は**計算時に確定して結果クラスが保持する**。保存時に付与しない。これにより `load → save` の往復でファイルが変化しない。

## 7. 数値品質の診断

計算は常に完走させ、品質は診断値として記録する。閾値を超えたものは `NumericalQualityWarning`（`UserWarning` 派生）で `warnings.warn` するとともに、その文言を `Diagnostics.messages` に残す。**出力ファイルだけを後から見て信頼可否を判定できる**ことを重視する。

各診断値は互いに異なる失敗モードを検出する：

| 診断値 | 検出する問題 | 閾値の目安 |
|---|---|---|
| `sigma_tau_max` = σ·π/de | **打ち切りリンギング**。de が σ に対して粗いと τ 窓が短く、ガウス減衰の完了前に打ち切られる | < 6 で警告（≒ de > σ/2） |
| `edge_intensity_ratio` | **エイリアシング**。E 範囲が狭くスペクトル重みが折り返している | > 1e-4 で警告 |
| `total_area` | **実装の誤り**（規格化因子・グリッド構成）。§5.2 より厳密に 1 になるはずの量。エイリアシングでは重みが畳み込まれて戻るため 1 のまま変化せず、この指標では検出できない点に注意 | \|1 − area\| > 1e-6 で警告 |
| `window_captured_fraction` | **切り出し窓が狭い**（計算自体は正しいが見えている範囲が不足） | < 0.99 で警告 |
| `max_imaginary_ratio` | **対称性の破れ**（ρ の実装ミス） | > 1e-8 で警告 |

## 8. 出力仕様

### 8.1 形式

**単一 JSON**。round-trip の正準形式とする。入力エコー・スペクトル配列・診断値・来歴を 1 ファイルに収め、`load_result` がこのファイルだけから結果クラスを完全に復元できるようにする。

N = 2¹⁴〜2¹⁷ 点で 0.3〜3 MB 程度のテキストになるが、エディタで中身が見え diff も取れる利点を優先し、これは割り切る。CSV 等の他形式エクスポートは v1 では設けない。

浮動小数点は Python 標準 `json` の `repr` ベース出力により round-trip で完全一致する。

### 8.2 スキーマ

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

入力エコーは**正準形**で書き出す（`coupling_convention` は常に `"huang_rhys"`、`coupling` は S の値）。これにより `load_result` に流儀の曖昧さが残らない。

`schema_version` が一致しない場合は `SchemaVersionError`。

## 9. 公開 API

`fcenvelope/__init__.py` から**自由関数 4 つ**を公開する。結果クラスは純粋なデータ容器に保ち、I/O と描画の責務を持たせない。これにより matplotlib への依存を `plotting.py` に隔離できる。

```python
def compute_envelope(
    modes: Sequence[VibrationalMode],
    conditions: Conditions,
) -> FCEnvelopeResult: ...

def save_result(result: FCEnvelopeResult, path: str | Path) -> None: ...

def load_result(path: str | Path) -> FCEnvelopeResult: ...

def plot_result(
    result: FCEnvelopeResult,
    *,
    ax: matplotlib.axes.Axes | None = None,
    label: str | None = None,
    title: str | None = None,
) -> matplotlib.figure.Figure: ...
```

- `compute_envelope` の引数は `modes` と `conditions` の 2 つ。入力 JSON のトップレベル `{"modes": [...], "conditions": {...}}` と 1:1 で対応する。
- `plot_result` は `Figure` を返すのみで、ファイル保存はしない。`ax` を受け取れるため複数条件を 1 枚に重ね描きでき、ノートブックでもそのまま表示される。保存は呼び出し側（CLI）が `fig.savefig()` を行う。
- 入力ファイルの読み込みは `FCEnvelopeInput` を経由する（`FCEnvelopeInput.model_validate_json` → `to_modes()` / `.conditions`）。

### 9.1 CLI

`typer` による 2 サブコマンド構成。エントリポイントは `fcenvelope.cli:app`。

```
fcenvelope run INPUT.json -o RESULT.json [--plot FIG.png]
                          [--temperature FLOAT] [--sigma FLOAT]
                          [--e-min FLOAT] [--e-max FLOAT] [--de FLOAT]

fcenvelope plot RESULT.json -o FIG.png [--title TEXT] [--dpi INT]
```

- CLI で上書きできるのは `conditions` の 5 フィールドのみ。`modes` は上書き対象にしない。
- `plot` サブコマンドにより、重い計算をやり直さずに見た目だけ調整できる。
- 終了コード: `0` 正常 / `1` `FCEnvelopeError` / `2` typer の使用法エラー。

## 10. モジュール構成とエラー設計

### 10.1 モジュール

`src/fcenvelope/` を責任別に 7 ファイルへ分割する。依存は `errors → models → result → {io, plotting} → cli` の一方通行で循環はない。matplotlib を `plotting.py` に、typer を `cli.py` に閉じ込めるのが主目的。

| ファイル | 責務 |
|---|---|
| `errors.py` | 例外・警告クラス |
| `models.py` | pydantic モデル、流儀レジストリ、単位検証 |
| `result.py` | `FCEnvelopeResult` / `Diagnostics` |
| `core.py` | 占有数、ρ(τ)、グリッド構成、FFT、診断値算出 |
| `io.py` | `save_result` / `load_result` |
| `plotting.py` | `plot_result` |
| `cli.py` | typer アプリ |

### 10.2 例外階層

```
FCEnvelopeError(Exception)
├── InvalidInputError        # 値の範囲・整合性の違反。pydantic ValidationError をラップ
├── UnsupportedUnitError     # frequency_unit / energy_unit が cm^-1 でない
└── SchemaVersionError       # schema_version の不一致

NumericalQualityWarning(UserWarning)
```

- pydantic の `ValidationError` は I/O 境界で `InvalidInputError` にラップして送出する。利用側は `except FCEnvelopeError` で一括でき、CLI はそれを捕捉して短いメッセージ + 終了コードを返す（トレースバックを出さない）。

## 11. テスト方針

**解析解・モーメント恒等式による検証を中核**に据える。参照データファイルの保守が不要で、数値コアを改良してもテストが生き残るため。

`M(τ) = ρ(τ)e^{−σ²τ²/2}` のモーメント展開から、以下が**厳密に**成り立つ：

| 次数 | 恒等式 | 備考 |
|---|---|---|
| 0 次 | ∫F dE = 1 | 規格化因子の検証 |
| 1 次 | ⟨E⟩ = −λ、λ = Σ_α S_α ε_α | **温度に依存しない**。符号規約（§3）とも整合 |
| 2 次 | Var(E) = Σ_α S_α ε_α²(2n_α+1) + σ² | **ここにのみ温度が効く** |

温度の扱いを誤ると 2 次モーメントだけが静かにずれるため、この 3 本が効く。

テスト項目：

- `test_moments.py` — 上記 3 恒等式を、複数温度（0 K / 77 K / 300 K）× 複数モードで検証
- `test_single_mode_t0.py` — T=0・単一モードで §3 のポアソン級数と厳密一致
- `test_conventions.py` — `g = 0.5` と `huang_rhys = 0.25` が同一結果を与える
- `test_io.py` — `save → load` の round-trip（配列・メタデータとも完全一致）
- `test_validation.py` — 単位不一致、`schema_version` 不一致、`e_min >= e_max`、負の温度、空の `modes`
- `test_diagnostics.py` — 粗い `de` で `sigma_tau_max` 警告、狭い窓で `edge_intensity_ratio` 上昇
- `test_cli.py` — typer `CliRunner` による `run` / `plot` の疎通と終了コード

## 12. 依存関係

| パッケージ | 用途 | 区分 |
|---|---|---|
| `numpy` | 配列・FFT | 必須 |
| `scipy` | `scipy.constants`（k_B）、将来の単位変換の受け皿 | 必須 |
| `pydantic` (v2) | 入力の検証 | 必須 |
| `typer` | CLI | 必須 |
| `matplotlib` | 描画 | 必須 |
| `pytest` | テスト | dev |

Python 3.11 以上。extras による分割は行わない（README の `uv sync` → `uv run fcenvelope` が素の同期だけで動くことを優先）。

## 13. 明示的なスコープ外

以下は v1 では実装しない。将来検討する場合は新たな合意文書を起こす。

- 吸収／発光スペクトル（E_00、振動数プレファクタ、屈折率因子、遷移双極子による絶対強度規格化）— §1.1
- 鏡像近似を破る扱い（基底状態と励起状態で異なる ω_α・S_α）、Duschinsky 回転
- 非調和性、モード間結合
- cm⁻¹ 以外の単位の受け入れ、および単位変換の自前実装 — §2.1
- ガウス以外の広がり（ローレンツ、Voigt）、σ のモード依存
- 温度スキャン等のバッチ実行機能（CLI の繰り返し呼び出しで代替）
- CSV / NPZ 等の追加出力形式
- `validate` / `info` などの追加サブコマンド
- 無次元変位 Δ・再編成エネルギー λ_α・質量重み付き変位 ΔQ による coupling 入力 — §2.2
