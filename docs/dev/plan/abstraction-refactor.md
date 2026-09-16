# 抽象化リファクタリング 作業計画

コア機能の実装が一巡したため、実装済みの概念を整理し、不変な部分を抽象化した形へ
置き換える。**この文書は実装者への引き継ぎ用**である。決定そのものは `docs/adr/`、語彙は
`CONTEXT.md`、現行の仕様は `docs/dev/spec/interface.md` にある。

## 前提

- **目的は抽象化であって、新機能の実装ではない。** 将来入れる予定の機能（下表）は、
  抽象化の形を決めるための判断材料として使う。新しい構造から自然に出てくる機能を無理に
  止める必要はないが、機能の追加を作業の目標にはしない。
- **今の振る舞いを厳密に保つ必要はない。** 下表の完成形に近づく変更であれば、公開 API も
  ファイル形式も変わってよい。v1 は実運用に上げていない。
- **物理モデルは固定**。変位型調和振動子から出ない。振動数変化も Duschinsky 回転も将来に
  わたり対象外。

| 将来の機能 | このリファクタリングで用意すること | 実装時の検討材料 |
|---|---|---|
| ローレンツ型・Voigt 型の線形状 | ガウス型の知識を `Broadening` に集める。数値計算と診断値の判定を分ける | ADR-0038, 0039（提案） |
| 入力の単位変換、流儀 V・λ | 流儀をオブジェクトにする。入力ファイルの型と計算用の値の型を分ける | `docs/theory/vcc.md` |
| 入力フォーマットの見直し | 入力ファイルの型を `inputs.py` に分離する | — |
| 非対角な基底からの入力（対角化） | 正準化の行き先を `VibrationalSystem` 1 つに決める。パーサに計算を入れない | ADR-0037（提案） |
| 結果の種類の追加（予定はないがありうる） | 種類による振り分けを表にする | — |

## 非目的

- 上表の機能そのものの実装。
- 数値アルゴリズムの改良（漸化式を Laguerre 陽形式へ置き換える等）。ADR-0024 の方針は
  維持する。
- 性能改善。

---

## 目標の形

### 計算用の値（`models.py`、frozen dataclass、ADR-0044, 0045, 0051）

```python
VibrationalMode(frequency, huang_rhys)
VibrationalSystem(modes: tuple[VibrationalMode, ...])
    .frequencies                 # ndarray
    .huang_rhys                  # ndarray
    .reorganization_energy       # λ（ADR-0047）
    .occupations(temperature)    # n_α。式は physics.py
Broadening(sigma)                # ガウス型の知識を持つ: 減衰因子・頂点値・打ち切りの指標（ADR-0034）
EnergyGrid(e_min, e_max, de)
Selection(min_weight=1e-4, max_lines=10000, max_quanta=None)   # 既定値はここだけ（ADR-0050）
```

どの型も `__post_init__` で自分の不変条件を検証し、違反は `InvalidInputError` にする
（ADR-0051）。pydantic には依存しない。

### 結果（`result.py`、ADR-0031, 0032, 0046, 0047）

```python
Provenance(fcenvelope_version, created_at)          # 来歴

EnvelopeResult(system, temperature, broadening, grid,
               energy, density, diagnostics, provenance)
LinesResult(system, temperature, selection,
            lines, diagnostics, provenance)
FCLine(energy, fc_factor, weight, transitions)
```

結果クラスは λ も単位も持たない。λ は `system.reorganization_energy` から得る。単位と
`derived` の書き出しは io の責務。

共通部分は意味でまとめる（ADR-0046）。来歴は `Provenance`、系は `VibrationalSystem`、
温度は独立したフィールド。両系統で共有する計算の補助（閾値など）は今は存在しないので、
そのためのクラスは作らない。

### 公開 API（ADR-0011, 0048）

```python
compute_envelope(system, *, temperature, broadening, grid) -> EnvelopeResult
compute_fc_lines(system, *, temperature, selection=Selection()) -> LinesResult

save_envelope / load_envelope / plot_envelope
save_lines    / load_lines    / plot_lines
plot_overlay(envelope, lines, *, ax=None, magnify=1.0, ...)

fc_factor_matrix(huang_rhys, m_max, n_max=0) -> np.ndarray
```

### 入力ファイル（`inputs.py`、pydantic、ADR-0040, 0045）

```json
{
  "schema_version": 2,
  "frequency_unit": "cm^-1",
  "coupling_convention": "g",
  "modes": [{ "frequency": 1200.0, "coupling": 0.5 }],
  "temperature": 300.0,
  "broadening": { "sigma": 150.0 },
  "grid": { "e_min": -4000.0, "e_max": 1000.0, "de": 5.0 },
  "selection": { "min_weight": 0.0001, "max_lines": 10000, "max_quanta": null }
}
```

