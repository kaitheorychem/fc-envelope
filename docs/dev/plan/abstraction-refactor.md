# 抽象化リファクタリング 作業計画

コア機能の実装が一巡したため、実装済みの概念を整理し、不変な部分を抽象化した形へ
置き換える。**この文書は実装者への引き継ぎ用**であり、決定そのものは `docs/adr/` に、
語彙は `CONTEXT.md` に、現行の仕様は `docs/dev/spec/interface.md` にある。

## 前提

- **破壊的変更は自由**。公開 API もファイル形式も互換を保つ必要はない。v1 は実運用に
  上げていない。
- **物理モデルは固定**。変位型調和振動子から出ない。振動数変化も Duschinsky 回転も
  将来にわたり対象外。したがって `VibrationalMode` と ρ(τ) の間に継ぎ目を作らない。
- **拡張軸は線形状のみ**（ガウス → ローレンツ / Voigt）。
- 決定の根拠は ADR-0031〜0043。各段階の冒頭に該当 ADR を記す。

## 非目的

- 数値アルゴリズムの改良（漸化式を Laguerre 陽形式へ置き換える等）。ADR-0024 の方針は
  維持する。
- 性能改善。
- 吸収／発光の区別（ADR-0001）。

---

## 目標インターフェイス

```python
# 計算
compute_envelope(modes, *, temperature: float,
                 broadening: Broadening, grid: EnergyGrid) -> EnvelopeResult
compute_fc_lines(modes, *, temperature: float,
                 selection: Selection = Selection()) -> LinesResult

# 永続化・描画（系統ごとに 4 関数）
save_envelope / load_envelope / plot_envelope
save_lines    / load_lines    / plot_lines
plot_overlay(envelope, lines, *, ax=None, magnify=1.0, ...)

# 理論式そのもの
fc_factor_matrix(huang_rhys, m_max, n_max=0) -> np.ndarray

# 値型
VibrationalMode(frequency, huang_rhys)
Broadening(sigma, gamma)            # 少なくとも一方 > 0、両方 >= 0
EnergyGrid(e_min, e_max, de)
Selection(min_weight=1e-4, max_lines=10000, max_quanta=None)
```

入力 JSON（`schema_version` = 2）:

```json
{
  "schema_version": 2,
  "frequency_unit": "cm^-1",
  "coupling_convention": "g",
  "modes": [{ "frequency": 1200.0, "coupling": 0.5 }],
  "temperature": 300.0,
  "broadening": { "sigma": 150.0, "gamma": 0.0 },
  "grid": { "e_min": -4000.0, "e_max": 1000.0, "de": 5.0 },
  "selection": { "min_weight": 0.0001, "max_lines": 10000, "max_quanta": null }
}
```

`run` は `temperature` / `broadening` / `grid` を、`lines` は `temperature` / `selection` を
読む。互いに相手の節を無視する。`modes` は上書きしない（ADR-0012）。

モジュール階層（ADR-0041）:

```
errors → units → models → physics → result → { envelope, lines } → { io, plotting } → cli
                              normalmodes ↗
```

---

## 作業の段階

各段階の完了条件は **`uv run pytest` が緑になること**。段階をまたいで赤のまま進めない。

### 段階 0 — 許容誤差の修正（ADR-0042）

現在 `test_fc_factor.py::test_recurrence_matches_the_closed_form[6.0]` が
1.488e-11 < 1e-11 で落ちている。**リファクタリング前に緑にしておく**。

判定を `max|rec − ana| / max|ana| < 1e-9` に変える。要素ごとの相対誤差は使えない
（要素の大半がほぼ 0 で 0/0 になる）。許容誤差の根拠と、これが ADR-0024 の破綻とは
別物であることをコメントに残す。

> 検算値: S=6, m≤25, n≤12 で 1.488e-11 / 0.4008 = 3.7e-11。破綻は S=25・n=29 から始まり、
> そこでの列和のずれは −0.26 と桁違いに大きい。

### 段階 1 — 改名とモジュール再配置（ADR-0031, 0032, 0041）

**振る舞いを一切変えない。** 純粋な機械的置換。

| 旧 | 新 |
|---|---|
| `core.py` | `physics.py`（K_B_CM, `occupation_numbers`, `boltzmann_populations`, `reorganization_energy`）と `envelope.py`（`build_grids`, `compute_envelope`）に分割 |
| `fcfactor.py` | `lines.py`。`boltzmann_populations` は `physics.py` へ移す |
| `FCEnvelopeResult` / `FCLinesResult` | `EnvelopeResult` / `LinesResult` |
| `EnvelopeResult.intensity` | `.density` |
| `FCLine.intensity` | `.weight` |
| `min_intensity` / `captured_intensity` | `min_weight` / `captured_weight` |
| `save_result` / `load_result` / `plot_result` | `save_envelope` / `load_envelope` / `plot_envelope` |
| `save_fc_lines` / `load_fc_lines` / `plot_fc_lines` | `save_lines` / `load_lines` / `plot_lines` |
| `kind = "fcenvelope.result"` | `"fcenvelope.envelope"` |
| JSON `spectrum.intensity` | `spectrum.density` |
| JSON `lines[].intensity` | `lines[].weight` |

`lines.py` が `physics.py` だけを見て `envelope.py` を見ないことを確認する（現在
`fcfactor → core` という向きがあり、これが歪みの本体）。