入力ファイルの型は構造・単位・流儀を検査し、正準化して計算用の値を返す。範囲の検査は
値の型に任せ、値の型が送出したエラーにフィールドの位置を添える（ADR-0051）。

`run` は `temperature` / `broadening` / `grid` を、`lines` は `temperature` / `selection` を
読む。`selection` は省略でき、省略時は `Selection` の既定値を使う。

### モジュール（ADR-0041）

| モジュール | 依存先 |
|---|---|
| `errors.py` | — |
| `physics.py` | errors |
| `models.py` | errors, physics |
| `units.py` | errors |
| `inputs.py` | errors, units, models |
| `result.py` | models |
| `envelope.py` / `lines.py` | physics, models, result（互いに依存しない） |
| `io.py` / `plotting.py` | models, result（`io` は `inputs` に依存しない） |
| `cli.py` | 上記すべて |

`physics.py` は配列と数値だけを扱い、モデルの型を知らない。

---

## 作業の段階

各段階の完了条件は **`uv run pytest` が緑になること**。段階をまたいで赤のまま進めない。

### 段階 0 — 許容誤差の修正（ADR-0042）

現在 `test_fc_factor.py::test_recurrence_matches_the_closed_form[6.0]` が
1.488e-11 < 1e-11 で落ちている。**リファクタリング前に緑にしておく**。

判定を `max|rec − ana| / max|ana| < 1e-9` に変える。要素ごとの相対誤差は使えない（要素の
大半がほぼ 0 で 0/0 になる）。許容誤差の根拠と、これが ADR-0024 の破綻とは別物である
ことをコメントに残す。

> 検算値: S=6, m≤25, n≤12 で 1.488e-11 / 0.4008 = 3.7e-11。破綻は S=25・n=29 から始まり、
> そこでの列和のずれは −0.26 と桁違いに大きい。

### 段階 1 — 改名とモジュールの分割（ADR-0031, 0032, 0041）

振る舞いを変えない機械的な置換。

| 旧 | 新 |
|---|---|
| `core.py` | `physics.py`（`K_B_CM`, `occupation_numbers`, `boltzmann_populations`）と `envelope.py`（`build_grids`, `compute_envelope`） |
| `fcfactor.py` | `lines.py`。`boltzmann_populations` は `physics.py` へ |
| `FCEnvelopeResult` / `FCLinesResult` | `EnvelopeResult` / `LinesResult` |
| `EnvelopeResult.intensity` | `.density` |
| `FCLine.intensity` | `.weight` |
| `min_intensity` / `captured_intensity` | `min_weight` / `captured_weight` |
| `save_result` / `load_result` / `plot_result` | `save_envelope` / `load_envelope` / `plot_envelope` |
| `save_fc_lines` / `load_fc_lines` / `plot_fc_lines` | `save_lines` / `load_lines` / `plot_lines` |
| `kind = "fcenvelope.result"` | `"fcenvelope.envelope"` |
| JSON `spectrum.intensity` / `lines[].intensity` | `spectrum.density` / `lines[].weight` |

`lines.py` が `envelope.py` を import しないことを確認する（現在の `fcfactor → core` の
向きが、この段階で解消すべき歪み）。

### 段階 2 — 計算用の値の型と入力ファイルの型を分ける（ADR-0035, 0040, 0044, 0045, 0050, 0051）

1. `models.py` に `VibrationalMode`, `VibrationalSystem`, `Broadening`, `EnergyGrid`,
   `Selection` を frozen dataclass として置く。各型は `__post_init__` で不変条件を検証する。
   `Conditions` は削除する。
2. `physics.py` からモデルの型への依存を取り除く（`reorganization_energy(modes)` は
   `VibrationalSystem.reorganization_energy` に置き換える）。
3. `models.py` の入力ファイル部分（`FCEnvelopeInput`, `ModeSpec`, CSV の読み込み）を
   `inputs.py` へ移し、入力ファイルの形を `schema_version` 2 にする。1 は
   `SchemaVersionError` で拒否する。範囲の検査は値の型に任せ、エラーにフィールドの位置を
   添える。
4. `compute_envelope` / `compute_fc_lines` の引数を目標の形にする。
5. CLI の上書きを入力ファイルの型に対して行い、その後で正準化する。CLI の既定値は
   `None`（上書きしない）にし、`Selection` の既定値との二重定義をなくす。
6. `data/*.json` を再生成する。

### 段階 3 — 結果クラスの形を変える（ADR-0046, 0047）

1. `result.py` に `Provenance` を置き、結果クラスの `fcenvelope_version` / `created_at` を
   まとめる。
2. 結果クラスを目標の形にする。`modes` → `system`、条件は `temperature` と
   `broadening` / `grid`、または `selection` をそのまま持つ。
3. `reorganization_energy` と単位のフィールドを結果クラスから外す。io は保存時に `derived`
   と単位を書き出し、読み込み時は `derived` を読み飛ばす。
4. `io` の読み込みで、入力エコーから `inputs.py` を経由せず値の型を直接作る。
5. 重ね描きの前提チェック（ADR-0029）を `system` と `temperature` の比較にする。

`LinesResult` が `Selection` を丸ごと持つことで、`max_quanta` が結果に記録されていなかった
穴が閉じる。

### 段階 4 — 計算の中を分け、ガウス型の知識を `Broadening` に集める（ADR-0034, 0048）

1. 各計算関数の中を「数値計算」「診断値の判定」「結果の組み立て」に分ける。警告を発報して
   `messages` に記録する処理は共通の補助関数にする。メッセージ本文は各系統に手書きで残す
   （ADR-0036）。
2. ガウス型であることに依存したコードを `Broadening` に移し、`envelope.py` と
   `plotting.py` が線形状の種類を知らなくてよい形にする。

   | 現在の場所 | 中身 |
   |---|---|
   | `core.py` の `damping = -0.5 * sigma**2 * tau**2` | 時間領域の減衰因子 |
   | `plotting._gaussian_peak` | 規格化された線形状の頂点値 1/(σ√(2π)) |
   | `core.py` の `sigma_tau_max` と閾値 6 | τ 窓の打ち切りの指標 |

計算するのはガウス型だけで、γ を足すことはこの段階の目的ではない。

### 段階 5 — 流儀をオブジェクトにする（ADR-0033）

`units.py` を作り、`CouplingConvention` を Enum と関数表からオブジェクトにする。各流儀が
持つべき情報は次のとおり。

- S への変換（coupling と frequency を受け取る）
- 単位を持つか（g, Δ, S は無次元。V, λ は持つ）
- 持つ場合、frequency の単位とどう組み合わさるか

現在の型 `Callable[[float], float]` は V（S = V²/2ħω³）と λ（S = λ/ħω）を構造的に表現
できない。関係式は `docs/theory/vcc.md` の表にある。V と λ を足すことはこの段階の目的
ではない。足せる構造にすることが目的。

### 段階 6 — 振り分けの表と機械的な重複の除去（ADR-0036, 0049）

1. `io.py` に `kind` → 保存・読み込みの表、`plotting.py` に結果の型 → 描画の表、`cli.py`
   に結果の型 → 報告の表を置く。`load_any`、`_save_figure` などの if 文と `isinstance` を
   表引きに置き換える。
2. すべての表が同じ種類を網羅していることを確かめるテストを足す。
3. 重ね描きは表に載せず専用の関数のまま。CLI の組み合わせ判定のエラー文は、種類名を表から
   引き、`kind` 文字列を直接書かない。
4. `io.py` のフィールド名タプルを `dataclasses.fields()` から導出し、共通ヘッダの読み書きを
   1 箇所にまとめる。
5. `plotting.py` の軸の用意・表題・凡例の重複をまとめる。

### 段階 7 — 文書の追随

- `docs/dev/spec/interface.md` を実装後の姿に更新する。
- `README.md` の使用例を新しい API に合わせる。
- `CONTEXT.md` の語と、コード中の識別子・docstring・警告文言が食い違っていないことを
  確認する。特に「線強度」→「重み」、「モード列」→「系」。

---

## 検証

`uv run pytest`。既存のテストは ADR-0015 / ADR-0026 の恒等式を軸にしており、改名と構造の
変更に追随させれば数値の検証はそのまま生き残る。特に強いのは次の 1 本で、リファクタリング
中はこれを壊さないことを最優先にする。

> **線をガウシアンで畳んだものがエンベロープに一致する** — エンベロープ（FFT）と
> 離散線（漸化式）は共通コードをほとんど持たない独立な 2 実装なので、両者の一致は片方
> だけを見ていては気づけない誤りを捕まえる（ADR-0026）。

段階 2 以降で新しく足すテスト:

- 値の型が不変条件の違反で `InvalidInputError` を送出する（ライブラリから直接作った場合）
- 入力ファイル経由の範囲違反で、エラーにフィールドの位置が含まれる
- CLI の上書きが入力ファイルと同じ単位で解釈される
- `LinesResult` の保存・読み込みで `max_quanta` が往復する
- 振り分けの表がすべて同じ種類を網羅している