### 段階 2 — `Conditions` の 4 分割（ADR-0035, 0040）

`Conditions` を削除し、`Broadening` / `EnergyGrid` / `Selection` を `models.py` に置く。
この段階では `Broadening.gamma` を受け取って保持するが、まだ計算には効かせない
（既定 0.0）。`schema_version` を 2 に上げ、1 は `SchemaVersionError` で拒否する。

**`LinesResult` は `Selection` を丸ごとエコーする**こと。従来 `max_quanta` だけが結果に
記録されず、結果ファイルから計算を再現できない穴があった。オブジェクトごと持たせれば
この穴は構造的に閉じる（ADR-0035）。

`data/*.json` は再生成する。

### 段階 3 — 線形状の 2 パラメータ化（ADR-0034, 0038, 0039）

1. `envelope.py` の減衰項を `exp(-0.5*σ²τ² - γ*|τ|)` にする。
2. 検証を `sigma > 0` から「σ ≥ 0, γ ≥ 0 かつ少なくとも一方 > 0」に変える。
3. 診断値 `sigma_tau_max` を `damping_at_tau_max = exp(−σ²τ_max²/2 − γ·τ_max)` に差し替え、
   閾値を `> 1.523e-8`（= e⁻¹⁸）で警告とする。γ=0 では現行の「σ·τ_max ≥ 6」と等価。
4. `plot_overlay` の棒の高さを Voigt の頂点へ一般化する。

   ```python
   from scipy.special import wofz
   def lineshape_peak(sigma: float, gamma: float) -> float:
       a = gamma / (sigma * math.sqrt(2.0))
       return wofz(1j * a).real / (sigma * math.sqrt(2.0 * math.pi))
   ```
   σ → 0 の分岐（純ローレンツ）では `1 / (math.pi * gamma)` を直接返す。

追加すべきテスト:

- γ = 0 で段階 2 までと完全一致（回帰）
- σ → 0 の純ローレンツで `lineshape_peak` が 1/(πγ) に一致
- Voigt の頂点値が、減衰因子の逆フーリエ変換の E=0 値と一致（検証済み: 相対差 ~1e-11）
- Voigt でも 0 次モーメント ∫F dE = 1 が成り立つ
- 2 次モーメントはローレンツ成分では発散するため、**σ 成分のみで検証する**か、
  γ > 0 では 2 次モーメントの検証を行わない

> 注意: ADR-0015 の 2 次モーメント恒等式 Var(E) = Σ S_α ε_α²(2n_α+1) + σ² は、ローレンツ
> 成分を入れると成立しない（ローレンツ分布は分散を持たない）。γ > 0 のテストでは 0 次と
> 1 次だけを使うこと。

### 段階 4 — 流儀のオブジェクト化（ADR-0033）

`units.py` を作り、`CouplingConvention` を Enum + 関数表からオブジェクトへ昇格させる。
各流儀が持つべき情報:

- S への変換（coupling と frequency を受け取る）
- 単位を持つか（g, Δ, S は無次元。V, λ は持つ）
- 持つ場合、frequency の単位とどう組み合わさるか

現在の型 `Callable[[float], float]` は V（S = V²/2ħω³）と λ（S = λ/ħω）を**構造的に
表現できない**。関係式は `docs/theory/vcc.md` の表にある。V と λ を実際に足すかは任意
だが、**足せる構造にすること**がこの段階の目的。

### 段階 5 — `io.py` の機械的重複の除去（ADR-0036）

- `_DIAGNOSTIC_FLOAT_FIELDS` 等の手書きタプルを `dataclasses.fields()` から導出する。
- 共通ヘッダ（`schema_version` / `kind` / 単位 / 来歴 / 入力エコー / `derived` /
  `diagnostics`）の読み書きを 1 箇所にまとめる。

**`_quality_messages` は統合しない。** 構造は似ているが、閾値の向きも型も違い、メッセージ
本文がすべて違う。本文は「どう直すか」というその項目固有の知識を持っており、雛形に
押し込めると診断機能の価値が失われる（ADR-0036）。

### 段階 6 — 文書の追随

- `docs/dev/spec/interface.md` を実装後の姿に更新する（現在は段階 0 時点の記述）。
- `README.md` の使用例を新しい API に合わせる。
- `CONTEXT.md` に定義した語と、コード中の識別子・docstring・警告文言が食い違っていない
  ことを確認する。特に「線強度」→「重み」。

### 段階 7 — `diagonalize`（別タスク。今回のスコープ外）

非対角項を含む基底からの入力（ADR-0037）。`normalmodes.py` と `fcenvelope diagonalize`
サブコマンドを足す。出力は現行のモード表 CSV とし、`modes` の参照形態は増やさない。
並進・回転を落とす閾値は既定値を置かず引数で明示必須にする。

---

## 検証

`uv run pytest`。既存のテストは ADR-0015 / ADR-0026 の恒等式を軸にしており、改名に
追随させれば数値の検証はそのまま生き残る。特に強いのは次の 1 本で、リファクタリング中は
これを壊さないことを最優先にする。

> **線をガウシアンで畳んだものがエンベロープに一致する** — エンベロープ（FFT）と
> 離散線（漸化式）は共通コードをほとんど持たない独立な 2 実装なので、両者の一致は片方
> だけを見ていては気づけない誤りを捕まえる（ADR-0026）。
